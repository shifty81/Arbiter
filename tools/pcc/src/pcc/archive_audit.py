from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


def _sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream)


def _safe_project_file(root: Path, value: str) -> Path:
    pure = PurePosixPath(value.replace("\\", "/").strip())
    if not pure.parts or pure.is_absolute() or ".." in pure.parts or ":" in pure.parts[0]:
        raise ValueError(f"archive path must be project-relative: {value}")
    candidate = root.joinpath(*pure.parts)
    resolved_root = root.resolve()
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"archive path escapes project root: {value}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"archive does not exist: {value}")
    return resolved


def _cortex_crate(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if len(parts) >= 2 and parts[0] == "crates" and parts[1].startswith("cortex_"):
        return parts[1]
    return None


def audit_archive(project_root: Path, archive_value: str, prefix: str = "") -> dict[str, Any]:
    root = project_root.resolve()
    archive_path = _safe_project_file(root, archive_value)
    normalized_prefix = prefix.replace("\\", "/").strip("/")
    prefix_with_slash = f"{normalized_prefix}/" if normalized_prefix else ""

    archive_files: dict[str, tuple[int, str]] = {}
    duplicate_entries: list[str] = []
    max_entries = 100_000
    max_entry_bytes = 256 * 1024 * 1024
    max_total_bytes = 2 * 1024 * 1024 * 1024
    total_archive_bytes = 0
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > max_entries:
            raise ValueError(f"archive contains too many entries: {len(infos)} > {max_entries}")
        for info in infos:
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/").lstrip("./")
            if normalized_prefix and not (name == normalized_prefix or name.startswith(prefix_with_slash)):
                continue
            if name in archive_files:
                duplicate_entries.append(name)
                continue
            if info.file_size > max_entry_bytes:
                raise ValueError(f"archive entry exceeds bounded audit size: {name}")
            total_archive_bytes += info.file_size
            if total_archive_bytes > max_total_bytes:
                raise ValueError("archive exceeds bounded total audit size")
            with archive.open(info, "r") as stream:
                archive_files[name] = (info.file_size, _sha256_stream(stream))

    project_files: dict[str, tuple[int, str]] = {}
    scan_root = root / normalized_prefix if normalized_prefix else root
    if scan_root.exists():
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            project_files[relative] = (path.stat().st_size, _sha256_file(path))

    archive_paths = set(archive_files)
    project_paths = set(project_files)
    shared_paths = archive_paths & project_paths
    equal = sorted(path for path in shared_paths if archive_files[path][1] == project_files[path][1])
    changed = sorted(path for path in shared_paths if archive_files[path][1] != project_files[path][1])
    archive_only = sorted(archive_paths - project_paths)
    project_only = sorted(project_paths - archive_paths)

    archive_crates = {crate for path in archive_paths if (crate := _cortex_crate(path))}
    project_crates = {crate for path in project_paths if (crate := _cortex_crate(path))}
    shared_crates = sorted(archive_crates & project_crates)
    crate_rows: list[dict[str, Any]] = []
    for crate in shared_crates:
        marker = f"crates/{crate}/"
        crate_equal = [path for path in equal if path.startswith(marker)]
        crate_changed = [path for path in changed if path.startswith(marker)]
        crate_archive_only = [path for path in archive_only if path.startswith(marker)]
        crate_project_only = [path for path in project_only if path.startswith(marker)]
        crate_rows.append(
            {
                "crate": crate,
                "equal_files": len(crate_equal),
                "changed_files": len(crate_changed),
                "archive_only_files": len(crate_archive_only),
                "project_only_files": len(crate_project_only),
                "state": "equal"
                if not crate_changed and not crate_archive_only and not crate_project_only
                else "different",
                "changed_paths": crate_changed,
                "archive_only_paths": crate_archive_only,
                "project_only_paths": crate_project_only,
            }
        )

    return {
        "schema": "pcc.archive_audit.v1",
        "archive": str(archive_path),
        "prefix": normalized_prefix,
        "archive_file_count": len(archive_files),
        "project_file_count": len(project_files),
        "shared_file_count": len(shared_paths),
        "equal_file_count": len(equal),
        "changed_file_count": len(changed),
        "archive_only_file_count": len(archive_only),
        "project_only_file_count": len(project_only),
        "duplicate_archive_entries": sorted(duplicate_entries),
        "cortex_crates": {
            "archive": sorted(archive_crates),
            "project": sorted(project_crates),
            "shared": shared_crates,
            "archive_only": sorted(archive_crates - project_crates),
            "project_only": sorted(project_crates - archive_crates),
            "shared_count": len(shared_crates),
        },
        "crate_parity": crate_rows,
        "changed_paths": changed,
        "archive_only_paths": archive_only,
        "project_only_paths": project_only,
    }
