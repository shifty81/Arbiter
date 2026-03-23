"""Resource module — ZIP-based resource bundle operations."""
from __future__ import annotations
import hashlib
import json
import time
import zipfile
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_MANIFEST_ENTRY = "__manifest__.json"


def _read_manifest(bundle: str) -> dict:
    """Read the embedded manifest from a resource bundle ZIP."""
    with zipfile.ZipFile(bundle, "r") as zf:
        if _MANIFEST_ENTRY in zf.namelist():
            return json.loads(zf.read(_MANIFEST_ENTRY).decode())
    return {}


def _write_manifest(bundle: str, manifest: dict) -> None:
    """Update the manifest stored inside an existing bundle ZIP."""
    # Rewrite whole archive to update manifest (zipfile doesn't support deletion)
    tmp_path = Path(bundle).with_suffix(".tmp.zip")
    with zipfile.ZipFile(bundle, "r") as src_zf:
        with zipfile.ZipFile(str(tmp_path), "w", compression=zipfile.ZIP_DEFLATED) as dst_zf:
            for item in src_zf.infolist():
                if item.filename == _MANIFEST_ENTRY:
                    continue
                dst_zf.writestr(item, src_zf.read(item.filename))
            dst_zf.writestr(_MANIFEST_ENTRY, json.dumps(manifest, indent=2))
    tmp_path.replace(bundle)


def resource_pack(input_dir: str, output: str, manifest: str | None = None, **kwargs) -> dict:
    """Pack all files from *input_dir* into a ZIP resource bundle at *output*.

    An auto-generated manifest listing all packed resources is embedded inside
    the bundle as ``__manifest__.json``.  Pass an external *manifest* JSON file
    path to merge extra metadata.
    """
    root = Path(input_dir)
    if not root.is_dir():
        return {"status": "error", "error": f"Input directory not found: {input_dir}"}

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    extra_meta: dict = {}
    if manifest:
        mp = Path(manifest)
        if mp.exists():
            try:
                extra_meta = json.loads(mp.read_text())
            except json.JSONDecodeError:
                pass

    resources: list[dict] = []
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            arc_name = str(f.relative_to(root))
            zf.write(f, arc_name)
            resources.append({
                "name": arc_name,
                "size_bytes": f.stat().st_size,
                "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
            })

        bundle_manifest = {
            "created_at": time.time(),
            "resource_count": len(resources),
            "resources": resources,
            **extra_meta,
        }
        zf.writestr(_MANIFEST_ENTRY, json.dumps(bundle_manifest, indent=2))

    return {
        "status": "ok",
        "bundle": str(out_path),
        "resource_count": len(resources),
        "size_bytes": out_path.stat().st_size,
    }


def resource_unpack(bundle: str, output_dir: str, **kwargs) -> dict:
    """Extract a resource bundle ZIP to *output_dir*, skipping the manifest entry."""
    bundle_path = Path(bundle)
    if not bundle_path.exists():
        return {"status": "error", "error": f"Bundle not found: {bundle}"}

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    extracted: list[str] = []
    with zipfile.ZipFile(bundle, "r") as zf:
        for item in zf.infolist():
            if item.filename == _MANIFEST_ENTRY:
                continue
            zf.extract(item, path=out)
            extracted.append(item.filename)

    return {"status": "ok", "output_dir": str(out), "extracted": extracted, "count": len(extracted)}


def resource_list(bundle: str, **kwargs) -> dict:
    """List all resources stored in *bundle*."""
    bundle_path = Path(bundle)
    if not bundle_path.exists():
        return {"status": "error", "error": f"Bundle not found: {bundle}"}

    manifest = _read_manifest(bundle)
    if manifest:
        resources = manifest.get("resources", [])
    else:
        with zipfile.ZipFile(bundle, "r") as zf:
            resources = [
                {"name": i.filename, "size_bytes": i.file_size}
                for i in zf.infolist()
                if i.filename != _MANIFEST_ENTRY
            ]

    return {"status": "ok", "bundle": bundle, "resources": resources, "count": len(resources)}


def resource_add(bundle: str, path: str, alias: str | None = None, **kwargs) -> dict:
    """Add a single file *path* to an existing bundle, stored under *alias* (or filename)."""
    bundle_path = Path(bundle)
    if not bundle_path.exists():
        return {"status": "error", "error": f"Bundle not found: {bundle}"}

    src = Path(path)
    if not src.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    arc_name = alias or src.name

    # Re-write bundle with new file appended
    manifest = _read_manifest(bundle)
    resources: list[dict] = manifest.get("resources", [])

    tmp = bundle_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(bundle, "r") as src_zf:
        with zipfile.ZipFile(str(tmp), "w", compression=zipfile.ZIP_DEFLATED) as dst_zf:
            for item in src_zf.infolist():
                if item.filename in (_MANIFEST_ENTRY, arc_name):
                    continue
                dst_zf.writestr(item, src_zf.read(item.filename))
            dst_zf.write(src, arc_name)
            # Remove existing entry for same name
            resources = [r for r in resources if r.get("name") != arc_name]
            resources.append({
                "name": arc_name,
                "size_bytes": src.stat().st_size,
                "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
            })
            manifest["resources"] = resources
            manifest["resource_count"] = len(resources)
            dst_zf.writestr(_MANIFEST_ENTRY, json.dumps(manifest, indent=2))
    tmp.replace(bundle)

    return {"status": "ok", "bundle": bundle, "added": arc_name}


def resource_remove(bundle: str, name: str, **kwargs) -> dict:
    """Remove the resource *name* from *bundle*."""
    bundle_path = Path(bundle)
    if not bundle_path.exists():
        return {"status": "error", "error": f"Bundle not found: {bundle}"}

    manifest = _read_manifest(bundle)
    resources: list[dict] = manifest.get("resources", [])

    found = any(r.get("name") == name for r in resources)
    with zipfile.ZipFile(bundle, "r") as src_zf:
        names_in_zip = src_zf.namelist()

    if name not in names_in_zip:
        return {"status": "error", "error": f"Resource '{name}' not found in bundle"}

    tmp = bundle_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(bundle, "r") as src_zf:
        with zipfile.ZipFile(str(tmp), "w", compression=zipfile.ZIP_DEFLATED) as dst_zf:
            for item in src_zf.infolist():
                if item.filename in (_MANIFEST_ENTRY, name):
                    continue
                dst_zf.writestr(item, src_zf.read(item.filename))
            resources = [r for r in resources if r.get("name") != name]
            manifest["resources"] = resources
            manifest["resource_count"] = len(resources)
            dst_zf.writestr(_MANIFEST_ENTRY, json.dumps(manifest, indent=2))
    tmp.replace(bundle)

    return {"status": "ok", "bundle": bundle, "removed": name}
