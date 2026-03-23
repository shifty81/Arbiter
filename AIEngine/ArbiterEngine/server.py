"""Arbiter Engine Bridge Server.

Exposes the same REST API contract as ArbiterAI's PythonBridge (fastapi_bridge.py)
so the WPF application can connect without any code changes, just a different port.

Default port: 8001  (ArbiterAI bridge stays on 8000)

Start:
    cd AIEngine/ArbiterEngine
    python server.py
"""
from __future__ import annotations

import os
import sys
import json
import sqlite3
import subprocess
import platform
from pathlib import Path
from typing import Any

# ── Ensure local packages are importable ─────────────────────────────────────
_BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(_BASE))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from core.logger import get_logger, setup_logging
from core.config_loader import ConfigLoader
from core.module_loader import ModuleLoader
from core.permission import PermissionSystem
from core.plugin_loader import PluginLoader
from core.task_runner import TaskRunner
from core.tool_registry import ToolRegistry
from llm.factory import create_llm

setup_logging(log_file=_BASE / "logs" / "arbiter_engine.log")
logger = get_logger(__name__)

# ── Boot the agent stack ──────────────────────────────────────────────────────
_config = ConfigLoader(_BASE / "configs")
_config.load()

_registry = ToolRegistry()
ModuleLoader(_BASE / "modules", _registry).load_all()
_plugin_loader = PluginLoader(_BASE / "plugins", _registry)
_plugin_loader.load_all()

_backend = _config.get("agent.default_llm_backend", "ollama")
_llm = create_llm(_backend, _config)
_permissions = PermissionSystem()
_runner = TaskRunner()

# ── Per-project chat history (in-memory) ─────────────────────────────────────
_chat_histories: dict[str, list[dict[str, Any]]] = {}

# ── Arbiter AI personas list (mirrors fastapi_bridge.py) ─────────────────────
_PERSONAS = [
    "Arbiter", "Coder", "Teacher", "Organizer",
    "senior_developer", "software_architect", "frontend_developer",
    "backend_developer", "database_engineer", "mobile_developer",
    "devops_engineer", "security_auditor", "test_engineer",
    "code_reviewer", "performance_engineer", "documentation_writer",
    "ai_ml_engineer",
]
_active_personas: dict[str, str] = {}
_MAX_CHAT_HISTORY_TURNS = 40

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Arbiter Engine", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Pydantic models ───────────────────────────────────────────────────────────
class UserMessage(BaseModel):
    message: str
    project: str = "default"
    use_voice: bool = False
    voice: str = "British_Female"
    mode: str = "chat"  # "chat" | "agentic"


class PersonaRequest(BaseModel):
    persona: str


class BuildRequest(BaseModel):
    project: str
    command: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": "arbiter-engine", "version": "0.2.0"}


@app.get("/status")
def status() -> dict:
    tool_count = len(_registry.list_tools())
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / 1e9, 1)
        cpu = platform.processor() or platform.machine()
    except Exception:
        ram_gb = 0
        cpu = platform.machine()

    try:
        import torch
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
        vram_gb = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1) if torch.cuda.is_available() else 0
    except Exception:
        gpu = "CPU"
        vram_gb = 0

    return {
        "engine": "arbiter-engine",
        "llm_backend": _backend,
        "tool_count": tool_count,
        "cpu": cpu,
        "ram_gb": ram_gb,
        "gpu": gpu,
        "vram_gb": vram_gb,
    }


@app.get("/personas")
def get_personas() -> dict:
    return {"personas": _PERSONAS}


@app.get("/persona/{project_name}")
def get_project_persona(project_name: str) -> dict:
    persona = _active_personas.get(project_name, "Arbiter")
    return {"project": project_name, "persona": persona}


@app.post("/persona/{project_name}")
def set_project_persona(project_name: str, req: PersonaRequest) -> dict:
    if req.persona not in _PERSONAS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown persona '{req.persona}'")
    _active_personas[project_name] = req.persona
    logger.info("Persona for project %r set to %r", project_name, req.persona)
    return {"project": project_name, "persona": req.persona}


@app.post("/chat")
def chat(msg: UserMessage) -> dict:
    from core.agent import Agent

    history = _chat_histories.setdefault(msg.project, [])
    persona = _active_personas.get(msg.project, "Arbiter")

    # Rebuild agent with current project context each call (lightweight)
    agent = Agent(
        llm=_llm,
        tool_registry=_registry,
        permission_system=_permissions,
        task_runner=_runner,
        config=_config,
        project_path=msg.project,
    )

    try:
        response = agent.run(
            prompt=msg.message,
            project_path=msg.project,
            chat_history=history,
        )
    except Exception as exc:
        logger.error("Agent error: %s", exc)
        response = f"[Arbiter Engine error] {exc}"

    # Persist history (keep last _MAX_CHAT_HISTORY_TURNS turns)
    history.append({"role": "user", "content": msg.message})
    history.append({"role": "assistant", "content": response})
    if len(history) > _MAX_CHAT_HISTORY_TURNS:
        history[:] = history[-_MAX_CHAT_HISTORY_TURNS:]

    return {"response": response, "persona": persona}


@app.get("/history/{project_name}")
def history(project_name: str) -> dict:
    return {"history": _chat_histories.get(project_name, [])}


@app.get("/models")
def list_models() -> dict:
    try:
        models = _llm.list_models() if hasattr(_llm, "list_models") else []
    except Exception:
        models = []
    return {"models": models, "active_backend": _backend}


@app.post("/build")
def build_project(req: BuildRequest) -> dict:
    return _run_project_command(req, "build")


@app.post("/run")
def run_project(req: BuildRequest) -> dict:
    return _run_project_command(req, "run")


@app.post("/test")
def test_project(req: BuildRequest) -> dict:
    return _run_project_command(req, "test")


def _run_project_command(req: BuildRequest, action: str) -> dict:
    project_dir = Path("Projects") / req.project
    if not project_dir.exists():
        return {"success": False, "output": f"Project directory not found: {project_dir}"}
    cmd = req.command or _auto_detect_command(project_dir, action)
    if not cmd:
        return {"success": False, "output": f"Cannot auto-detect {action} command for this project."}
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=str(project_dir),
            capture_output=True, text=True, timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        return {"success": result.returncode == 0, "output": output, "command": cmd}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "Command timed out after 120 seconds.", "command": cmd}
    except Exception as exc:
        return {"success": False, "output": str(exc), "command": cmd}


def _auto_detect_command(project_dir: Path, action: str) -> str:
    if (project_dir / "Cargo.toml").exists():
        return {"build": "cargo build", "run": "cargo run", "test": "cargo test"}.get(action, "")
    if (project_dir / "package.json").exists():
        return {"build": "npm run build", "run": "npm start", "test": "npm test"}.get(action, "")
    if any(project_dir.glob("*.csproj")):
        return {"build": "dotnet build", "run": "dotnet run", "test": "dotnet test"}.get(action, "")
    if (project_dir / "CMakeLists.txt").exists():
        return {"build": "cmake --build .", "run": "", "test": "ctest"}.get(action, "")
    if list(project_dir.glob("*.py")):
        return {"build": "", "run": "python main.py", "test": "python -m pytest"}.get(action, "")
    return ""


# ── Plugin hot-reload endpoints (M2-11) ───────────────────────────────────────

class PluginReloadRequest(BaseModel):
    name: str = ""  # empty string means reload all changed plugins


@app.get("/plugins")
def list_plugins() -> dict:
    """Return all currently loaded plugins."""
    return {"plugins": list(_plugin_loader.loaded_plugins.values())}


@app.post("/plugins/reload")
def reload_plugins(req: PluginReloadRequest) -> dict:
    """Hot-reload a plugin (or all changed plugins) without restarting the server.

    If ``name`` is provided, reload that specific plugin.
    If ``name`` is empty, reload all plugins whose manifest has changed on disk.
    """
    if req.name:
        ok = _plugin_loader.reload_plugin(req.name)
        if not ok:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Plugin '{req.name}' not found")
        return {"status": "reloaded", "plugins": [req.name]}
    reloaded = _plugin_loader.reload_all()
    return {"status": "reloaded", "plugins": reloaded}


@app.post("/plugins/install")
def install_plugin(req: dict = {}) -> dict:
    """Placeholder for plugin installation (marketplace integration)."""
    return {"status": "not_implemented", "detail": "Plugin marketplace not yet available."}


# ── Tool call streaming via Server-Sent Events (M2-12) ────────────────────────

import asyncio
import queue as _queue
from fastapi.responses import StreamingResponse


class StreamBuildRequest(BaseModel):
    project: str
    command: str = ""
    action: str = "build"  # "build" | "run" | "test"


@app.post("/stream/run")
async def stream_run(req: StreamBuildRequest):
    """Stream build/run/test output as Server-Sent Events (text/event-stream).

    The client receives a sequence of ``data: <line>\\n\\n`` SSE events and a
    final ``data: [DONE]\\n\\n`` event when the process exits.

    Example::

        curl -N -X POST http://localhost:8001/stream/run \\
             -H 'Content-Type: application/json' \\
             -d '{"project":"myapp","action":"build"}'
    """
    project_dir = Path("Projects") / req.project
    if not project_dir.exists():
        async def _err():
            yield f"data: ERROR: Project not found: {req.project}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    cmd = req.command or _auto_detect_command(project_dir, req.action)
    if not cmd:
        async def _err2():
            yield f"data: ERROR: Cannot detect {req.action} command\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_err2(), media_type="text/event-stream")

    async def _generate():
        loop = asyncio.get_event_loop()
        line_queue: _queue.Queue[str | None] = _queue.Queue()

        def _reader():
            try:
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=str(project_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    line_queue.put(line.rstrip())
                proc.wait()
            except Exception as exc:
                line_queue.put(f"ERROR: {exc}")
            finally:
                line_queue.put(None)  # sentinel

        import threading
        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        while True:
            try:
                item = await loop.run_in_executor(None, lambda: line_queue.get(timeout=1))
            except _queue.Empty:
                continue
            if item is None:
                break
            yield f"data: {item}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ── M2-13: Multi-Agent Orchestration ─────────────────────────────────────────
#
#  Spawn specialist sub-agents (DevOps, Security, Docs, Frontend, Backend, …)
#  each with a focused system prompt.  The orchestrator runs them sequentially
#  (or reports their planned outputs) and aggregates results.
# ─────────────────────────────────────────────────────────────────────────────

import uuid as _uuid
import datetime as _datetime

# Registry of active and completed agent runs (in-memory; resets on restart)
_agent_runs: dict[str, dict] = {}

_SPECIALIST_PROMPTS: dict[str, str] = {
    "devops": (
        "You are a DevOps specialist. Focus on CI/CD pipelines, infrastructure, "
        "Docker, deployment automation, and operational reliability."
    ),
    "security": (
        "You are a security auditor. Identify vulnerabilities, insecure patterns, "
        "hardcoded secrets, OWASP risks, and recommend mitigations."
    ),
    "docs": (
        "You are a documentation writer. Produce clear, comprehensive docstrings, "
        "README sections, and API reference documentation."
    ),
    "frontend": (
        "You are a frontend developer specialising in UI/UX, HTML/CSS/JS, "
        "accessibility, and responsive design."
    ),
    "backend": (
        "You are a backend developer focusing on API design, database optimisation, "
        "concurrency, and server-side performance."
    ),
    "architect": (
        "You are a software architect. Evaluate system design, suggest scalable "
        "patterns, and identify technical debt."
    ),
    "test": (
        "You are a QA engineer. Write unit tests, integration tests, and identify "
        "edge cases. Aim for high coverage."
    ),
}


class SpawnAgentRequest(BaseModel):
    task: str                    # the task description to hand to the sub-agent
    specialization: str = "backend"  # one of _SPECIALIST_PROMPTS keys
    project: str = "default"
    parent_run_id: str = ""      # link to an orchestration run


class OrchestrateRequest(BaseModel):
    task: str
    project: str = "default"
    # Comma-separated list of specializations (empty = auto-select)
    agents: str = ""


@app.get("/agents")
def list_agents() -> dict:
    """Return all agent runs (active and completed)."""
    return {
        "runs": list(_agent_runs.values()),
        "specializations": list(_SPECIALIST_PROMPTS.keys()),
    }


@app.post("/agents/spawn")
def spawn_agent(req: SpawnAgentRequest) -> dict:
    """Spawn a single specialist sub-agent and return its response synchronously.

    For long tasks consider using ``/stream/agent`` (SSE) instead.
    """
    spec = req.specialization.lower()
    system_prompt = _SPECIALIST_PROMPTS.get(spec, _SPECIALIST_PROMPTS["backend"])

    run_id = str(_uuid.uuid4())[:8]
    run: dict = {
        "run_id": run_id,
        "specialization": spec,
        "task": req.task,
        "project": req.project,
        "parent_run_id": req.parent_run_id,
        "status": "running",
        "started_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "response": "",
    }
    _agent_runs[run_id] = run

    try:
        from core.agent import Agent
        agent = Agent(
            llm=_llm,
            tool_registry=_registry,
            permission_system=_permissions,
            task_runner=_runner,
            config=_config,
            project_path=req.project,
        )
        # Override the agent's effective system prompt via a wrapped message
        full_task = f"[{spec.upper()} SPECIALIST]\n{system_prompt}\n\nTask: {req.task}"
        response = agent.run(prompt=full_task, project_path=req.project)
    except Exception as exc:
        logger.error("Sub-agent %r error: %s", run_id, exc)
        response = f"[Agent error] {exc}"
        run["status"] = "error"
    else:
        run["status"] = "done"

    run["response"] = response
    run["completed_at"] = _datetime.datetime.now(_datetime.timezone.utc).isoformat()
    return {"run_id": run_id, "specialization": spec, "response": response, "status": run["status"]}


@app.post("/agents/orchestrate")
def orchestrate_agents(req: OrchestrateRequest) -> dict:
    """Orchestrate multiple specialist sub-agents for a single task.

    Each agent runs sequentially and receives the previous agent's output
    as additional context, producing a synthesised result.
    """
    if req.agents.strip():
        specs = [s.strip().lower() for s in req.agents.split(",") if s.strip()]
    else:
        # Auto-select agents based on task keywords
        task_lower = req.task.lower()
        specs = []
        if any(w in task_lower for w in ("deploy", "docker", "ci", "pipeline")):
            specs.append("devops")
        if any(w in task_lower for w in ("security", "auth", "secret", "vuln")):
            specs.append("security")
        if any(w in task_lower for w in ("test", "spec", "assert")):
            specs.append("test")
        if any(w in task_lower for w in ("doc", "readme", "comment")):
            specs.append("docs")
        if not specs:
            specs = ["architect", "backend"]

    orch_id = str(_uuid.uuid4())[:8]
    results: list[dict] = []
    context = req.task

    for spec in specs:
        sub_req = SpawnAgentRequest(
            task=context,
            specialization=spec,
            project=req.project,
            parent_run_id=orch_id,
        )
        result = spawn_agent(sub_req)
        results.append(result)
        # Feed this agent's output into the next agent's context
        context = f"Previous {spec} analysis:\n{result['response']}\n\nOriginal task: {req.task}"

    return {
        "orchestration_id": orch_id,
        "task": req.task,
        "agents_used": specs,
        "results": results,
        "final_response": results[-1]["response"] if results else "",
    }


@app.get("/agents/{run_id}")
def get_agent_run(run_id: str) -> dict:
    """Return details for a specific agent run."""
    if run_id not in _agent_runs:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Agent run '{run_id}' not found")
    return _agent_runs[run_id]


if __name__ == "__main__":
    host = _config.get("server.host", "127.0.0.1")
    port = int(_config.get("server.port", 8001))
    logger.info("Starting Arbiter Engine at http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
