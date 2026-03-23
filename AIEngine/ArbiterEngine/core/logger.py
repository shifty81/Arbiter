"""Logging setup for Arbiter Engine."""
from __future__ import annotations
import logging
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_initialized = False


def setup_logging(level: int = logging.INFO, log_file: str | Path | None = None) -> None:
    """Configure root logger for Arbiter Engine."""
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
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under 'arbiter'."""
    if not name.startswith("arbiter"):
        name = f"arbiter.{name}"
    return logging.getLogger(name)
