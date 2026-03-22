"""Config loader — loads TOML/JSON configuration files."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from core.logger import get_logger

logger = get_logger(__name__)

try:
    import toml
    _HAS_TOML = True
except ImportError:
    _HAS_TOML = False


class ConfigLoader:
    """Loads and merges configuration from TOML/JSON files."""

    def __init__(self, config_dir: str | Path = "configs") -> None:
        self.config_dir = Path(config_dir)
        self._data: dict[str, Any] = {}

    def load(self, filename: str = "config.toml") -> None:
        path = self.config_dir / filename
        if not path.exists():
            logger.warning("Config file not found: %s", path)
            return
        if path.suffix == ".toml" and _HAS_TOML:
            with path.open() as f:
                data = toml.load(f)
        elif path.suffix == ".json":
            with path.open() as f:
                data = json.load(f)
        else:
            logger.warning("Unsupported config format: %s", path.suffix)
            return
        self._data.update(data)
        logger.info("Loaded config: %s", path)

    def get(self, key: str, default: Any = None) -> Any:
        parts = key.split(".")
        val: Any = self._data
        for part in parts:
            if not isinstance(val, dict) or part not in val:
                return default
            val = val[part]
        return val

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        d = self._data
        for part in parts[:-1]:
            d = d.setdefault(part, {})
        d[parts[-1]] = value

    @property
    def data(self) -> dict[str, Any]:
        return dict(self._data)
