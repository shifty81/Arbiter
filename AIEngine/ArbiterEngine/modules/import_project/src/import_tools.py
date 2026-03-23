"""Import Project module — copy local folders into the SwissAgent workspace."""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Any


def _workspace_root() -> Path:
    """Return the SwissAgent project root's workspace directory."""
    # This file lives at <root>/modules/import_project/src/import_tools.py
    return Path(__file__).resolve().parents[3] / "workspace"


def _expand(path: str) -> Path:
    """Expand ~ and environment variables in a path string."""
    return Path(os.path.expandvars(os.path.expanduser(path))).resolve()


def import_project(
    source_path: str,
    destination_name: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Copy a local folder into ``workspace/`` for development.

    Args:
        source_path:      Absolute or ``~``-relative path to the folder to import.
        destination_name: Name for the folder inside ``workspace/``.
                          Defaults to the source folder's own name.
        overwrite:        Replace the destination if it already exists.

    Returns:
        A dict describing the result (``success``, ``source``, ``destination``,
        ``files_copied``, ``message``) or an ``{"error": "…"}`` dict on failure.
    """
    src = _expand(source_path)

    if not src.exists():
        return {"error": f"Source path does not exist: {src}"}
    if not src.is_dir():
        return {"error": f"Source path is not a directory: {src}"}

    name = destination_name.strip() if destination_name else src.name
    if not name:
        return {"error": "Could not determine a destination name. Please provide one."}

    workspace = _workspace_root()
    dst = workspace / name

    if dst.exists():
        if not overwrite:
            return {
                "error": (
                    f"Destination '{dst}' already exists. "
                    "Set overwrite=true to replace it."
                )
            }
        shutil.rmtree(dst)

    # Guard against copying a directory into itself.  Use os.path.samefile()
    # for robust cross-platform comparison (handles Windows case-insensitivity).
    ignore_fn = None
    try:
        dst_rel = dst.relative_to(src)
        skip_name = dst_rel.parts[0]

        def ignore_fn(directory: str, contents: list) -> set:  # type: ignore[misc]
            try:
                if os.path.samefile(directory, str(src)):
                    return {skip_name}
            except OSError:
                pass
            return set()
    except ValueError:
        pass  # dst is not inside src — normal case, no ignore needed

    # Only create workspace/ now (after guard setup) to minimise the window
    # where an in-progress copy sees the newly created directory.
    workspace.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copytree(src, dst, ignore=ignore_fn)
    except Exception as exc:
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        return {"error": f"Copy failed: {exc}"}

    file_count = sum(1 for _ in dst.rglob("*") if _.is_file())

    return {
        "success": True,
        "source": str(src),
        "destination": str(dst),
        "workspace_path": f"workspace/{name}",
        "files_copied": file_count,
        "message": (
            f"Project '{name}' imported successfully from {src} → "
            f"workspace/{name} ({file_count} files)."
        ),
    }


def scan_folder(path: str, max_depth: int = 2) -> dict[str, Any]:
    """List the contents of a local folder to inspect it before importing.

    Args:
        path:      Absolute or ``~``-relative path to the folder to scan.
        max_depth: How many directory levels to recurse (default 2).

    Returns:
        A dict with ``path``, ``exists``, ``entries`` (nested tree), and
        ``summary`` counts, or an ``{"error": "…"}`` dict on failure.
    """
    target = _expand(path)

    if not target.exists():
        return {"error": f"Path does not exist: {target}", "exists": False}
    if not target.is_dir():
        return {"error": f"Path is not a directory: {target}", "exists": True}

    def _walk(directory: Path, depth: int) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        try:
            items = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return [{"name": "<permission denied>", "type": "error"}]
        for item in items:
            entry: dict[str, Any] = {
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            }
            if item.is_file():
                entry["size_bytes"] = item.stat().st_size
            if item.is_dir() and depth > 0:
                entry["children"] = _walk(item, depth - 1)
            entries.append(entry)
        return entries

    entries = _walk(target, max(0, max_depth - 1))
    total_files = sum(1 for _ in target.rglob("*") if _.is_file())
    total_dirs = sum(1 for _ in target.rglob("*") if _.is_dir())

    # Detect common project markers
    markers = {
        "CMakeLists.txt": "C/C++ (CMake)",
        "package.json": "Node.js / JavaScript",
        "Cargo.toml": "Rust (Cargo)",
        "pyproject.toml": "Python",
        "setup.py": "Python",
        "Makefile": "Make",
        "build.gradle": "Java/Kotlin (Gradle)",
        "pom.xml": "Java (Maven)",
        ".git": "Git repository",
    }
    detected = [label for marker, label in markers.items() if (target / marker).exists()]

    return {
        "path": str(target),
        "exists": True,
        "entries": entries,
        "summary": {
            "total_files": total_files,
            "total_dirs": total_dirs,
            "detected_project_types": detected,
        },
        "suggestion": (
            f"To import: import_project(source_path='{target}', "
            f"destination_name='{target.name}')"
        ),
    }
