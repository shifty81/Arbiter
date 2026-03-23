"""Module loader — discovers and initialises Arbiter Engine modules."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from core.logger import get_logger
from core.tool_registry import ToolRegistry

logger = get_logger(__name__)


class ModuleLoader:
    def __init__(self, modules_dir: str | Path, tool_registry: ToolRegistry) -> None:
        self.modules_dir = Path(modules_dir)
        self.tool_registry = tool_registry
        self._loaded: dict[str, dict[str, Any]] = {}

    def load_all(self) -> None:
        if not self.modules_dir.exists():
            logger.warning("Modules directory not found: %s", self.modules_dir)
            return
        for module_dir in sorted(self.modules_dir.iterdir()):
            if module_dir.is_dir():
                self._load_module(module_dir)

    def _load_module(self, module_dir: Path) -> None:
        manifest = module_dir / "module.json"
        if not manifest.exists():
            return
        try:
            with manifest.open() as f:
                meta = json.load(f)
            name = meta.get("name", module_dir.name)
            tools_file = module_dir / "tools.json"
            if tools_file.exists():
                self.tool_registry.register_from_file(tools_file)
            self._loaded[name] = meta
            logger.debug("Module loaded: %s", name)
        except Exception as exc:
            logger.error("Failed to load module %s: %s", module_dir.name, exc)

    @property
    def loaded_modules(self) -> dict[str, dict[str, Any]]:
        return dict(self._loaded)
