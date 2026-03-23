"""Knowledge module — fetch, index, and search documentation for RAG-enhanced agent responses.

Uses only Python stdlib + `requests` (already a project dependency) — no ML models needed.
Search uses TF-IDF-style keyword scoring for fully-offline operation.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


# ── Paths ──────────────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _kb_dir(project_path: str = "") -> Path:
    """Return the .swissagent/knowledge directory for a project."""
    root = _repo_root()
    if project_path:
        base = root / project_path
    else:
        base = root / "workspace"
    kb = base / ".swissagent" / "knowledge"
    kb.mkdir(parents=True, exist_ok=True)
    return kb


def _index_path(project_path: str = "") -> Path:
    return _kb_dir(project_path) / "index.json"


def _chunks_path(project_path: str = "", source_id: str = "") -> Path:
    return _kb_dir(project_path) / f"chunks_{source_id}.json"


# ── Index helpers ──────────────────────────────────────────────────────────────

def _load_index(project_path: str = "") -> dict[str, Any]:
    p = _index_path(project_path)
    if not p.exists():
        return {"sources": []}
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _save_index(data: dict[str, Any], project_path: str = "") -> None:
    with _index_path(project_path).open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ── HTML → plain text ──────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "nav", "footer", "header", "aside", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _html_to_text(html_content: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html_content)
    except Exception:
        pass
    text = parser.get_text()
    # Collapse excessive whitespace
    text = re.sub(r"\s{3,}", "\n\n", text)
    return html.unescape(text).strip()


# ── Chunking ───────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    """Split text into overlapping word-count chunks."""
    words = text.split()
    chunks: list[str] = []
    i = 0
    while i < len(words):
        chunk_words = words[i: i + chunk_size]
        chunks.append(" ".join(chunk_words))
        i += chunk_size - overlap
    return [c for c in chunks if len(c.strip()) > 20]


# ── TF-IDF search ──────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", text.lower())


def _score(query_tokens: list[str], chunk_text: str) -> float:
    """Simple TF-based relevance score."""
    chunk_tokens = _tokenize(chunk_text)
    if not chunk_tokens:
        return 0.0
    tf: dict[str, float] = {}
    for tok in chunk_tokens:
        tf[tok] = tf.get(tok, 0) + 1
    total = len(chunk_tokens)
    score = 0.0
    for qt in query_tokens:
        score += tf.get(qt, 0) / total
    # Boost for exact phrase matches
    query_str = " ".join(query_tokens)
    if query_str in chunk_text.lower():
        score += 2.0
    return score


# ── Public tool functions ──────────────────────────────────────────────────────

def knowledge_fetch(
    url: str,
    project_path: str = "",
    label: str = "",
) -> dict[str, Any]:
    """Fetch a URL and add it to the project knowledge base."""
    if not _HAS_REQUESTS:
        return {"error": "requests library not installed. Run: pip install requests"}

    # Normalise URL
    if not urlparse(url).scheme:
        url = "https://" + url

    source_id = hashlib.sha1(url.encode()).hexdigest()[:12]
    index = _load_index(project_path)

    # Check if already indexed
    existing = next((s for s in index["sources"] if s["id"] == source_id), None)
    if existing:
        return {
            "already_indexed": True,
            "source_id": source_id,
            "label": existing.get("label", url),
            "chunks": existing.get("chunk_count", 0),
            "message": f"Source already indexed as '{existing.get('label', url)}'. Use knowledge_search to query it.",
        }

    try:
        resp = _requests.get(url, timeout=15, headers={"User-Agent": "SwissAgent-KnowledgeBot/1.0"})
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
    except Exception as exc:
        return {"error": f"Failed to fetch {url}: {exc}"}

    # Extract text
    raw = resp.text
    if "html" in content_type:
        text = _html_to_text(raw)
    else:
        text = raw  # plain text / markdown

    if len(text) < 50:
        return {"error": f"Fetched content from {url} is too short to be useful ({len(text)} chars)."}

    chunks = _chunk_text(text)
    chunk_data = [{"id": f"{source_id}_{i}", "source_id": source_id, "text": c} for i, c in enumerate(chunks)]

    # Save chunks
    with _chunks_path(project_path, source_id).open("w", encoding="utf-8") as f:
        json.dump(chunk_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Update index
    entry = {
        "id": source_id,
        "url": url,
        "label": label or urlparse(url).netloc + urlparse(url).path,
        "chunk_count": len(chunks),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "char_count": len(text),
    }
    index["sources"].append(entry)
    _save_index(index, project_path)

    return {
        "success": True,
        "source_id": source_id,
        "url": url,
        "label": entry["label"],
        "chunks_indexed": len(chunks),
        "char_count": len(text),
        "message": f"Indexed {len(chunks)} chunks from {url}. Use knowledge_search to query.",
    }


def knowledge_search(
    query: str,
    project_path: str = "",
    top_k: int = 5,
) -> dict[str, Any]:
    """Search the knowledge base for chunks relevant to a query."""
    top_k = max(1, min(top_k, 20))
    kb = _kb_dir(project_path)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return {"error": "Query is too short or contains no searchable words."}

    scored: list[tuple[float, dict[str, Any]]] = []
    for chunks_file in kb.glob("chunks_*.json"):
        try:
            with chunks_file.open(encoding="utf-8") as f:
                chunks = json.load(f)
        except Exception:
            continue
        for chunk in chunks:
            s = _score(query_tokens, chunk.get("text", ""))
            if s > 0:
                scored.append((s, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    if not top:
        return {
            "results": [],
            "message": "No relevant chunks found. Try fetching more documentation with knowledge_fetch.",
        }

    # Load source labels for display
    index = _load_index(project_path)
    source_map = {s["id"]: s for s in index.get("sources", [])}

    results = []
    for score, chunk in top:
        src = source_map.get(chunk.get("source_id", ""), {})
        results.append({
            "score": round(score, 4),
            "source_label": src.get("label", chunk.get("source_id", "unknown")),
            "source_url": src.get("url", ""),
            "text": chunk["text"][:800] + ("…" if len(chunk["text"]) > 800 else ""),
        })

    return {
        "query": query,
        "results": results,
        "total_found": len(scored),
        "showing": len(results),
    }


def knowledge_list(project_path: str = "") -> dict[str, Any]:
    """List all indexed knowledge sources for a project."""
    index = _load_index(project_path)
    sources = index.get("sources", [])
    total_chunks = sum(s.get("chunk_count", 0) for s in sources)
    return {
        "project_path": project_path or "workspace (root)",
        "source_count": len(sources),
        "total_chunks": total_chunks,
        "sources": sources,
    }


def knowledge_remove(source_id: str, project_path: str = "") -> dict[str, Any]:
    """Remove a knowledge source and its chunks."""
    index = _load_index(project_path)
    before = len(index["sources"])
    index["sources"] = [s for s in index["sources"] if s["id"] != source_id]
    if len(index["sources"]) == before:
        return {"error": f"Source '{source_id}' not found."}

    chunks_file = _chunks_path(project_path, source_id)
    if chunks_file.exists():
        chunks_file.unlink()

    _save_index(index, project_path)
    return {"success": True, "removed_source_id": source_id}
