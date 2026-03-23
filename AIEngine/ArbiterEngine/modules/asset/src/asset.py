"""Asset module — file-based asset registry with JSON manifest."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_ASSET_DIR = Path("cache") / "assets"
_MANIFEST_FILE = _ASSET_DIR / "manifest.json"


def _load_manifest() -> dict:
    _ASSET_DIR.mkdir(parents=True, exist_ok=True)
    if _MANIFEST_FILE.exists():
        try:
            return json.loads(_MANIFEST_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _save_manifest(manifest: dict) -> None:
    _ASSET_DIR.mkdir(parents=True, exist_ok=True)
    _MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_import(path: str, type: str, name: str | None = None, **kwargs) -> dict:
    """Import an asset file from *path* into the asset registry.

    The file is copied into the managed assets directory.  A unique *asset_id*
    is generated and returned, along with metadata stored in the manifest.

    *type* is a free-form category string (e.g. ``"texture"``, ``"model"``, ``"audio"``).
    *name* defaults to the original filename stem.
    """
    src = Path(path)
    if not src.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    manifest = _load_manifest()
    asset_id = uuid.uuid4().hex[:12]
    name = name or src.stem
    dest = _ASSET_DIR / asset_id / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)

    entry = {
        "id": asset_id,
        "name": name,
        "type": type,
        "original_path": str(src.resolve()),
        "stored_path": str(dest),
        "filename": src.name,
        "size_bytes": dest.stat().st_size,
        "sha256": _sha256(dest),
        "imported_at": time.time(),
    }
    manifest[asset_id] = entry
    _save_manifest(manifest)
    logger.info("Asset imported: %s → %s", path, asset_id)
    return {"status": "ok", "asset_id": asset_id, "name": name, "type": type}


def asset_export(asset_id: str, dst: str, **kwargs) -> dict:
    """Export a managed asset identified by *asset_id* to *dst*."""
    manifest = _load_manifest()
    entry = manifest.get(asset_id)
    if not entry:
        return {"status": "error", "error": f"Asset not found: {asset_id}"}

    src = Path(entry["stored_path"])
    if not src.exists():
        return {"status": "error", "error": f"Asset file missing from store: {src}"}

    out = Path(dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out)
    return {"status": "ok", "asset_id": asset_id, "dst": str(out)}


def asset_list(type: str | None = None, **kwargs) -> dict:
    """List all assets in the registry, optionally filtered by *type*."""
    manifest = _load_manifest()
    assets = [
        {"id": e["id"], "name": e["name"], "type": e["type"], "filename": e["filename"], "size_bytes": e["size_bytes"]}
        for e in manifest.values()
        if type is None or e["type"] == type
    ]
    return {"status": "ok", "assets": assets, "count": len(assets)}


def asset_delete(asset_id: str, **kwargs) -> dict:
    """Remove an asset from the registry and delete its stored file."""
    manifest = _load_manifest()
    entry = manifest.pop(asset_id, None)
    if not entry:
        return {"status": "error", "error": f"Asset not found: {asset_id}"}

    stored = Path(entry["stored_path"])
    if stored.exists():
        try:
            shutil.rmtree(stored.parent)
        except Exception:
            stored.unlink(missing_ok=True)

    _save_manifest(manifest)
    return {"status": "ok", "deleted": asset_id}


def asset_metadata(asset_id: str, **kwargs) -> dict:
    """Return the full metadata record for an asset."""
    manifest = _load_manifest()
    entry = manifest.get(asset_id)
    if not entry:
        return {"status": "error", "error": f"Asset not found: {asset_id}"}
    return {"status": "ok", "asset": entry}
