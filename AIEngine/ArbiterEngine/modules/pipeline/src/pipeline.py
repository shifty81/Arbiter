"""Pipeline module — define and run multi-step build/deploy pipelines."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Pipeline registry (in-memory, process-lifetime)
# ---------------------------------------------------------------------------
_pipelines: dict[str, "Pipeline"] = {}
_runs: dict[str, dict[str, Any]] = {}


@dataclass
class PipelineStep:
    name: str
    func: Callable[..., Any]
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Pipeline:
    name: str
    steps: list[PipelineStep] = field(default_factory=list)

    def run(self, context: dict | None = None) -> dict:
        ctx = context or {}
        results: list[dict] = []
        for step in self.steps:
            logger.info("Pipeline %r: running step %r", self.name, step.name)
            start = time.monotonic()
            try:
                result = step.func(**{**step.kwargs, **ctx})
            except Exception as exc:
                result = {"error": str(exc)}
            elapsed = time.monotonic() - start
            results.append({"step": step.name, "elapsed_s": round(elapsed, 3), "result": result})
            if isinstance(result, dict) and "error" in result:
                logger.error("Pipeline step %r failed: %s", step.name, result["error"])
                return {"pipeline": self.name, "status": "failed", "steps": results}
        return {"pipeline": self.name, "status": "success", "steps": results}


def _default_pipelines() -> dict[str, "Pipeline"]:
    """Create a set of built-in pipelines."""
    from tools.build_runner import BuildRunner
    from tools.feedback_parser import FeedbackParser
    runner = BuildRunner()
    parser = FeedbackParser()

    def _build_step(workspace_path: str = "workspace/sample_project") -> dict:
        output = runner.run(workspace_path)
        result = parser.parse(output)
        return {"output": output, "errors": len(result.errors), "warnings": len(result.warnings)}

    build = Pipeline("build")
    build.steps = [PipelineStep("build", _build_step)]
    return {"build": build}


def pipeline_run(name: str, context: dict | None = None) -> dict:
    """Run a registered pipeline by name."""
    if not _pipelines:
        _pipelines.update(_default_pipelines())
    pl = _pipelines.get(name)
    if pl is None:
        return {"error": f"Pipeline '{name}' not found"}
    result = pl.run(context)
    run_id = f"{name}_{int(time.time())}"
    _runs[run_id] = result
    return {**result, "run_id": run_id}


def pipeline_list() -> dict:
    """List available pipeline names."""
    if not _pipelines:
        _pipelines.update(_default_pipelines())
    return {"pipelines": list(_pipelines.keys())}


def pipeline_status(run_id: str) -> dict:
    """Get the result of a previous pipeline run."""
    run = _runs.get(run_id)
    if run is None:
        return {"error": f"Run '{run_id}' not found"}
    return run


def pipeline_cancel(run_id: str) -> dict:
    """Mark a run as cancelled (pipelines are synchronous — cancels future steps)."""
    if run_id in _runs:
        _runs[run_id]["status"] = "cancelled"
        return {"cancelled": run_id}
    return {"error": f"Run '{run_id}' not found"}


def pipeline_register(name: str, steps_json: str) -> dict:
    """Register a new pipeline from a JSON step list.

    steps_json format::

        [{"name": "build", "module": "modules.build.src.build_tools", "func": "build_cmake",
          "kwargs": {"path": "workspace/myproject"}}]
    """
    import importlib
    steps_data = json.loads(steps_json)
    steps: list[PipelineStep] = []
    for s in steps_data:
        mod = importlib.import_module(s["module"])
        func = getattr(mod, s["func"])
        steps.append(PipelineStep(s["name"], func, s.get("kwargs", {})))
    _pipelines[name] = Pipeline(name, steps)
    return {"registered": name, "steps": len(steps)}

