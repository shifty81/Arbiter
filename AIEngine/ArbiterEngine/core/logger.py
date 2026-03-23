"""Logging setup for Arbiter Engine."""
from __future__ import annotations
import json
import logging
import logging.handlers
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_initialized = False

# Maximum size per log file before rotation (5 MB) and how many backups to keep
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 5


def setup_logging(level: int = logging.INFO, log_file: str | Path | None = None) -> None:
    """Configure root logger for Arbiter Engine.

    When *log_file* is given a :class:`RotatingFileHandler` is used so the
    log never grows unbounded.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True
    root = logging.getLogger("arbiter")
    root.setLevel(level)
    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FMT)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under 'arbiter'."""
    if not name.startswith("arbiter"):
        name = f"arbiter.{name}"
    return logging.getLogger(name)


# ── Workspace-level structured log ───────────────────────────────────────────

def get_workspace_log_path(workspace: str | Path) -> Path:
    """Return the path to the structured workspace log file."""
    return Path(workspace) / ".arbiter" / "logs" / "workspace.jsonl"


def write_workspace_log(
    workspace: str | Path,
    level: str,
    message: str,
    *,
    source: str = "",
    extra: dict | None = None,
) -> dict:
    """Append a structured JSON log entry to the workspace log.

    Entries are newline-delimited JSON (JSONL) so they can be streamed and
    tail-read efficiently.
    """
    log_path = get_workspace_log_path(workspace)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "source": source,
        "message": message,
    }
    if extra:
        entry["extra"] = extra
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def read_workspace_log(
    workspace: str | Path,
    *,
    level: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Read the most recent *limit* entries from the workspace log.

    If *level* is given only entries with that level (case-insensitive) are
    returned.
    """
    log_path = get_workspace_log_path(workspace)
    if not log_path.exists():
        return []
    entries: list[dict] = []
    for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if level and entry.get("level", "").upper() != level.upper():
            continue
        entries.append(entry)
    return entries[-limit:]


# ── Crash capture ─────────────────────────────────────────────────────────────

def capture_crash(workspace: str | Path, exc: BaseException, *, source: str = "") -> dict:
    """Write a structured crash entry to the workspace log and return it.

    The entry includes the full traceback so it can later be filed as an
    issue in the local issues tracker.
    """
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    entry = write_workspace_log(
        workspace,
        "CRASH",
        str(exc),
        source=source,
        extra={"traceback": tb, "exc_type": type(exc).__name__},
    )
    return entry
