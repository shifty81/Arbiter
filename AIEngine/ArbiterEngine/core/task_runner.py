"""Task runner — executes tool callables with argument validation."""
from __future__ import annotations
import concurrent.futures
from typing import Any, Callable
from core.logger import get_logger

logger = get_logger(__name__)


class TaskRunner:
    def __init__(self, max_workers: int = 4) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    def run(self, tool: dict[str, Any], args: dict[str, Any]) -> Any:
        func: Callable[..., Any] | None = tool.get("_callable")
        if func is None:
            return {"error": f"No callable for tool '{tool.get('name')}'"}
        try:
            logger.debug("Running tool %r with args %s", tool.get("name"), args)
            return func(**args)
        except Exception as exc:
            logger.error("Tool %r raised: %s", tool.get("name"), exc)
            return {"error": str(exc)}

    def run_parallel(self, tasks: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[Any]:
        futures = [self._executor.submit(self.run, tool, args) for tool, args in tasks]
        return [f.result() for f in futures]

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)
