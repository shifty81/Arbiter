"""Tool registry — central store for all registered tools."""
from __future__ import annotations
import importlib
import json
from pathlib import Path
from typing import Any, Callable
from core.logger import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """Maintains a registry of all available tools loaded from JSON definitions."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}
        self._callables: dict[str, Callable[..., Any]] = {}

    def register(self, tool_def: dict[str, Any], func: Callable[..., Any] | None = None) -> None:
        name = tool_def["name"]
        self._tools[name] = tool_def
        if func is not None:
            self._callables[name] = func
        logger.debug("Registered tool: %s", name)

    def register_from_file(self, path: str | Path) -> None:
        path = Path(path)
        if not path.exists():
            logger.warning("tools.json not found: %s", path)
            return
        with path.open() as f:
            data = json.load(f)
        tools = data if isinstance(data, list) else data.get("tools", [])
        for tool_def in tools:
            self._resolve_and_register(tool_def)

    def register_from_directory(self, directory: str | Path) -> None:
        directory = Path(directory)
        for tools_file in directory.rglob("tools.json"):
            self.register_from_file(tools_file)

    def get(self, name: str) -> dict[str, Any] | None:
        tool = self._tools.get(name)
        if tool is None:
            return None
        func = self._callables.get(name)
        return {**tool, "_callable": func} if func is not None else tool

    def get_callable(self, name: str) -> Callable[..., Any] | None:
        return self._callables.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._tools.values())

    def _resolve_and_register(self, tool_def: dict[str, Any]) -> None:
        func = None
        function_path = tool_def.get("function")
        if function_path:
            try:
                module_path, _, func_name = function_path.rpartition(".")
                mod = importlib.import_module(module_path)
                func = getattr(mod, func_name, None)
            except Exception as exc:
                logger.warning("Could not resolve function %r: %s", function_path, exc)
        self.register(tool_def, func)
