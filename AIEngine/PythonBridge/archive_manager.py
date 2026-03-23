"""
archive_manager.py — Arbiter Archive (Living Knowledge Codex).

The Archive is a collection of *ArchiveEntry* objects extracted from files in
the Library.  Each entry captures a logical chunk of knowledge (a function,
class, markdown section, or plain-text paragraph) together with an
AI-generated one-line summary, language tag, file origin, and keyword tags.

The archive is persisted as JSON in ``Memory/archive.json`` and rebuilt
incrementally as files change.

Typical flow
------------
1.  ``ArchiveManager`` loads the JSON on startup.
2.  ``ArchiveManager.rebuild(library_manager)`` crawls every library path,
    extracts entries, generates LLM summaries, and saves.
3.  The background watcher (``start_watcher``) repeats step 2 every 30 s for
    any file whose mtime has changed since the last scan.
4.  ``ArchiveManager.search(query)`` scores entries by term frequency and
    returns the top-k most relevant.
5.  ``ArchiveManager.get_context(query, k)`` returns a formatted string
    suitable for injection into an LLM system prompt.
6.  ``ArchiveManager.export_markdown()`` renders the full archive as a single
    Markdown codex document.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

# ── Default storage location ───────────────────────────────────────────────────
_DEFAULT_ARCHIVE = (
    Path(__file__).resolve().parent.parent.parent / "Memory" / "archive.json"
)

# ── Maximum chars extracted per entry ─────────────────────────────────────────
MAX_CONTENT_CHARS = 3000
# ── Background watcher interval (seconds) ─────────────────────────────────────
WATCHER_INTERVAL = 30


@dataclass
class ArchiveEntry:
    """One logical knowledge chunk extracted from a library file."""
    id: str
    title: str
    summary: str
    content: str
    language: str          # "python" | "javascript" | "markdown" | "text" | …
    source_file: str       # relative path inside the library
    library_id: str        # which LibraryManager entry this came from
    entry_type: str        # "function" | "class" | "section" | "snippet" | "paragraph"
    tags: list[str] = field(default_factory=list)
    indexed_at: int = field(default_factory=lambda: int(time.time()))
    file_mtime: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ArchiveEntry":
        d.setdefault("tags", [])
        d.setdefault("indexed_at", 0)
        d.setdefault("file_mtime", 0.0)
        return ArchiveEntry(**{k: v for k, v in d.items() if k in ArchiveEntry.__dataclass_fields__})


class ArchiveManager:
    """Build and query the living knowledge archive."""

    def __init__(
        self,
        archive_path: str | Path = _DEFAULT_ARCHIVE,
        llm_summariser: Callable[[str], str] | None = None,
    ) -> None:
        self._archive_path = Path(archive_path)
        self._archive_path.parent.mkdir(parents=True, exist_ok=True)
        self._llm = llm_summariser  # optional: fn(content) → one-line summary
        self._entries: list[ArchiveEntry] = []
        self._lock = threading.Lock()
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._archive_path.is_file():
            try:
                data = json.loads(self._archive_path.read_text(encoding="utf-8"))
                with self._lock:
                    self._entries = [ArchiveEntry.from_dict(e) for e in data.get("entries", [])]
                return
            except Exception:
                pass
        self._entries = []

    def _save(self) -> None:
        with self._lock:
            snapshot = [e.to_dict() for e in self._entries]
        self._archive_path.write_text(
            json.dumps({"entries": snapshot}, indent=2), encoding="utf-8"
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def entries(self) -> list[ArchiveEntry]:
        with self._lock:
            return list(self._entries)

    def rebuild(self, library_manager: Any) -> int:
        """Re-index all files in all library paths.  Returns count of new entries."""
        new_entries: list[ArchiveEntry] = []
        for lib_entry in library_manager.list_paths():
            lib_id = lib_entry["id"]
            lib_root = Path(lib_entry["path"])
            exts: set[str] = set(lib_entry.get("extensions", []))
            if not lib_root.exists():
                continue
            for f in lib_root.rglob("*"):
                if not f.is_file() or f.suffix.lower() not in exts or _is_hidden(f):
                    continue
                rel_path = str(f.relative_to(lib_root))
                mtime = f.stat().st_mtime
                new_entries.extend(
                    self._extract_file(f, rel_path, lib_id, mtime)
                )
        with self._lock:
            self._entries = new_entries
        self._save()
        return len(new_entries)

    def rebuild_incremental(self, library_manager: Any) -> int:
        """Re-index only files whose mtime has changed.  Returns count of updated entries."""
        # Build mtime lookup from current archive
        known: dict[str, float] = {
            e.source_file: e.file_mtime
            for e in self._entries
        }
        updated_count = 0
        for lib_entry in library_manager.list_paths():
            lib_id = lib_entry["id"]
            lib_root = Path(lib_entry["path"])
            exts: set[str] = set(lib_entry.get("extensions", []))
            if not lib_root.exists():
                continue
            for f in lib_root.rglob("*"):
                if not f.is_file() or f.suffix.lower() not in exts or _is_hidden(f):
                    continue
                rel_path = str(f.relative_to(lib_root))
                mtime = f.stat().st_mtime
                if known.get(rel_path, 0) == mtime:
                    continue  # unchanged
                # Remove old entries for this file
                with self._lock:
                    self._entries = [
                        e for e in self._entries
                        if not (e.source_file == rel_path and e.library_id == lib_id)
                    ]
                new = self._extract_file(f, rel_path, lib_id, mtime)
                with self._lock:
                    self._entries.extend(new)
                updated_count += len(new)
        if updated_count:
            self._save()
        return updated_count

    def delete_entry(self, entry_id: str) -> bool:
        """Remove an entry by ID.  Returns True if removed."""
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if e.id != entry_id]
            removed = len(self._entries) < before
        if removed:
            self._save()
        return removed

    def search(self, query: str, top_k: int = 10) -> list[ArchiveEntry]:
        """Score entries by query term frequency and return the top-k results."""
        terms = re.findall(r"\w+", query.lower())
        if not terms:
            return []
        scored: list[tuple[float, ArchiveEntry]] = []
        with self._lock:
            snapshot = list(self._entries)
        for entry in snapshot:
            score = _score_entry(entry, terms)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def get_context(self, query: str, top_k: int = 5) -> str:
        """Return top-k relevant archive entries formatted for LLM context injection."""
        results = self.search(query, top_k=top_k)
        if not results:
            return ""
        parts = ["--- Archive Context ---"]
        for e in results:
            parts.append(f"[{e.entry_type}] {e.title} ({e.source_file})")
            if e.summary:
                parts.append(f"Summary: {e.summary}")
            snippet = e.content[:500].strip()
            if snippet:
                parts.append(f"```{e.language}\n{snippet}\n```")
            parts.append("")
        parts.append("--- End Archive Context ---")
        return "\n".join(parts)

    def export_markdown(self) -> str:
        """Render the full archive as a Markdown codex document."""
        with self._lock:
            snapshot = list(self._entries)
        if not snapshot:
            return "# Arbiter Archive\n\n*No entries yet. Run a rebuild to index your library.*\n"
        lines = ["# Arbiter Archive — Knowledge Codex\n"]
        # Group by source file
        by_file: dict[str, list[ArchiveEntry]] = {}
        for e in snapshot:
            by_file.setdefault(e.source_file, []).append(e)
        for src_file, entries in sorted(by_file.items()):
            lines.append(f"\n## `{src_file}`\n")
            for e in entries:
                lines.append(f"### {e.title} `[{e.entry_type}]`\n")
                if e.summary:
                    lines.append(f"> {e.summary}\n")
                if e.tags:
                    lines.append(f"**Tags:** {', '.join(e.tags)}\n")
                lines.append(f"```{e.language}\n{e.content[:MAX_CONTENT_CHARS]}\n```\n")
        return "\n".join(lines)

    # ── Background watcher ──────────────────────────────────────────────────────

    def start_watcher(self, library_manager: Any) -> threading.Thread:
        """Start a background thread that re-indexes changed files every 30 s."""
        def _watch() -> None:
            while True:
                time.sleep(WATCHER_INTERVAL)
                try:
                    self.rebuild_incremental(library_manager)
                except Exception:
                    pass
        t = threading.Thread(target=_watch, daemon=True, name="arbiter-archive-watcher")
        t.start()
        return t

    # ── Internal extraction ────────────────────────────────────────────────────

    def _extract_file(
        self, path: Path, rel_path: str, lib_id: str, mtime: float
    ) -> list[ArchiveEntry]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []
        lang = _detect_language(path)
        if lang == "python":
            return self._extract_python(text, rel_path, lib_id, mtime)
        if lang in ("markdown", "rst"):
            return self._extract_markdown(text, rel_path, lib_id, mtime, lang)
        if lang in ("javascript", "typescript", "csharp", "go", "rust", "java"):
            return self._extract_generic(text, rel_path, lib_id, mtime, lang)
        # Fallback: chunk plain text into paragraphs
        return self._extract_text_chunks(text, rel_path, lib_id, mtime)

    def _make_entry(
        self,
        title: str,
        content: str,
        language: str,
        source_file: str,
        lib_id: str,
        entry_type: str,
        mtime: float,
        tags: list[str] | None = None,
    ) -> ArchiveEntry:
        content = content[:MAX_CONTENT_CHARS]
        summary = self._summarise(content) if self._llm else ""
        entry_id = hashlib.md5(f"{lib_id}:{source_file}:{title}".encode()).hexdigest()[:12]
        return ArchiveEntry(
            id=entry_id,
            title=title,
            summary=summary,
            content=content,
            language=language,
            source_file=source_file,
            library_id=lib_id,
            entry_type=entry_type,
            tags=tags or _extract_tags(title + " " + content),
            indexed_at=int(time.time()),
            file_mtime=mtime,
        )

    def _summarise(self, content: str) -> str:
        if self._llm is None:
            return ""
        try:
            return self._llm(f"Summarise this code/text in one sentence:\n\n{content[:1000]}")
        except Exception:
            return ""

    # ── Language-specific extractors ──────────────────────────────────────────

    def _extract_python(
        self, source: str, rel_path: str, lib_id: str, mtime: float
    ) -> list[ArchiveEntry]:
        entries: list[ArchiveEntry] = []
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError:
            return self._extract_text_chunks(source, rel_path, lib_id, mtime)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node) or ""
                body_src = _ast_node_source(source, node)
                entry = self._make_entry(
                    title=f"{rel_path}::{node.name}",
                    content=body_src,
                    language="python",
                    source_file=rel_path,
                    lib_id=lib_id,
                    entry_type="function",
                    mtime=mtime,
                    tags=[node.name],
                )
                if docstring and not entry.summary:
                    entry.summary = docstring.splitlines()[0][:200]
                entries.append(entry)
            elif isinstance(node, ast.ClassDef):
                body_src = _ast_node_source(source, node)
                docstring = ast.get_docstring(node) or ""
                entry = self._make_entry(
                    title=f"{rel_path}::{node.name}",
                    content=body_src,
                    language="python",
                    source_file=rel_path,
                    lib_id=lib_id,
                    entry_type="class",
                    mtime=mtime,
                    tags=[node.name],
                )
                if docstring and not entry.summary:
                    entry.summary = docstring.splitlines()[0][:200]
                entries.append(entry)

        # If no top-level functions/classes were found, fall back to chunking
        if not entries:
            return self._extract_text_chunks(source, rel_path, lib_id, mtime)
        return entries

    def _extract_markdown(
        self, text: str, rel_path: str, lib_id: str, mtime: float, lang: str
    ) -> list[ArchiveEntry]:
        entries: list[ArchiveEntry] = []
        sections = re.split(r"(?m)^#{1,3}\s+", text)
        headings = re.findall(r"(?m)^#{1,3}\s+(.+)", text)
        for i, body in enumerate(sections[1:], 0):
            title_text = headings[i] if i < len(headings) else f"Section {i + 1}"
            entries.append(self._make_entry(
                title=f"{rel_path} § {title_text}",
                content=body.strip(),
                language=lang,
                source_file=rel_path,
                lib_id=lib_id,
                entry_type="section",
                mtime=mtime,
            ))
        if not entries:
            return self._extract_text_chunks(text, rel_path, lib_id, mtime)
        return entries

    def _extract_generic(
        self, text: str, rel_path: str, lib_id: str, mtime: float, lang: str
    ) -> list[ArchiveEntry]:
        """Extract top-level function / class definitions via regex."""
        entries: list[ArchiveEntry] = []
        # Match function / method / class definitions for JS/TS/C#/Go/Rust/Java
        patterns = [
            # JS/TS: function foo(…) { or const foo = (…) =>
            (r"(?:^|\n)(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", "function"),
            (r"(?:^|\n)(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", "function"),
            # class Foo {
            (r"(?:^|\n)(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", "class"),
            # C# / Java / Go: type Foo struct / interface Foo
            (r"(?:^|\n)\s*(?:public|private|internal|protected)?\s*(?:static\s+)?(?:class|interface|struct|enum)\s+(\w+)", "class"),
            # Go func / Rust fn
            (r"(?:^|\n)(?:pub\s+)?fn\s+(\w+)\s*\(", "function"),
            (r"(?:^|\n)func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", "function"),
        ]
        matched_names: set[str] = set()
        lines = text.splitlines()
        for pattern, etype in patterns:
            for m in re.finditer(pattern, text, re.MULTILINE):
                name = m.group(1)
                if name in matched_names:
                    continue
                matched_names.add(name)
                start_line = text.count("\n", 0, m.start())
                snippet_lines = lines[start_line: start_line + 40]
                snippet = "\n".join(snippet_lines)
                entries.append(self._make_entry(
                    title=f"{rel_path}::{name}",
                    content=snippet,
                    language=lang,
                    source_file=rel_path,
                    lib_id=lib_id,
                    entry_type=etype,
                    mtime=mtime,
                    tags=[name],
                ))
        if not entries:
            return self._extract_text_chunks(text, rel_path, lib_id, mtime)
        return entries

    def _extract_text_chunks(
        self, text: str, rel_path: str, lib_id: str, mtime: float
    ) -> list[ArchiveEntry]:
        """Split plain text into paragraph-sized chunks."""
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        entries: list[ArchiveEntry] = []
        for i, para in enumerate(paragraphs[:50]):  # cap at 50 chunks per file
            entries.append(self._make_entry(
                title=f"{rel_path} — chunk {i + 1}",
                content=para,
                language=_detect_language(Path(rel_path)),
                source_file=rel_path,
                lib_id=lib_id,
                entry_type="paragraph",
                mtime=mtime,
            ))
        return entries


# ── Module-level helpers ───────────────────────────────────────────────────────

def _detect_language(path: Path) -> str:
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".cs": "csharp",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".r": "r",
        ".sh": "bash",
        ".bash": "bash",
        ".ps1": "powershell",
        ".md": "markdown",
        ".rst": "rst",
        ".html": "html",
        ".css": "css",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
    }.get(path.suffix.lower(), "text")


def _ast_node_source(source: str, node: ast.AST) -> str:
    lines = source.splitlines()
    start = node.lineno - 1  # type: ignore[attr-defined]
    end = getattr(node, "end_lineno", start + 40)
    return "\n".join(lines[start:end])


def _extract_tags(text: str, max_tags: int = 8) -> list[str]:
    """Extract top frequent identifiers as tags."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text)
    freq: dict[str, int] = {}
    stop = {
        "def", "class", "return", "import", "from", "self", "true", "false",
        "None", "null", "int", "str", "bool", "list", "dict", "var", "let",
        "const", "function", "public", "private", "void",
    }
    for t in tokens:
        if t not in stop:
            freq[t] = freq.get(t, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:max_tags]]


def _score_entry(entry: ArchiveEntry, terms: list[str]) -> float:
    """Simple TF-based relevance score."""
    haystack = " ".join([
        entry.title,
        entry.summary,
        entry.content[:500],
        " ".join(entry.tags),
    ]).lower()
    return sum(haystack.count(t) for t in terms)


def _is_hidden(path: Path) -> bool:
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}
    return any(part.startswith(".") or part in skip for part in path.parts)
