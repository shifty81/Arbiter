"""Profile module — CPU and memory profiling for Python commands and files."""
from __future__ import annotations
import cProfile
import io
import json
import os
import pstats
import subprocess
import sys
import tracemalloc
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


def profile_cpu(command: str, duration: int = 30, output: str | None = None, **kwargs) -> dict:
    """Profile CPU usage of a Python expression or script path.

    *command* can be:
    - A Python expression (e.g. ``"sum(range(1_000_000))"``).
    - An absolute path to a Python script file.

    Profiling results are returned as a summary dict and optionally written
    to *output* as a JSON file.
    """
    profiler = cProfile.Profile()

    p = Path(command)
    if p.is_file() and command.endswith(".py"):
        source = p.read_text(encoding="utf-8")
        ns: dict = {}
        try:
            profiler.enable()
            exec(compile(source, str(p), "exec"), ns)  # noqa: S102
            profiler.disable()
            run_ok = True
            run_error = None
        except Exception as exc:
            profiler.disable()
            run_ok = False
            run_error = str(exc)
    else:
        ns = {}
        try:
            profiler.enable()
            exec(compile(command, "<profile>", "exec"), ns)  # noqa: S102
            profiler.disable()
            run_ok = True
            run_error = None
        except Exception as exc:
            profiler.disable()
            run_ok = False
            run_error = str(exc)

    stream = io.StringIO()
    ps = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
    ps.print_stats(20)
    stats_text = stream.getvalue()

    # Parse top entries into structured data
    top: list[dict] = []
    for line in stats_text.splitlines():
        parts = line.split(None, 5)
        if len(parts) == 6 and parts[0].replace(".", "").isdigit():
            top.append({
                "ncalls": parts[0],
                "tottime": parts[1],
                "percall_tot": parts[2],
                "cumtime": parts[3],
                "percall_cum": parts[4],
                "location": parts[5],
            })

    result: dict = {
        "status": "ok" if run_ok else "error",
        "command": command,
        "top_functions": top[:20],
        "stats_text": stats_text,
    }
    if run_error:
        result["error"] = run_error

    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))
        result["output"] = str(out)

    return result


def profile_memory(command: str, output: str | None = None, **kwargs) -> dict:
    """Profile memory allocations of a Python expression or script path.

    Uses ``tracemalloc`` to capture the top allocation sites.
    """
    tracemalloc.start()
    p = Path(command)
    run_ok = True
    run_error = None
    ns: dict = {}
    try:
        if p.is_file() and command.endswith(".py"):
            source = p.read_text(encoding="utf-8")
            exec(compile(source, str(p), "exec"), ns)  # noqa: S102
        else:
            exec(compile(command, "<profile>", "exec"), ns)  # noqa: S102
    except Exception as exc:
        run_ok = False
        run_error = str(exc)

    snap = tracemalloc.take_snapshot()
    tracemalloc.stop()

    top_stats = snap.statistics("lineno")[:20]
    allocations = [
        {
            "file": str(s.traceback[0].filename),
            "line": s.traceback[0].lineno,
            "size_kb": round(s.size / 1024, 2),
            "count": s.count,
        }
        for s in top_stats
    ]
    total_kb = round(sum(s.size for s in top_stats) / 1024, 2)

    result: dict = {
        "status": "ok" if run_ok else "error",
        "command": command,
        "total_tracked_kb": total_kb,
        "top_allocations": allocations,
    }
    if run_error:
        result["error"] = run_error

    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))
        result["output"] = str(out)

    return result


def profile_report(profile_data: str, output: str | None = None, format: str = "text", **kwargs) -> dict:
    """Load profiling data from a file and produce a human-readable report.

    *profile_data* may be:
    - A JSON file previously written by ``profile_cpu`` or ``profile_memory``.
    - A ``cProfile`` ``.prof`` binary file.

    *format* can be ``"text"`` (default) or ``"json"``.
    """
    data_path = Path(profile_data)
    if not data_path.exists():
        return {"status": "error", "error": f"Profile data file not found: {profile_data}"}

    # JSON data (from our own profile_cpu / profile_memory)
    if data_path.suffix == ".json":
        data = json.loads(data_path.read_text())
        report = json.dumps(data, indent=2) if format == "json" else json.dumps(data, indent=2)
        result = {"status": "ok", "format": format, "report": report, "source": str(data_path)}
    elif data_path.suffix == ".prof":
        stream = io.StringIO()
        ps = pstats.Stats(str(data_path), stream=stream).sort_stats("cumulative")
        ps.print_stats(30)
        report = stream.getvalue()
        result = {"status": "ok", "format": "text", "report": report, "source": str(data_path)}
    else:
        # Try treating it as a plain text log
        report = data_path.read_text(encoding="utf-8", errors="replace")
        result = {"status": "ok", "format": "text", "report": report, "source": str(data_path)}

    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result["report"])
        result["output"] = str(out)

    return result
