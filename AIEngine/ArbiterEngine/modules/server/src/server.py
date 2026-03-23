"""Server module — local dev-server lifecycle management."""
from __future__ import annotations
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

# In-process registry: server_id → metadata dict
_servers: dict[str, dict] = {}
_lock = threading.Lock()


def _server_type(path: str) -> str:
    """Guess the server type from the project layout."""
    root = Path(path)
    if (root / "package.json").exists():
        return "node"
    if list(root.glob("*.py")) or (root / "manage.py").exists():
        return "python"
    if (root / "index.html").exists():
        return "static"
    return "static"


def server_start(path: str, port: int = 8080, host: str = "127.0.0.1", **kwargs) -> dict:
    """Start a local development server for the project at *path*.

    Auto-detects the project type:
    - ``package.json`` present → ``npm start`` (or ``npx serve``)
    - Python project → ``python -m http.server`` or ``uvicorn`` for FastAPI/Django
    - Static HTML → ``python -m http.server``

    Returns a ``server_id`` used for subsequent stop/status/logs calls.
    """
    root = Path(path)
    if not root.is_dir():
        return {"status": "error", "error": f"Directory not found: {path}"}

    stype = _server_type(path)
    server_id = uuid.uuid4().hex[:8]
    log_lines: list[str] = []

    if stype == "node" and shutil.which("npm"):
        pkg = root / "package.json"
        import json as _json
        scripts = _json.loads(pkg.read_text()).get("scripts", {})
        cmd = ["npm", "start"] if "start" in scripts else ["npx", "serve", "-l", str(port)]
    elif stype == "python" and shutil.which("uvicorn"):
        # Look for a FastAPI/ASGI app
        cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", host, "--port", str(port), "--reload"]
    else:
        # Generic static file server
        cmd = [sys.executable, "-m", "http.server", str(port), "--bind", host, "--directory", str(root)]

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        return {"status": "error", "error": f"Command not found: {cmd[0]}"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    # Collect log lines in a background thread
    def _reader(p: subprocess.Popen, lines: list[str]) -> None:
        for line in p.stdout:  # type: ignore[union-attr]
            lines.append(line.rstrip())

    t = threading.Thread(target=_reader, args=(proc, log_lines), daemon=True)
    t.start()

    time.sleep(0.3)  # Brief pause to detect immediate startup failures
    if proc.poll() is not None:
        return {
            "status": "error",
            "error": "Server process exited immediately",
            "logs": log_lines,
        }

    with _lock:
        _servers[server_id] = {
            "id": server_id,
            "path": str(root),
            "host": host,
            "port": port,
            "type": stype,
            "command": cmd,
            "process": proc,
            "log_lines": log_lines,
            "started_at": time.time(),
        }

    logger.info("Server %s started (pid=%d) at %s:%d", server_id, proc.pid, host, port)
    return {
        "status": "ok",
        "server_id": server_id,
        "pid": proc.pid,
        "url": f"http://{host}:{port}",
        "type": stype,
    }


def server_stop(server_id: str, **kwargs) -> dict:
    """Terminate the server identified by *server_id*."""
    with _lock:
        entry = _servers.get(server_id)
    if entry is None:
        return {"status": "error", "error": f"Server not found: {server_id}"}

    proc: subprocess.Popen = entry["process"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    with _lock:
        _servers.pop(server_id, None)

    logger.info("Server %s stopped", server_id)
    return {"status": "stopped", "server_id": server_id}


def server_status(server_id: str, **kwargs) -> dict:
    """Return the current status of the server identified by *server_id*."""
    with _lock:
        entry = _servers.get(server_id)
    if entry is None:
        return {"status": "error", "error": f"Server not found: {server_id}"}

    proc: subprocess.Popen = entry["process"]
    running = proc.poll() is None
    return {
        "status": "running" if running else "stopped",
        "server_id": server_id,
        "pid": proc.pid,
        "url": f"http://{entry['host']}:{entry['port']}",
        "type": entry["type"],
        "path": entry["path"],
        "started_at": entry["started_at"],
    }


def server_list(**kwargs) -> dict:
    """Return a list of all tracked servers."""
    with _lock:
        servers = [
            {
                "server_id": e["id"],
                "url": f"http://{e['host']}:{e['port']}",
                "type": e["type"],
                "path": e["path"],
                "running": e["process"].poll() is None,
            }
            for e in _servers.values()
        ]
    return {"servers": servers, "count": len(servers)}


def server_logs(server_id: str, lines: int = 50, **kwargs) -> dict:
    """Return the last *lines* of stdout/stderr from the server."""
    with _lock:
        entry = _servers.get(server_id)
    if entry is None:
        return {"status": "error", "error": f"Server not found: {server_id}"}

    log_lines: list[str] = entry["log_lines"]
    tail = log_lines[-lines:] if len(log_lines) > lines else log_lines[:]
    return {"status": "ok", "server_id": server_id, "lines": tail, "total_lines": len(log_lines)}
