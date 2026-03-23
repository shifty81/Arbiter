"""Debug module — process debugging, tracing, and memory inspection utilities."""
from __future__ import annotations
import json
import os
import sys
import traceback
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


def _process_exists(pid: int) -> bool:
    """Return True if a process with *pid* is running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def debug_attach(pid: int, **kwargs) -> dict:
    """Inspect a running process by PID and return basic OS-level information.

    On Linux/macOS reads ``/proc/{pid}/status`` when available.
    Returns available info or an error if the process does not exist.
    """
    if not _process_exists(pid):
        return {"status": "error", "error": f"Process {pid} not found or permission denied"}

    info: dict = {"pid": pid, "status": "running"}

    # Try /proc on Linux
    proc_status = Path(f"/proc/{pid}/status")
    if proc_status.exists():
        try:
            lines = proc_status.read_text().splitlines()
            for line in lines:
                if ":" in line:
                    key, _, val = line.partition(":")
                    key_lower = key.strip().lower()
                    if key_lower == "pid":
                        continue  # keep the typed integer we already set
                    info[key_lower] = val.strip()
        except PermissionError:
            info["proc_status"] = "permission_denied"

    # Try reading the command line
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.exists():
        try:
            cmdline = proc_cmdline.read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip()
            info["cmdline"] = cmdline
        except PermissionError:
            pass

    return {"status": "ok", "info": info}


def debug_breakpoint(file: str, line: int, **kwargs) -> dict:
    """Record a logical breakpoint at *file*:*line* and validate the location.

    Reads the source file and returns the code line at the specified location
    so the caller can confirm the breakpoint target.
    """
    p = Path(file)
    if not p.exists():
        return {"status": "error", "error": f"File not found: {file}"}
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if line < 1 or line > len(lines):
        return {
            "status": "error",
            "error": f"Line {line} out of range (file has {len(lines)} lines)",
        }
    code_line = lines[line - 1]
    return {
        "status": "ok",
        "file": str(p.resolve()),
        "line": line,
        "code": code_line,
        "message": f"Breakpoint registered at {file}:{line}",
    }


def debug_trace(pid: int, output: str | None = None, **kwargs) -> dict:
    """Capture a lightweight stack trace snapshot of the current Python process.

    When *pid* matches the current process (``os.getpid()``), the live Python
    stack frames are collected.  For external PIDs the function reads
    ``/proc/{pid}/stack`` on Linux if available.

    The trace is written to *output* when provided.
    """
    result: dict = {"pid": pid}

    if pid == os.getpid():
        # Capture current-process frames
        frames = []
        for thread_id, frame in sys._current_frames().items():
            stack = traceback.extract_stack(frame)
            frames.append({
                "thread_id": thread_id,
                "stack": [{"file": f.filename, "line": f.lineno, "name": f.name, "text": f.line} for f in stack],
            })
        result["frames"] = frames
        result["status"] = "ok"
    else:
        if not _process_exists(pid):
            return {"status": "error", "error": f"Process {pid} not found"}
        proc_stack = Path(f"/proc/{pid}/stack")
        if proc_stack.exists():
            try:
                result["kernel_stack"] = proc_stack.read_text()
                result["status"] = "ok"
            except PermissionError:
                result["status"] = "error"
                result["error"] = "Permission denied reading /proc stack"
        else:
            result["status"] = "ok"
            result["message"] = "External PID trace requires ptrace/gdb; only /proc available on this system."

    if output and result.get("status") == "ok":
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))
        result["output"] = str(out)

    return result


def debug_memory(pid: int, **kwargs) -> dict:
    """Return memory usage information for *pid*.

    Reads ``/proc/{pid}/status`` on Linux for VmRSS and VmSize.
    For the current process also uses Python's ``tracemalloc`` snapshot.
    """
    if not _process_exists(pid):
        return {"status": "error", "error": f"Process {pid} not found"}

    memory: dict = {"pid": pid}

    # /proc-based memory info (Linux)
    proc_status = Path(f"/proc/{pid}/status")
    if proc_status.exists():
        try:
            for line in proc_status.read_text().splitlines():
                if line.startswith(("VmRSS", "VmSize", "VmPeak", "VmSwap")):
                    key, _, val = line.partition(":")
                    memory[key.strip()] = val.strip()
        except PermissionError:
            memory["proc_status"] = "permission_denied"

    # Python tracemalloc for current process
    if pid == os.getpid():
        import tracemalloc
        if not tracemalloc.is_tracing():
            tracemalloc.start()
        snap = tracemalloc.take_snapshot()
        stats = snap.statistics("lineno")[:5]
        memory["top_allocations"] = [
            {"file": str(s.traceback[0].filename), "line": s.traceback[0].lineno, "size_kb": round(s.size / 1024, 2)}
            for s in stats
        ]

    return {"status": "ok", "memory": memory}
