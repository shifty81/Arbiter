"""Doc module — documentation generation from Python source and docstrings."""
from __future__ import annotations
import ast
import http.server
import inspect
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


def _extract_docs(src_path: Path) -> list[dict]:
    """Extract module/class/function docstrings from a Python file using AST."""
    docs: list[dict] = []
    try:
        tree = ast.parse(src_path.read_text(encoding="utf-8", errors="replace"), filename=str(src_path))
    except SyntaxError:
        return docs

    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            name = getattr(node, "name", "<module>")
            kind = type(node).__name__.replace("Def", "").replace("Async", "async ").lower()
            docs.append({"kind": kind, "name": name, "doc": doc or ""})
    return docs


def doc_generate(src: str, output: str, format: str = "markdown", title: str | None = None, **kwargs) -> dict:
    """Generate documentation for Python source files in *src* and write to *output*.

    *format*:
    - ``"markdown"`` (default) — produces a ``README.md``-style document
    - ``"json"``               — produces a structured JSON file
    - ``"html"``               — produces a simple HTML page

    Scans ``*.py`` files recursively under *src*.
    """
    root = Path(src)
    if not root.exists():
        return {"status": "error", "error": f"Source path not found: {src}"}

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    project_title = title or root.name
    files = sorted(root.rglob("*.py")) if root.is_dir() else [root]

    all_docs: list[dict] = []
    for f in files:
        entries = _extract_docs(f)
        if entries:
            all_docs.append({"file": str(f.relative_to(root) if root.is_dir() else f), "entries": entries})

    fmt = format.lower()

    if fmt == "json":
        out_path.write_text(json.dumps({"title": project_title, "modules": all_docs}, indent=2))

    elif fmt == "html":
        parts = [f"<html><head><title>{project_title}</title></head><body>"]
        parts.append(f"<h1>{project_title}</h1>")
        for module in all_docs:
            parts.append(f"<h2>{module['file']}</h2>")
            for e in module["entries"]:
                if e["doc"]:
                    parts.append(f"<h3>{e['kind']}: {e['name']}</h3><p>{e['doc']}</p>")
        parts.append("</body></html>")
        out_path.write_text("\n".join(parts))

    else:  # markdown
        lines = [f"# {project_title}\n"]
        for module in all_docs:
            lines.append(f"## `{module['file']}`\n")
            for e in module["entries"]:
                if e["doc"]:
                    lines.append(f"### {e['kind']}: `{e['name']}`\n\n{e['doc']}\n")
        out_path.write_text("\n".join(lines))

    total_entries = sum(len(m["entries"]) for m in all_docs)
    return {
        "status": "ok",
        "output": str(out_path),
        "format": fmt,
        "files_scanned": len(files),
        "entries_documented": total_entries,
    }


def doc_serve(docs_dir: str, port: int = 8000, **kwargs) -> dict:
    """Serve *docs_dir* as a static website on localhost:*port* using Python's built-in HTTP server.

    The server runs in a daemon thread so it will stop when the Python process ends.
    Returns immediately with the server URL.
    """
    root = Path(docs_dir)
    if not root.is_dir():
        return {"status": "error", "error": f"Directory not found: {docs_dir}"}

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *args):  # silence default output
            pass

    try:
        httpd = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        return {"status": "error", "error": str(exc)}

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"
    logger.info("Doc server started at %s serving %s", url, docs_dir)
    return {"status": "ok", "url": url, "docs_dir": str(root)}


def doc_lint(docs_dir: str, **kwargs) -> dict:
    """Check Markdown documentation files in *docs_dir* for common issues.

    Checks performed (no external tools required):
    - Broken internal links (``[text](./path)`` pointing to non-existent files)
    - Empty headings
    - Files with no content

    Returns a list of warnings per file.
    """
    root = Path(docs_dir)
    if not root.is_dir():
        return {"status": "error", "error": f"Directory not found: {docs_dir}"}

    import re

    warnings: list[dict] = []
    md_files = sorted(root.rglob("*.md"))

    for f in md_files:
        content = f.read_text(encoding="utf-8", errors="replace")
        file_warnings: list[str] = []

        # Empty file
        if not content.strip():
            file_warnings.append("File is empty")

        # Empty headings
        for m in re.finditer(r"^#+\s*$", content, re.MULTILINE):
            file_warnings.append(f"Empty heading at line {content[:m.start()].count(chr(10)) + 1}")

        # Broken relative links
        for m in re.finditer(r"\[([^\]]+)\]\((\./[^)]+)\)", content):
            link_path = root / m.group(2).lstrip("./")
            if not link_path.exists():
                file_warnings.append(f"Broken link: {m.group(2)}")

        if file_warnings:
            warnings.append({"file": str(f.relative_to(root)), "warnings": file_warnings})

    return {
        "status": "ok",
        "docs_dir": str(root),
        "files_checked": len(md_files),
        "warnings": warnings,
        "warning_count": sum(len(w["warnings"]) for w in warnings),
    }
