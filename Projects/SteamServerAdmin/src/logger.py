"""SteamServerAdmin — Logging Setup.

Mirrors the pattern from Arbiter's core/logger.py:
  - RotatingFileHandler writing to logs/steam_server_admin/<name>.log
  - Console handler with the same format
  - setup_ssa_logging() is called once at startup
  - get_ssa_logger(name) returns a named logger for any SSA module
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Root directory of the SteamServerAdmin project (two levels up from this file)
_SSA_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _SSA_ROOT / "logs" / "steam_server_admin"

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 5 * 1024 * 1024   # 5 MB per file
_BACKUP_COUNT = 5


def setup_ssa_logging(log_name: str = "ssa_main", level: int = logging.INFO) -> None:
    """Initialise SteamServerAdmin logging.

    Creates ``logs/steam_server_admin/<log_name>.log`` with rotating file
    output and a console handler.  Safe to call multiple times (idempotent via
    root-logger guard).
    """
    root = logging.getLogger("ssa")
    if root.handlers:
        return  # already configured

    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # ── Rotating file handler ─────────────────────────────────────────────────
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _LOG_DIR / f"{log_name}.log"
    fh = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # ── Console handler ───────────────────────────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    root.info("SteamServerAdmin logging initialised → %s", log_file)


def get_ssa_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under ``ssa.<name>``.

    Call ``setup_ssa_logging()`` before first use.
    """
    return logging.getLogger(f"ssa.{name}")
