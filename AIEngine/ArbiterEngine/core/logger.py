"""Logging setup for Arbiter Engine.

Each Arbiter subsystem writes its rotating log file into a dedicated subfolder
under the repository-level ``logs/`` directory so all system logs are
aggregated in one place.  The subfolder mapping is:

    logs/arbiter_engine/      – Arbiter Engine (server.py, port 8001)
    logs/python_bridge/       – FastAPI PythonBridge (fastapi_bridge.py, port 8000)
    logs/host_app/            – WPF HostApp events forwarded via the bridge
    logs/vs_extension/        – Visual Studio extension events
    logs/self_build/          – Autonomous self-build loop
    logs/steam_server_admin/  – SteamServerAdmin standalone project

Per-project structured logs (JSONL) continue to live in the workspace at
``.arbiter/logs/workspace.jsonl`` and are managed by :func:`write_workspace_log`.
"""
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

# How many parent directories to walk when searching for the repo root.
# See _find_repo_root() for the rationale behind this value.
_MAX_REPO_TRAVERSAL_DEPTH = 8

# Mapping from subsystem name to subfolder name under the repo-level logs/ dir
_SYSTEM_LOG_DIRS: dict[str, str] = {
    "arbiter_engine": "arbiter_engine",
    "python_bridge": "python_bridge",
    "host_app": "host_app",
    "vs_extension": "vs_extension",
    "self_build": "self_build",
    "steam_server_admin": "steam_server_admin",
}


def _find_repo_root(start: Path | None = None) -> Path:
    """Walk upward from *start* (default: this file's directory) to find the
    repository root — identified by the presence of ``roadmap.json``.

    We limit traversal to 8 levels.  This is deliberately generous: the
    deepest any Arbiter source file currently sits relative to the repo root
    is ``AIEngine/ArbiterEngine/core/`` (3 levels), so 8 covers even deeply
    nested future layouts while avoiding runaway traversal to filesystem root
    on misconfigured or containerised environments.

    Falls back to a directory two levels above this file if not found.
    """
    candidate = (start or Path(__file__).resolve().parent)
    for _ in range(_MAX_REPO_TRAVERSAL_DEPTH):
        if (candidate / "roadmap.json").exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    # Fallback: two levels above the core/ package (ArbiterEngine root)
    return Path(__file__).resolve().parent.parent


def get_system_log_path(system: str, filename: str | None = None) -> Path:
    """Return the path for a system-level log file under ``<repo_root>/logs/<system>/``.

    If *filename* is omitted it defaults to ``<system>.log``.
    """
    root = _find_repo_root()
    folder = _SYSTEM_LOG_DIRS.get(system, system)
    log_dir = root / "logs" / folder
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / (filename or f"{folder}.log")


def setup_logging(level: int = logging.INFO, log_file: str | Path | None = None) -> None:
    """Configure root logger for Arbiter Engine.

    When *log_file* is given a :class:`RotatingFileHandler` is used so the
    log never grows unbounded.

    If *log_file* is ``None`` a default system-level log is written to
    ``<repo_root>/logs/arbiter_engine/arbiter_engine.log`` automatically.
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

    # Resolve the file path — fall back to the default system log location
    if log_file is None:
        log_path = get_system_log_path("arbiter_engine")
    else:
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


def setup_system_logging(
    system: str,
    level: int = logging.INFO,
    filename: str | None = None,
) -> logging.Logger:
    """Set up a dedicated rotating log file for a named subsystem.

    The log file is written to ``<repo_root>/logs/<system>/<filename>``.
    Returns a logger namespaced as ``arbiter.<system>``.

    This is the preferred entry point for non-engine subsystems (e.g. the
    PythonBridge, self-build loop, VS extension event relay).

    Example::

        logger = setup_system_logging("python_bridge")
        logger.info("PythonBridge started on port 8000")
    """
    log_path = get_system_log_path(system, filename)
    logger_name = f"arbiter.{system}"
    sys_logger = logging.getLogger(logger_name)
    if sys_logger.handlers:
        # Already configured — return as-is to support hot-reload scenarios
        return sys_logger

    sys_logger.setLevel(level)
    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FMT)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    sys_logger.addHandler(ch)

    fh = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    sys_logger.addHandler(fh)
    return sys_logger


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
