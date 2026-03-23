"""Editor module — code formatting, linting, and text search/replace."""
from __future__ import annotations
import re
import shutil
import subprocess
import sys
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


def _run(cmd: list[str], cwd: str | None = None) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=60)
        return {"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Executable not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "Command timed out"}
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}


def _detect_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".go": "go",
        ".rs": "rust",
        ".lua": "lua",
        ".json": "json",
    }.get(ext, "unknown")


def editor_format(path: str, language: str | None = None, **kwargs) -> dict:
    """Format source code at *path* using the appropriate formatter.

    Language is auto-detected from the file extension when not provided.

    Formatters used (when available in PATH):
    - Python → ``black``
    - JavaScript/TypeScript → ``prettier``
    - C/C++ → ``clang-format``
    - Go → ``gofmt``
    - Rust → ``rustfmt``
    - JSON → Python's ``json`` module (always available)
    """
    p = Path(path)
    if not p.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    lang = (language or _detect_language(path)).lower()

    if lang == "python":
        if shutil.which("black"):
            r = _run(["black", str(p)])
        else:
            # Fallback: use autopep8 if available, otherwise report
            r = _run([sys.executable, "-m", "autopep8", "--in-place", str(p)])
        if r["returncode"] not in (0, -1):
            return {"status": "error", "error": r["stderr"], "language": lang}
        if r["returncode"] == -1:
            return {"status": "skipped", "reason": "No Python formatter (black/autopep8) found in PATH", "language": lang}

    elif lang in ("javascript", "typescript"):
        if shutil.which("prettier"):
            r = _run(["prettier", "--write", str(p)])
            if r["returncode"] != 0:
                return {"status": "error", "error": r["stderr"], "language": lang}
        else:
            return {"status": "skipped", "reason": "prettier not found in PATH", "language": lang}

    elif lang in ("c", "cpp", "csharp"):
        if shutil.which("clang-format"):
            r = _run(["clang-format", "-i", str(p)])
            if r["returncode"] != 0:
                return {"status": "error", "error": r["stderr"], "language": lang}
        else:
            return {"status": "skipped", "reason": "clang-format not found in PATH", "language": lang}

    elif lang == "go":
        if shutil.which("gofmt"):
            r = _run(["gofmt", "-w", str(p)])
            if r["returncode"] != 0:
                return {"status": "error", "error": r["stderr"], "language": lang}
        else:
            return {"status": "skipped", "reason": "gofmt not found in PATH", "language": lang}

    elif lang == "rust":
        if shutil.which("rustfmt"):
            r = _run(["rustfmt", str(p)])
            if r["returncode"] != 0:
                return {"status": "error", "error": r["stderr"], "language": lang}
        else:
            return {"status": "skipped", "reason": "rustfmt not found in PATH", "language": lang}

    elif lang == "json":
        import json as _json
        try:
            obj = _json.loads(p.read_text())
            p.write_text(_json.dumps(obj, indent=2))
        except _json.JSONDecodeError as exc:
            return {"status": "error", "error": f"JSON parse error: {exc}", "language": lang}

    else:
        return {"status": "skipped", "reason": f"No formatter configured for language: {lang}", "language": lang}

    return {"status": "ok", "path": str(p), "language": lang}


def editor_lint(path: str, language: str | None = None, **kwargs) -> dict:
    """Lint source code at *path* and return a list of issues.

    Linters used (when available in PATH):
    - Python → ``flake8``
    - JavaScript/TypeScript → ``eslint``
    - C/C++ → ``cppcheck``
    - Go → ``go vet``
    - Rust → ``cargo clippy``
    """
    p = Path(path)
    if not p.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    lang = (language or _detect_language(path)).lower()
    issues: list[dict] = []

    if lang == "python":
        if shutil.which("flake8"):
            r = _run(["flake8", "--format=%(path)s:%(row)d:%(col)d: %(code)s %(text)s", str(p)])
            for line in r["stdout"].splitlines():
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    issues.append({"file": parts[0], "line": parts[1], "col": parts[2], "message": parts[3].strip()})
        else:
            return {"status": "skipped", "reason": "flake8 not found in PATH", "language": lang}

    elif lang in ("javascript", "typescript"):
        if shutil.which("eslint"):
            r = _run(["eslint", "--format=compact", str(p)])
            for line in r["stdout"].splitlines():
                if "Error -" in line or "Warning -" in line:
                    issues.append({"message": line.strip()})
        else:
            return {"status": "skipped", "reason": "eslint not found in PATH", "language": lang}

    elif lang in ("c", "cpp"):
        if shutil.which("cppcheck"):
            r = _run(["cppcheck", "--enable=all", "--quiet", str(p)])
            for line in r["stderr"].splitlines():
                issues.append({"message": line.strip()})
        else:
            return {"status": "skipped", "reason": "cppcheck not found in PATH", "language": lang}

    elif lang == "go":
        if shutil.which("go"):
            r = _run(["go", "vet", str(p)])
            for line in r["stderr"].splitlines():
                issues.append({"message": line.strip()})
        else:
            return {"status": "skipped", "reason": "go not found in PATH", "language": lang}

    else:
        return {"status": "skipped", "reason": f"No linter configured for language: {lang}", "language": lang}

    return {"status": "ok", "path": str(p), "language": lang, "issues": issues, "issue_count": len(issues)}


def editor_search(pattern: str, directory: str, file_type: str | None = None, **kwargs) -> dict:
    """Search for *pattern* (regex) across files in *directory*.

    *file_type* can be a file extension like ``".py"`` to restrict results.
    Returns a list of matches with file path, line number, and matched text.
    """
    root = Path(directory)
    if not root.is_dir():
        return {"status": "error", "error": f"Directory not found: {directory}"}

    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return {"status": "error", "error": f"Invalid regex: {exc}"}

    matches: list[dict] = []
    glob = f"*{file_type}" if file_type else "*"
    for f in sorted(root.rglob(glob)):
        if not f.is_file():
            continue
        try:
            for lineno, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    matches.append({"file": str(f), "line": lineno, "text": line.rstrip()})
        except Exception:
            pass

    return {"status": "ok", "pattern": pattern, "directory": directory, "matches": matches, "count": len(matches)}


def editor_replace(pattern: str, replacement: str, directory: str, file_type: str | None = None, **kwargs) -> dict:
    """Search-and-replace *pattern* with *replacement* across files in *directory*.

    *pattern* is treated as a regex.  Files are edited in-place.
    Returns a summary of how many replacements were made per file.
    """
    root = Path(directory)
    if not root.is_dir():
        return {"status": "error", "error": f"Directory not found: {directory}"}

    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return {"status": "error", "error": f"Invalid regex: {exc}"}

    summary: list[dict] = []
    glob = f"*{file_type}" if file_type else "*"
    for f in sorted(root.rglob(glob)):
        if not f.is_file():
            continue
        try:
            original = f.read_text(encoding="utf-8", errors="replace")
            new_text, count = rx.subn(replacement, original)
            if count:
                f.write_text(new_text, encoding="utf-8")
                summary.append({"file": str(f), "replacements": count})
        except Exception:
            pass

    total = sum(s["replacements"] for s in summary)
    return {
        "status": "ok",
        "pattern": pattern,
        "replacement": replacement,
        "directory": directory,
        "files_changed": len(summary),
        "total_replacements": total,
        "details": summary,
    }
