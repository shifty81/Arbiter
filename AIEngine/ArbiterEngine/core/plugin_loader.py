"""Plugin loader — discovers and loads plugins from the plugins/ directory."""
from __future__ import annotations
import json
import time
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
        # Track manifest mtime for hot-reload change detection
        self._mtimes: dict[str, float] = {}

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
            # Store the directory name so callers can locate routes.py
            meta["_dir"] = plugin_dir.name
            self._loaded[name] = meta
            self._mtimes[name] = manifest.stat().st_mtime
            logger.info("Plugin loaded: %s v%s", name, meta.get("version", "?"))
        except Exception as exc:
            logger.error("Failed to load plugin %s: %s", plugin_dir.name, exc)

    def load_plugin(self, plugin_dir: str | Path) -> None:
        self._load_plugin(Path(plugin_dir))

    def unload_plugin(self, name: str) -> bool:
        if name in self._loaded:
            del self._loaded[name]
            self._mtimes.pop(name, None)
            logger.info("Plugin unloaded: %s", name)
            return True
        return False

    def reload_plugin(self, name: str) -> bool:
        """Reload a single plugin by name without restarting the server.

        Finds the plugin directory whose ``plugin.json`` declares the given
        name, unloads the old registration, then re-loads from disk.

        Returns ``True`` if the plugin was found and reloaded, ``False`` if the
        plugin could not be located.
        """
        if not self.plugins_dir.exists():
            return False
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest = plugin_dir / "plugin.json"
            if not manifest.exists():
                continue
            try:
                with manifest.open() as f:
                    meta = json.load(f)
            except Exception:
                continue
            if meta.get("name", plugin_dir.name) == name:
                self.unload_plugin(name)
                self._load_plugin(plugin_dir)
                logger.info("Plugin hot-reloaded: %s", name)
                return True
        return False

    def reload_all(self) -> list[str]:
        """Reload every plugin whose manifest mtime has changed.

        Returns the list of plugin names that were reloaded.
        """
        if not self.plugins_dir.exists():
            return []
        reloaded: list[str] = []
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest = plugin_dir / "plugin.json"
            if not manifest.exists():
                continue
            try:
                mtime = manifest.stat().st_mtime
                with manifest.open() as f:
                    meta = json.load(f)
                name = meta.get("name", plugin_dir.name)
                if self._mtimes.get(name, 0) != mtime:
                    self.unload_plugin(name)
                    self._load_plugin(plugin_dir)
                    reloaded.append(name)
            except Exception as exc:
                logger.error("Failed to reload plugin %s: %s", plugin_dir.name, exc)
        return reloaded

    @property
    def loaded_plugins(self) -> dict[str, dict[str, Any]]:
        return dict(self._loaded)
