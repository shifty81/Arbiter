"""Permission system — controls what tools and file paths are accessible."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from core.logger import get_logger

logger = get_logger(__name__)


class PermissionSystem:
    """Enforces access control for tool execution and filesystem operations."""

    def __init__(self) -> None:
        self._allowed_dirs: list[Path] = []
        self._blocked_dirs: list[Path] = []
        self._blocked_tools: set[str] = set()
        self._allowed_tools: set[str] | None = None

    def allow_dir(self, path: str | Path) -> None:
        self._allowed_dirs.append(Path(path).resolve())

    def block_dir(self, path: str | Path) -> None:
        self._blocked_dirs.append(Path(path).resolve())

    def block_tool(self, name: str) -> None:
        self._blocked_tools.add(name)

    def allow_only_tools(self, names: list[str]) -> None:
        self._allowed_tools = set(names)

    def is_allowed(self, tool_name: str, args: dict[str, Any]) -> bool:
        if tool_name in self._blocked_tools:
            logger.warning("Tool blocked: %s", tool_name)
            return False
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            logger.warning("Tool not in allowlist: %s", tool_name)
            return False
        if not isinstance(args, dict):
            return True
        for v in args.values():
            if not self._check_arg_value(v):
                return False
        return True

    def is_path_allowed(self, path: str | Path) -> bool:
        return self._check_path(str(path))

    def safe_write(self, path: str | Path) -> bool:
        return self._check_path(str(path))

    def safe_delete(self, path: str | Path) -> bool:
        return self._check_path(str(path))

    def _check_arg_value(self, value: object) -> bool:
        if isinstance(value, str):
            if "/" in value or "\\" in value:
                return self._check_path(value)
        elif isinstance(value, dict):
            return all(self._check_arg_value(v) for v in value.values())
        elif isinstance(value, (list, tuple)):
            return all(self._check_arg_value(v) for v in value)
        return True

    def _check_path(self, path_str: str) -> bool:
        resolved = Path(path_str).resolve()
        for blocked in self._blocked_dirs:
            try:
                resolved.relative_to(blocked)
                logger.warning("Path blocked: %s", resolved)
                return False
            except ValueError:
                pass
        if self._allowed_dirs:
            for allowed in self._allowed_dirs:
                try:
                    resolved.relative_to(allowed)
                    return True
                except ValueError:
                    pass
            logger.warning("Path not in allowed dirs: %s", resolved)
            return False
        return True
