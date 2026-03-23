"""
library_manager.py — Arbiter Library path CRUD.

The Library is a list of filesystem paths that the user wants Arbiter to
monitor and index.  Paths and their metadata are persisted in
``Memory/library_config.json``.

Usage::

    from library_manager import LibraryManager
    lm = LibraryManager()
    lm.add_path("/home/user/my-project")
    for p in lm.list_paths():
        print(p["path"])
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


# ── Default storage location ───────────────────────────────────────────────────
_DEFAULT_CONFIG = (
    Path(__file__).resolve().parent.parent.parent / "Memory" / "library_config.json"
)

# ── File extensions indexed by default ────────────────────────────────────────
DEFAULT_EXTENSIONS: set[str] = {
    # Code
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cs", ".go",
    ".rs", ".cpp", ".c", ".h", ".hpp", ".rb", ".php", ".swift",
    ".kt", ".scala", ".r", ".m", ".sh", ".bash", ".ps1",
    # Docs / config
    ".md", ".rst", ".txt", ".toml", ".yaml", ".yml", ".json",
    ".html", ".css",
}


class LibraryManager:
    """Manage a list of library paths that Arbiter monitors and indexes."""

    def __init__(self, config_path: str | Path = _DEFAULT_CONFIG) -> None:
        self._config_path = Path(config_path)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        if self._config_path.is_file():
            try:
                return json.loads(self._config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"paths": []}

    def _save(self) -> None:
        self._config_path.write_text(
            json.dumps(self._data, indent=2), encoding="utf-8"
        )

    # ── Path CRUD ──────────────────────────────────────────────────────────────

    def add_path(
        self,
        path: str,
        label: str = "",
        extensions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a path to the library.  Returns the entry dict."""
        resolved = str(Path(path).resolve())
        # Avoid duplicates
        for entry in self._data["paths"]:
            if entry["path"] == resolved:
                return entry
        entry: dict[str, Any] = {
            "id": _make_id(resolved),
            "path": resolved,
            "label": label or Path(resolved).name,
            "extensions": extensions or list(DEFAULT_EXTENSIONS),
            "added_at": int(time.time()),
        }
        self._data["paths"].append(entry)
        self._save()
        return entry

    def remove_path(self, path_or_id: str) -> bool:
        """Remove an entry by path or ID.  Returns True if removed."""
        original = self._data["paths"]
        kept = [
            e for e in original
            if e["path"] != path_or_id and e["id"] != path_or_id
        ]
        if len(kept) == len(original):
            return False
        self._data["paths"] = kept
        self._save()
        return True

    def list_paths(self) -> list[dict[str, Any]]:
        """Return all registered library paths."""
        return list(self._data["paths"])

    def get_path(self, path_or_id: str) -> dict[str, Any] | None:
        """Return a single entry by path or ID."""
        for e in self._data["paths"]:
            if e["path"] == path_or_id or e["id"] == path_or_id:
                return e
        return None

    # ── File enumeration ───────────────────────────────────────────────────────

    def list_files(self, path_or_id: str, relative: bool = True) -> list[str]:
        """Return all indexable files under a library path."""
        entry = self.get_path(path_or_id)
        if entry is None:
            return []
        root = Path(entry["path"])
        if not root.exists():
            return []
        exts: set[str] = set(entry.get("extensions", list(DEFAULT_EXTENSIONS)))
        files: list[str] = []
        for f in root.rglob("*"):
            if f.is_file() and f.suffix.lower() in exts and not _is_hidden(f):
                files.append(str(f.relative_to(root)) if relative else str(f))
        return sorted(files)

    def read_file(self, path_or_id: str, relative_path: str) -> str | None:
        """Read a file inside a library path, returning its content or None."""
        entry = self.get_path(path_or_id)
        if entry is None:
            return None
        root = Path(entry["path"]).resolve()
        full = (root / relative_path).resolve()
        # Guard against path traversal: resolved path must stay inside the library root
        try:
            full.relative_to(root)
        except ValueError:
            return None
        if not full.is_file():
            return None
        try:
            return full.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_id(path: str) -> str:
    """Short deterministic ID for a path."""
    import hashlib
    return hashlib.md5(path.encode()).hexdigest()[:10]


def _is_hidden(path: Path) -> bool:
    """Return True if the path (or any parent) is hidden / in a vendor dir."""
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}
    return any(part.startswith(".") or part in skip for part in path.parts)
