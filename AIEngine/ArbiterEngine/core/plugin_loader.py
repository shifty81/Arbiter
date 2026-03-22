"""Plugin loader — discovers and loads plugins from the plugins/ directory."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from core.logger import get_logger
from core.tool_registry import ToolRegistry

logger = get_logger(__name__)


class PluginLoader:
    def __init__(self, plugins_dir: str | Path, tool_registry: ToolRegistry) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.tool_registry = tool_registry
        self._loaded: dict[str, dict[str, Any]] = {}

    def load_all(self) -> None:
        if not self.plugins_dir.exists():
            logger.warning("Plugins directory not found: %s", self.plugins_dir)
            return
        for plugin_dir in self.plugins_dir.iterdir():
            if plugin_dir.is_dir():
                self._load_plugin(plugin_dir)

    def _load_plugin(self, plugin_dir: Path) -> None:
        manifest = plugin_dir / "plugin.json"
        if not manifest.exists():
            return
        try:
            with manifest.open() as f:
                meta = json.load(f)
            name = meta.get("name", plugin_dir.name)
            logger.info("Loading plugin: %s", name)
            tools_file = plugin_dir / "tools.json"
            if tools_file.exists():
                self.tool_registry.register_from_file(tools_file)
            self._loaded[name] = meta
            logger.info("Plugin loaded: %s v%s", name, meta.get("version", "?"))
        except Exception as exc:
            logger.error("Failed to load plugin %s: %s", plugin_dir.name, exc)

    def load_plugin(self, plugin_dir: str | Path) -> None:
        self._load_plugin(Path(plugin_dir))

    def unload_plugin(self, name: str) -> bool:
        if name in self._loaded:
            del self._loaded[name]
            logger.info("Plugin unloaded: %s", name)
            return True
        return False

    @property
    def loaded_plugins(self) -> dict[str, dict[str, Any]]:
        return dict(self._loaded)
