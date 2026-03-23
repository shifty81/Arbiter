"""Index module — project code indexer for fast search."""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

_TEXT_EXTS = {".py", ".js", ".ts", ".cpp", ".c", ".h", ".hpp", ".go", ".rs",
              ".java", ".cs", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"}


def _index_path(path: str) -> Path:
    safe = Path(path).resolve().name
    p = Path("cache") / "indexes" / f"{safe}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def index_project(path: str, exclude: list[str] | None = None) -> dict:
    root = Path(path)
    exclude_set = set(exclude or ["__pycache__", ".git", "node_modules", "venv", ".venv", "build", "dist"])
    entries = []
    for f in root.rglob("*"):
        if f.is_file() and f.suffix in _TEXT_EXTS:
            if any(ex in f.parts for ex in exclude_set):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                entries.append({"path": str(f.relative_to(root)), "content": text, "size": len(text)})
            except Exception:
                pass
    index = {"root": str(root), "built_at": time.time(), "entries": entries}
    _index_path(path).write_text(json.dumps(index))
    return {"indexed": len(entries), "path": path}


def index_search(query: str, path: str = ".", limit: int = 20) -> dict:
    ip = _index_path(path)
    if not ip.exists():
        return {"error": "Index not found. Run index_project first.", "results": []}
    index = json.loads(ip.read_text())
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results = []
    for entry in index["entries"]:
        matches = [m.start() for m in pattern.finditer(entry["content"])]
        if matches:
            results.append({"path": entry["path"], "match_count": len(matches)})
    results.sort(key=lambda r: r["match_count"], reverse=True)
    return {"results": results[:limit], "total": len(results), "query": query}


def index_rebuild(path: str) -> dict:
    return index_project(path)


def index_stats(path: str) -> dict:
    ip = _index_path(path)
    if not ip.exists():
        return {"error": "Index not found."}
    index = json.loads(ip.read_text())
    return {
        "root": index["root"],
        "built_at": index["built_at"],
        "entries": len(index["entries"]),
        "total_bytes": sum(e["size"] for e in index["entries"]),
    }
