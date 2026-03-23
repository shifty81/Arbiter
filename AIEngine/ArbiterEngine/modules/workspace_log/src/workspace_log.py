"""Workspace log module — thin wrappers around core.logger helpers."""
from __future__ import annotations
from pathlib import Path

from core.logger import (
    write_workspace_log as _write,
    read_workspace_log as _read,
    get_workspace_log_path as _path,
)


def workspace_log_write(
    workspace: str,
    message: str,
    level: str = "INFO",
    source: str = "",
    **kwargs,
) -> dict:
    """Write a structured log entry to the workspace log.

    *level* can be DEBUG, INFO, WARNING, ERROR, or CRASH.
    *source* is an optional component identifier (e.g. 'self_build').
    """
    return _write(workspace, level, message, source=source)


def workspace_log_read(
    workspace: str,
    level: str | None = None,
    limit: int = 200,
    **kwargs,
) -> dict:
    """Return recent log entries from the workspace log.

    Pass *level* to filter by severity (case-insensitive).
    *limit* caps the number of entries returned (newest first).
    """
    entries = _read(workspace, level=level, limit=limit)
    return {"workspace": workspace, "count": len(entries), "entries": entries}


def workspace_log_clear(workspace: str, **kwargs) -> dict:
    """Delete the workspace log file, resetting the log to empty."""
    log_path = _path(workspace)
    if log_path.exists():
        log_path.unlink()
        return {"status": "cleared", "workspace": workspace}
    return {"status": "already_empty", "workspace": workspace}
