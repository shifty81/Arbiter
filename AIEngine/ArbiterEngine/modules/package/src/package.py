"""Package module — pip / npm / gem / cargo package management."""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_MANAGERS = {"pip", "npm", "gem", "cargo", "go"}


def _detect_manager(cwd: str | None) -> str:
    """Auto-detect a suitable package manager based on project files."""
    if cwd:
        root = Path(cwd)
        if (root / "package.json").exists() and shutil.which("npm"):
            return "npm"
        if (root / "Cargo.toml").exists() and shutil.which("cargo"):
            return "cargo"
        if (root / "Gemfile").exists() and shutil.which("gem"):
            return "gem"
        if (root / "go.mod").exists() and shutil.which("go"):
            return "go"
    return "pip"


def _run(cmd: list[str], cwd: str | None = None) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=180)
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Executable not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "Command timed out"}
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}


def pkg_install(name: str, version: str | None = None, manager: str | None = None, cwd: str | None = None, **kwargs) -> dict:
    """Install package *name*, optionally pinned to *version*.

    *manager* can be ``"pip"``, ``"npm"``, ``"gem"``, ``"cargo"``, or ``"go"``.
    Auto-detected from project files when omitted.
    """
    mgr = (manager or _detect_manager(cwd)).lower()
    pkg = f"{name}=={version}" if version and mgr == "pip" else (f"{name}@{version}" if version else name)

    if mgr == "pip":
        r = _run([sys.executable, "-m", "pip", "install", pkg], cwd=cwd)
    elif mgr == "npm":
        r = _run(["npm", "install", pkg], cwd=cwd)
    elif mgr == "gem":
        cmd = ["gem", "install", name]
        if version:
            cmd += ["-v", version]
        r = _run(cmd, cwd=cwd)
    elif mgr == "cargo":
        cmd = ["cargo", "add", name]
        if version:
            cmd += ["--vers", version]
        r = _run(cmd, cwd=cwd)
    elif mgr == "go":
        module = f"{name}@{version}" if version else f"{name}@latest"
        r = _run(["go", "get", module], cwd=cwd)
    else:
        return {"status": "error", "error": f"Unsupported manager: {manager}"}

    ok = r["returncode"] == 0
    return {"status": "ok" if ok else "error", "manager": mgr, "package": name, **r}


def pkg_uninstall(name: str, manager: str | None = None, **kwargs) -> dict:
    """Uninstall package *name*."""
    mgr = (manager or "pip").lower()

    if mgr == "pip":
        r = _run([sys.executable, "-m", "pip", "uninstall", "-y", name])
    elif mgr == "npm":
        r = _run(["npm", "uninstall", name])
    elif mgr == "gem":
        r = _run(["gem", "uninstall", "-x", name])
    elif mgr == "cargo":
        r = _run(["cargo", "remove", name])
    else:
        return {"status": "error", "error": f"Unsupported manager: {manager}"}

    ok = r["returncode"] == 0
    return {"status": "ok" if ok else "error", "manager": mgr, "package": name, **r}


def pkg_list(manager: str | None = None, **kwargs) -> dict:
    """List installed packages for the given *manager*."""
    mgr = (manager or "pip").lower()

    if mgr == "pip":
        r = _run([sys.executable, "-m", "pip", "list", "--format=json"])
        if r["returncode"] == 0:
            try:
                packages = json.loads(r["stdout"])
                return {"status": "ok", "manager": mgr, "packages": packages, "count": len(packages)}
            except json.JSONDecodeError:
                pass
    elif mgr == "npm":
        r = _run(["npm", "ls", "--json", "--depth=0"])
        if r["returncode"] == 0:
            try:
                data = json.loads(r["stdout"])
                deps = list((data.get("dependencies") or {}).keys())
                return {"status": "ok", "manager": mgr, "packages": deps, "count": len(deps)}
            except json.JSONDecodeError:
                pass
    elif mgr == "gem":
        r = _run(["gem", "list"])
    elif mgr == "cargo":
        r = _run(["cargo", "metadata", "--no-deps", "--format-version=1"])
        if r["returncode"] == 0:
            try:
                data = json.loads(r["stdout"])
                packages = [{"name": p["name"], "version": p["version"]} for p in data.get("packages", [])]
                return {"status": "ok", "manager": mgr, "packages": packages, "count": len(packages)}
            except json.JSONDecodeError:
                pass
    else:
        return {"status": "error", "error": f"Unsupported manager: {manager}"}

    ok = r["returncode"] == 0
    return {"status": "ok" if ok else "error", "manager": mgr, "output": r["stdout"]}


def pkg_update(name: str, manager: str | None = None, **kwargs) -> dict:
    """Update package *name* to its latest version."""
    mgr = (manager or "pip").lower()

    if mgr == "pip":
        r = _run([sys.executable, "-m", "pip", "install", "--upgrade", name])
    elif mgr == "npm":
        r = _run(["npm", "update", name])
    elif mgr == "gem":
        r = _run(["gem", "update", name])
    elif mgr == "cargo":
        r = _run(["cargo", "update", "-p", name])
    elif mgr == "go":
        r = _run(["go", "get", f"{name}@latest"])
    else:
        return {"status": "error", "error": f"Unsupported manager: {manager}"}

    ok = r["returncode"] == 0
    return {"status": "ok" if ok else "error", "manager": mgr, "package": name, **r}


def pkg_search(query: str, manager: str | None = None, **kwargs) -> dict:
    """Search for packages matching *query*."""
    mgr = (manager or "pip").lower()

    if mgr == "pip":
        # pip removed its search command; fall back to pypi JSON API using urllib
        import urllib.request
        import urllib.error
        url = f"https://pypi.org/pypi/{query}/json"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            info = data.get("info", {})
            return {
                "status": "ok",
                "manager": mgr,
                "query": query,
                "results": [{"name": info.get("name"), "version": info.get("version"), "summary": info.get("summary")}],
            }
        except urllib.error.HTTPError:
            return {"status": "ok", "manager": mgr, "query": query, "results": [], "message": "Package not found on PyPI"}
        except Exception as exc:
            return {"status": "error", "manager": mgr, "error": str(exc)}
    elif mgr == "npm":
        r = _run(["npm", "search", "--json", query])
        if r["returncode"] == 0:
            try:
                results = json.loads(r["stdout"])
                simplified = [{"name": p.get("name"), "version": p.get("version"), "description": p.get("description")} for p in results[:10]]
                return {"status": "ok", "manager": mgr, "query": query, "results": simplified}
            except json.JSONDecodeError:
                pass
    elif mgr == "gem":
        r = _run(["gem", "search", query])
        return {"status": "ok" if r["returncode"] == 0 else "error", "manager": mgr, "query": query, "output": r["stdout"]}
    else:
        return {"status": "error", "error": f"Unsupported manager: {manager}"}

    return {"status": "ok", "manager": mgr, "query": query, "output": ""}
