"""Job module — background job management with threading."""
from __future__ import annotations
import shlex
import subprocess
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="swissagent-job")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _run_job(job_id: str, task: str, args: dict) -> None:
    """Execute a shell command or module function as a background task."""
    with _lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = time.time()

    try:
        cmd = shlex.split(task)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        result: dict[str, Any] = {
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
        status = "done" if proc.returncode == 0 else "failed"
    except FileNotFoundError:
        result = {"error": f"Command not found: {task.split()[0]}"}
        status = "failed"
    except subprocess.TimeoutExpired:
        result = {"error": "Job timed out"}
        status = "failed"
    except Exception as exc:
        result = {"error": str(exc), "traceback": traceback.format_exc()}
        status = "failed"

    with _lock:
        _jobs[job_id]["status"] = status
        _jobs[job_id]["result"] = result
        _jobs[job_id]["finished_at"] = time.time()


def job_submit(task: str, args: dict | None = None, priority: int = 0, **kwargs) -> dict:
    """Submit *task* (a shell command string) as a background job.

    Returns a ``job_id`` that can be used with the other job tools.
    """
    job_id = uuid.uuid4().hex[:8]
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "task": task,
            "args": args or {},
            "priority": priority,
            "status": "queued",
            "result": None,
            "submitted_at": time.time(),
            "started_at": None,
            "finished_at": None,
        }
    _executor.submit(_run_job, job_id, task, args or {})
    logger.info("Job %s submitted: %s", job_id, task)
    return {"status": "submitted", "job_id": job_id}


def job_status(job_id: str, **kwargs) -> dict:
    """Return the current status of job *job_id*."""
    with _lock:
        entry = _jobs.get(job_id)
    if entry is None:
        return {"status": "error", "error": f"Job not found: {job_id}"}
    return {
        "job_id": job_id,
        "task": entry["task"],
        "status": entry["status"],
        "submitted_at": entry["submitted_at"],
        "started_at": entry["started_at"],
        "finished_at": entry["finished_at"],
    }


def job_cancel(job_id: str, **kwargs) -> dict:
    """Mark a queued job as cancelled (running jobs cannot be interrupted)."""
    with _lock:
        entry = _jobs.get(job_id)
        if entry is None:
            return {"status": "error", "error": f"Job not found: {job_id}"}
        if entry["status"] == "queued":
            entry["status"] = "cancelled"
            entry["finished_at"] = time.time()
            return {"status": "cancelled", "job_id": job_id}
        return {"status": entry["status"], "job_id": job_id, "message": "Only queued jobs can be cancelled."}


def job_list(status: str | None = None, **kwargs) -> dict:
    """List all jobs, optionally filtered by *status*."""
    with _lock:
        jobs = [
            {
                "job_id": j["id"],
                "task": j["task"],
                "status": j["status"],
                "submitted_at": j["submitted_at"],
            }
            for j in _jobs.values()
            if status is None or j["status"] == status
        ]
    return {"jobs": jobs, "count": len(jobs)}


def job_result(job_id: str, **kwargs) -> dict:
    """Return the result payload of a completed job."""
    with _lock:
        entry = _jobs.get(job_id)
    if entry is None:
        return {"status": "error", "error": f"Job not found: {job_id}"}
    if entry["status"] not in {"done", "failed"}:
        return {"status": entry["status"], "job_id": job_id, "result": None}
    return {"status": entry["status"], "job_id": job_id, "result": entry["result"]}
