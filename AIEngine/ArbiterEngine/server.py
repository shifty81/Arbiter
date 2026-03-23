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
import signal
import sqlite3
import subprocess
import platform
import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# ── Ensure local packages are importable ─────────────────────────────────────
_BASE = Path(__file__).resolve().parent
_BRIDGE_DIR = _BASE.parent / "PythonBridge"
sys.path.insert(0, str(_BASE))
if _BRIDGE_DIR.is_dir():
    sys.path.insert(1, str(_BRIDGE_DIR))

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
from core.self_build import SelfBuildLoop, SelfBuildController

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

# ── Archive & Library managers (M3 — Living Knowledge Codex) ─────────────────
try:
    from archive_manager import ArchiveManager as _ArchiveManager
    from library_manager import LibraryManager as _LibraryManager
    _library = _LibraryManager()
    _archive = _ArchiveManager()
    _archive.start_watcher(_library)
    _HAS_ARCHIVE = True
except Exception as _arc_exc:  # pragma: no cover – optional dependency
    logger.warning("Archive/Library managers unavailable: %s", _arc_exc)
    _library = None  # type: ignore[assignment]
    _archive = None  # type: ignore[assignment]
    _HAS_ARCHIVE = False

# ── Self-build loop state (M2-14, M7) ─────────────────────────────────────────
import asyncio as _asyncio
import threading as _threading_sb

_self_build_controller: SelfBuildController | None = None
_self_build_loop: SelfBuildLoop | None = None           # kept for backward compat
_self_build_task: "_asyncio.Task[Any] | None" = None
_self_build_log: list[str] = []
_self_build_status: str = "idle"           # idle | running | paused | done | error
_self_build_pending_approval: dict[str, Any] | None = None   # patch waiting for approve/reject
_self_build_lock = _threading_sb.Lock()
_ROADMAP_FILE = _BASE.parent.parent / "roadmap.json"  # repo root roadmap

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

# ── Session snapshot (persists chat histories + personas across restarts) ─────
_SNAPSHOT_FILE = _BASE / "logs" / "session_snapshot.json"


def _load_snapshot() -> None:
    """Load persisted chat histories and active personas from the snapshot file."""
    global _chat_histories, _active_personas
    if not _SNAPSHOT_FILE.is_file():
        return
    try:
        data = json.loads(_SNAPSHOT_FILE.read_text(encoding="utf-8"))
        _chat_histories = data.get("chat_histories", {})
        _active_personas = data.get("active_personas", {})
        logger.info("Loaded session snapshot (%d projects)", len(_chat_histories))
    except Exception as exc:
        logger.warning("Could not load session snapshot: %s", exc)


def _save_snapshot() -> None:
    """Flush chat histories and active personas to the snapshot file."""
    try:
        _SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "chat_histories": _chat_histories,
            "active_personas": _active_personas,
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        # Write atomically: write to a .tmp then rename so a crash mid-write
        # never produces a truncated file.
        tmp = _SNAPSHOT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_SNAPSHOT_FILE)
        logger.info("Session snapshot saved (%d projects)", len(_chat_histories))
    except Exception as exc:
        logger.error("Could not save session snapshot: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load snapshot.  Shutdown: flush snapshot."""
    _load_snapshot()
    try:
        yield
    finally:
        _save_snapshot()


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Arbiter Engine", version="0.2.0", lifespan=lifespan)
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


# ── M2-12: Module installation and validation ──────────────────────────────────

class ModuleInstallRequest(BaseModel):
    force: bool = False  # overwrite existing modules directory


@app.post("/modules/install")
def modules_install(req: ModuleInstallRequest) -> dict:
    """Run setup_modules.py to fetch the 42-module toolset from SwissAgent.

    Runs the script in a subprocess so the API server stays responsive.
    """
    setup_script = _BASE.parent / "setup_modules.py"
    if not setup_script.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="setup_modules.py not found")

    modules_dir = _BASE / "modules"
    if not req.force and modules_dir.exists() and any(modules_dir.iterdir()):
        return {
            "status": "already_installed",
            "module_count": sum(1 for p in modules_dir.iterdir() if p.is_dir()),
            "detail": "Modules already present. Use force=true to reinstall.",
        }

    try:
        # Pass --force flag via environment variable since setup_modules.py
        # uses interactive input; we bypass it by patching stdin.
        import io
        proc = subprocess.Popen(
            [sys.executable, str(setup_script)],
            cwd=str(_BASE.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate(input="y\n", timeout=120)
        success = proc.returncode == 0
        module_count = sum(1 for p in modules_dir.iterdir() if p.is_dir()) if modules_dir.exists() else 0
        if success:
            # Reload modules into the registry
            ModuleLoader(modules_dir, _registry).load_all()
        return {
            "status": "ok" if success else "error",
            "module_count": module_count,
            "output": (stdout + stderr).strip()[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "detail": "Module installation timed out (120 s)"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/modules/validate")
def modules_validate() -> dict:
    """Check which modules are installed and whether they load correctly."""
    modules_dir = _BASE / "modules"
    if not modules_dir.exists():
        return {"status": "missing", "modules": [], "total": 0}

    results: list[dict[str, Any]] = []
    for mod_dir in sorted(modules_dir.iterdir()):
        if not mod_dir.is_dir():
            continue
        manifest = mod_dir / "module.json"
        has_manifest = manifest.is_file()
        entry: dict[str, Any] = {
            "name": mod_dir.name,
            "path": str(mod_dir),
            "has_manifest": has_manifest,
        }
        if has_manifest:
            try:
                meta = json.loads(manifest.read_text(encoding="utf-8"))
                entry["version"] = meta.get("version", "unknown")
                entry["description"] = meta.get("description", "")
                entry["tools"] = len(meta.get("tools", []))
                entry["status"] = "ok"
            except Exception as exc:
                entry["status"] = "manifest_error"
                entry["error"] = str(exc)
        else:
            entry["status"] = "no_manifest"
        results.append(entry)

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    return {
        "status": "ok",
        "total": len(results),
        "valid": ok_count,
        "invalid": len(results) - ok_count,
        "modules": results,
        "registry_tools": len(_registry.list_tools()),
    }


@app.get("/modules")
def modules_list() -> dict:
    """List all loaded tools from all modules."""
    return {
        "tools": _registry.list_tools(),
        "total": len(_registry.list_tools()),
    }

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


# ═════════════════════════════════════════════════════════════════════════════
#  M2-14 / M7-11: Self-Build REST API
#  Exposes: /self-build/start, /stop, /status, /approve, /reject, /log
# ═════════════════════════════════════════════════════════════════════════════

class SelfBuildStartRequest(BaseModel):
    task_id: str = ""   # empty = pick next pending task from roadmap
    mode: str = "assist"  # manual | assist | semiauto | fullauto


class SelfBuildApproveRequest(BaseModel):
    approved: bool = True


def _sb_emit(msg: str) -> None:
    """Append a line to the in-memory self-build log."""
    global _self_build_log
    with _self_build_lock:
        _self_build_log.append(msg.rstrip())
        if len(_self_build_log) > 2000:
            _self_build_log = _self_build_log[-2000:]


@app.get("/self-build/status")
def self_build_status() -> dict:
    """Return the current self-build loop status."""
    with _self_build_lock:
        return {
            "status": _self_build_status,
            "pending_approval": _self_build_pending_approval is not None,
            "log_lines": len(_self_build_log),
        }


@app.get("/self-build/log")
def self_build_log(tail: int = 100) -> dict:
    """Return the most recent self-build log lines."""
    with _self_build_lock:
        lines = _self_build_log[-max(1, tail):]
    return {"lines": lines}


@app.post("/self-build/start")
async def self_build_start(req: SelfBuildStartRequest) -> dict:
    """Start (or resume) the autonomous self-build loop.

    ``mode`` controls autonomy level (M7-2):
    - ``manual``   – returns the next task description; takes no action.
    - ``assist``   – generates code changes and waits for approval before applying.
    - ``semiauto`` – applies changes, waits for approval before committing.
    - ``fullauto`` – plans, codes, tests, and commits without human approval.
    """
    global _self_build_status, _self_build_log, _self_build_task
    global _self_build_controller, _self_build_loop

    if _self_build_status == "running":
        return {"status": "already_running"}

    if not _ROADMAP_FILE.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="roadmap.json not found")

    mode = req.mode.lower()
    if mode == "manual":
        # Manual mode: just return the next pending task (no code changes)
        from core.self_build import _roadmap_next
        task, ms = _roadmap_next(_ROADMAP_FILE)
        if task is None:
            return {"status": "complete", "message": "All roadmap tasks are done!"}
        return {
            "status": "ok",
            "mode": "manual",
            "next_task": task,
            "milestone": ms.get("title") if ms else None,
        }

    with _self_build_lock:
        _self_build_status = "running"
        _self_build_log = []

    # Use SelfBuildController for proper Assist/SemiAuto/FullAuto support
    _self_build_controller = SelfBuildController(
        base_dir=_BASE, llm=_llm, roadmap_file=_ROADMAP_FILE
    )
    # Also update legacy reference for any code that still uses _self_build_loop
    _self_build_loop = _self_build_controller  # type: ignore[assignment]

    async def _run_loop() -> None:
        global _self_build_status, _self_build_pending_approval
        try:
            result = await _self_build_controller.run_cycle(
                emit=_sb_emit,
                mode=mode,
                task_id=req.task_id or None,
            )
            with _self_build_lock:
                _self_build_status = "done" if result.get("status") == "success" else "error"
        except _asyncio.CancelledError:
            with _self_build_lock:
                _self_build_status = "idle"
        except Exception as exc:
            _sb_emit(f"❌ Self-build error: {exc}")
            with _self_build_lock:
                _self_build_status = "error"

    loop = _asyncio.get_event_loop()
    _self_build_task = loop.create_task(_run_loop())

    return {"status": "started", "mode": mode, "task_id": req.task_id or "auto"}


@app.post("/self-build/stop")
async def self_build_stop() -> dict:
    """Cancel the currently running self-build loop."""
    global _self_build_status, _self_build_task
    if _self_build_task and not _self_build_task.done():
        _self_build_task.cancel()
        _sb_emit("⏹ Self-build stopped by user.")
    with _self_build_lock:
        _self_build_status = "idle"
    return {"status": "stopped"}


@app.post("/self-build/approve")
def self_build_approve(req: SelfBuildApproveRequest) -> dict:
    """Approve or reject a pending self-build change (Assist / SemiAuto modes, M7-2)."""
    global _self_build_pending_approval
    # Delegate to the controller's approval mechanism if it is active
    if _self_build_controller is not None:
        _self_build_controller.set_approval(req.approved)
        action = "approved" if req.approved else "rejected"
        _sb_emit(f"{'✅' if req.approved else '❌'} Change {action} by user.")
        task_id = (_self_build_controller.pending_task or {}).get("task_id", "")
        return {"status": action, "task_id": task_id}

    # Legacy path: check old _self_build_pending_approval dict
    with _self_build_lock:
        pending = _self_build_pending_approval
        _self_build_pending_approval = None
    if pending is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No pending approval")
    action = "approved" if req.approved else "rejected"
    _sb_emit(f"{'✅' if req.approved else '❌'} Change {action} by user.")
    return {"status": action, "task_id": pending.get("task_id", "")}


@app.get("/self-build/roadmap")
def self_build_roadmap() -> dict:
    """Return the full roadmap with milestone and task status."""
    if not _ROADMAP_FILE.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="roadmap.json not found")
    try:
        data = json.loads(_ROADMAP_FILE.read_text(encoding="utf-8"))
        return data
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Could not read roadmap: {exc}")


@app.get("/self-build/next")
def self_build_next() -> dict:
    """Return the next pending task from the roadmap."""
    if not _ROADMAP_FILE.is_file():
        return {"task": None, "milestone": None}
    try:
        from core.self_build import _roadmap_next
        task, ms = _roadmap_next(_ROADMAP_FILE)
        return {
            "task": task,
            "milestone": {"id": ms.get("id"), "title": ms.get("title")} if ms else None,
        }
    except Exception:
        return {"task": None, "milestone": None}

import shutil as _shutil
import uuid as _uuid_mod
import threading as _threading
import tempfile as _tempfile
import difflib as _difflib

from fastapi import HTTPException as _HTTPException
from fastapi.responses import HTMLResponse as _HTMLResponse
from fastapi.staticfiles import StaticFiles as _StaticFiles

_GUI_DIR = _BASE.parent / "PythonBridge" / "gui"
if _GUI_DIR.is_dir():
    app.mount("/gui", _StaticFiles(directory=str(_GUI_DIR), html=True), name="gui")


@app.get("/", response_class=_HTMLResponse)
def root_redirect():
    """Redirect root to the Monaco IDE."""
    return _HTMLResponse(
        content='<meta http-equiv="refresh" content="0;url=/gui/index.html">',
        status_code=200,
    )


@app.get("/ide", response_class=_HTMLResponse)
def ide_redirect():
    """Convenience redirect: GET /ide → serve the Monaco IDE."""
    return _HTMLResponse(
        content='<meta http-equiv="refresh" content="0;url=/gui/index.html">',
        status_code=200,
    )


# ─── LLM status ──────────────────────────────────────────────────────────────

@app.get("/llm/status")
def llm_status() -> dict:
    """Return the current LLM backend reachability and model info."""
    reachable = False
    detail = ""
    try:
        import urllib.request
        base_url = _config.get("llm.ollama.base_url", "http://localhost:11434")
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3) as resp:
            data = json.loads(resp.read())
            models = [m.get("name", "") for m in data.get("models", [])]
            reachable = True
            detail = models[0] if models else "(no models pulled)"
    except Exception:
        detail = "Ollama not reachable — is it running?"
    return {
        "backend": _backend,
        "reachable": reachable,
        "detail": detail,
        "model": _config.get("llm.ollama.model", "llama3"),
    }


# ─── File management ─────────────────────────────────────────────────────────

_WORKSPACE_ROOT = _BASE / "workspace"
_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

_ALLOWED_ROOTS: dict[str, Path] = {
    "workspace": _BASE / "workspace",
    "projects":  _BASE.parent.parent / "Projects",
}


def _resolve_safe(rel_path: str) -> Path:
    """Return an absolute Path for *rel_path*, rejecting path traversal."""
    p = Path(rel_path)
    parts = p.parts
    root_name = parts[0].lower() if parts else ""
    root = _ALLOWED_ROOTS.get(root_name)
    if root is None:
        root = _ALLOWED_ROOTS["workspace"]
        resolved = (root / rel_path).resolve()
    else:
        rest = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        resolved = (root / rest).resolve()
    if not str(resolved).startswith(str(root.resolve())):
        raise _HTTPException(status_code=400, detail=f"Unsafe path: {rel_path}")
    return resolved


def _build_tree(directory: Path, base: Path, depth: int = 0, max_depth: int = 4) -> list:
    if depth > max_depth or not directory.is_dir():
        return []
    items = []
    try:
        for item in sorted(directory.iterdir()):
            if item.name.startswith("."):
                continue
            rel = str(item.relative_to(base))
            if item.is_dir():
                items.append({
                    "type": "dir", "name": item.name, "path": rel,
                    "children": _build_tree(item, base, depth + 1, max_depth),
                })
            else:
                items.append({"type": "file", "name": item.name, "path": rel,
                               "size": item.stat().st_size})
    except PermissionError:
        pass
    return items


_MAX_AI_CODE_CHARS    = 4000  # max code snippet forwarded to the LLM
_MAX_AI_CONTEXT_CHARS = 2000  # max context snippet forwarded to the LLM


def _run_cmd(command: str, cwd: Path, timeout: int = 120) -> dict:
    """Run a shell command (build/run/test) and return stdout/stderr/exit_code.

    Uses shell=True so that compound build commands (e.g. ``npm run build``,
    ``dotnet build``) work unchanged. Never pass unsanitised user-supplied text
    into this function — use ``_run_git_cmd`` for git operations instead.
    """
    try:
        proc = subprocess.run(
            command, shell=True, cwd=str(cwd),
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "stdout": proc.stdout, "stderr": proc.stderr,
            "exit_code": proc.returncode, "success": proc.returncode == 0,
            "output": proc.stdout or proc.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Timed out after {timeout}s.",
                "exit_code": -1, "success": False, "output": f"Timed out after {timeout}s."}


def _run_git_cmd(args: list[str], cwd: Path, timeout: int = 30) -> dict:
    """Run a git sub-command using an argument list (no shell expansion).

    Prefixes ``args`` with ``["git"]`` automatically.
    """
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=str(cwd),
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "stdout": proc.stdout, "stderr": proc.stderr,
            "exit_code": proc.returncode, "success": proc.returncode == 0,
            "output": proc.stdout or proc.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"git timed out after {timeout}s.",
                "exit_code": -1, "success": False, "output": f"git timed out after {timeout}s."}


@app.get("/files")
def files_tree(path: str = "workspace") -> dict:
    root_name = Path(path).parts[0].lower() if Path(path).parts else "workspace"
    root = _ALLOWED_ROOTS.get(root_name, _ALLOWED_ROOTS["workspace"])
    root.mkdir(parents=True, exist_ok=True)
    return {"tree": _build_tree(root, root), "root": path}


@app.get("/files/read")
def files_read(path: str) -> dict:
    fp = _resolve_safe(path)
    if not fp.is_file():
        raise _HTTPException(status_code=404, detail=f"File not found: {path}")
    content = fp.read_text(encoding="utf-8", errors="replace")
    return {"path": path, "content": content}


class _FileWriteReq(BaseModel):
    path: str
    content: str


@app.post("/files/write")
def files_write(req: _FileWriteReq) -> dict:
    fp = _resolve_safe(req.path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(req.content, encoding="utf-8")
    return {"path": req.path, "ok": True}


class _FileDeleteReq(BaseModel):
    path: str


@app.post("/files/delete")
def files_delete(req: _FileDeleteReq) -> dict:
    fp = _resolve_safe(req.path)
    if fp.is_file():
        fp.unlink()
    elif fp.is_dir():
        _shutil.rmtree(fp)
    else:
        raise _HTTPException(status_code=404, detail=f"Not found: {req.path}")
    return {"path": req.path, "ok": True}


class _FileRenameReq(BaseModel):
    path: str
    new_path: str


@app.post("/files/rename")
def files_rename(req: _FileRenameReq) -> dict:
    src = _resolve_safe(req.path)
    dst = _resolve_safe(req.new_path)
    if not src.exists():
        raise _HTTPException(status_code=404, detail=f"Source not found: {req.path}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"path": req.new_path, "ok": True}


@app.get("/files/scan")
def files_scan(path: str = "workspace") -> dict:
    root_name = Path(path).parts[0].lower() if Path(path).parts else "workspace"
    root = _ALLOWED_ROOTS.get(root_name, _ALLOWED_ROOTS["workspace"])
    if not root.is_dir():
        return {"path": path, "files": []}
    files = [
        str(f.relative_to(root))
        for f in root.rglob("*")
        if f.is_file() and not f.name.startswith(".")
    ]
    return {"path": path, "files": files}


class _FileImportReq(BaseModel):
    source: str
    dest: str = "workspace"


@app.post("/files/import")
def files_import(req: _FileImportReq) -> dict:
    src = Path(req.source)
    if not src.exists():
        raise _HTTPException(status_code=404, detail=f"Source not found: {req.source}")
    root_name = Path(req.dest).parts[0].lower() if Path(req.dest).parts else "workspace"
    dest_root = _ALLOWED_ROOTS.get(root_name, _ALLOWED_ROOTS["workspace"])
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / src.name
    if src.is_dir():
        _shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        _shutil.copy2(src, dest)
    return {"dest": str(dest.relative_to(_BASE.parent.parent)), "ok": True}


# ─── IDE native tool-call bridge ─────────────────────────────────────────────

_ide_queue: list = []
_ide_queue_lock = _threading.Lock()
_ide_results: dict = {}


@app.get("/api/ide/pending")
def ide_pending() -> dict:
    """Return and clear all pending native tool calls for the WPF host."""
    with _ide_queue_lock:
        items = list(_ide_queue)
        _ide_queue.clear()
    return {"calls": items}


class _IdeCommandReq(BaseModel):
    type: str
    payload: dict = {}


@app.post("/api/ide/command")
def ide_command(req: _IdeCommandReq) -> dict:
    """Queue a native command for the WPF host to execute."""
    call_id = str(_uuid_mod.uuid4())[:8]
    with _ide_queue_lock:
        _ide_queue.append({"id": call_id, "type": req.type, "payload": req.payload})
    return {"status": "queued", "call_id": call_id}


class _IdeResultReq(BaseModel):
    call_id: str
    result: dict = {}


@app.post("/api/ide/complete")
def ide_complete(req: _IdeResultReq) -> dict:
    """Receive the result of a native tool call from the WPF host."""
    _ide_results[req.call_id] = req.result
    return {"status": "ok", "call_id": req.call_id}


@app.get("/api/ide/result/{call_id}")
def ide_result(call_id: str) -> dict:
    """Poll for the result of a specific native call."""
    result = _ide_results.pop(call_id, None)
    if result is None:
        return {"status": "pending"}
    return {"status": "ready", "result": result}


# ─── Git endpoints ────────────────────────────────────────────────────────────

class _GitCloneReq(BaseModel):
    url: str
    dest: str = "workspace"
    branch: str = ""


@app.post("/git/clone")
def git_clone(req: _GitCloneReq) -> dict:
    dest_root = _ALLOWED_ROOTS.get(
        Path(req.dest).parts[0].lower() if Path(req.dest).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    dest_root.mkdir(parents=True, exist_ok=True)
    git_args = ["clone"]
    if req.branch:
        git_args += ["--branch", req.branch]
    git_args.append(req.url)
    return _run_git_cmd(git_args, dest_root, timeout=120)


@app.get("/git/status")
def git_status_ep(path: str = "workspace") -> dict:
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    r = _run_git_cmd(["status", "--short"], root, timeout=10)
    lines = (r.get("stdout") or "").splitlines()
    staged    = [ln[3:] for ln in lines if ln[:2] in ("A ", "M ", "D ")]
    unstaged  = [ln[3:] for ln in lines if ln[:1] == " " and ln[1:2] in ("M", "D")]
    untracked = [ln[3:] for ln in lines if ln[:2] == "??"]
    branch_r  = _run_git_cmd(["branch", "--show-current"], root, timeout=5)
    branch    = (branch_r.get("stdout") or "").strip() or "unknown"
    return {"branch": branch, "staged": staged, "unstaged": unstaged, "untracked": untracked}


class _GitStageReq(BaseModel):
    files: list
    project: str = "workspace"


@app.post("/git/stage")
def git_stage(req: _GitStageReq) -> dict:
    root = _ALLOWED_ROOTS.get(
        Path(req.project).parts[0].lower() if Path(req.project).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    safe_files = [str(f) for f in req.files[:50]]
    return _run_git_cmd(["add", "--"] + safe_files, root, timeout=15)


class _GitCommitReq(BaseModel):
    message: str
    project: str = "workspace"


@app.post("/git/commit")
def git_commit_ep(req: _GitCommitReq) -> dict:
    root = _ALLOWED_ROOTS.get(
        Path(req.project).parts[0].lower() if Path(req.project).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    return _run_git_cmd(["commit", "-m", req.message], root, timeout=15)


@app.get("/git/log")
def git_log(path: str = "workspace", limit: int = 20) -> dict:
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    r = _run_git_cmd(["log", "--oneline", f"-n{min(limit, 100)}"], root, timeout=10)
    commits = []
    for line in (r.get("stdout") or "").splitlines():
        if " " in line:
            sha, _, msg = line.partition(" ")
            commits.append({"sha": sha, "message": msg})
    return {"commits": commits}


@app.get("/git/diff")
def git_diff(path: str = "workspace", file: str = "") -> dict:
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    git_args = ["diff"]
    if file:
        git_args += ["--", file]
    r = _run_git_cmd(git_args, root, timeout=10)
    return {"diff": r.get("stdout", "")}


# ─── Project health / init ────────────────────────────────────────────────────

def _auto_detect_build_cmd(project_dir: Path, action: str) -> str:
    if (project_dir / "package.json").exists():
        return {"build": "npm run build", "run": "npm start", "test": "npm test"}.get(action, "")
    if list(project_dir.glob("*.csproj")) or list(project_dir.glob("*.sln")):
        return {"build": "dotnet build", "run": "dotnet run", "test": "dotnet test"}.get(action, "")
    if (project_dir / "Cargo.toml").exists():
        return {"build": "cargo build", "run": "cargo run", "test": "cargo test"}.get(action, "")
    if (project_dir / "pyproject.toml").exists() or (project_dir / "setup.py").exists():
        return {"build": "pip install -e .", "run": "python -m app", "test": "pytest"}.get(action, "")
    if (project_dir / "Makefile").exists():
        return {"build": "make", "run": "make run", "test": "make test"}.get(action, "")
    return ""


@app.get("/project/health")
def project_health(path: str = "workspace") -> dict:
    return {"status": "ok", "path": path}


@app.get("/project/init/detect")
def project_init_detect(path: str = "workspace") -> dict:
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    return {
        "build": _auto_detect_build_cmd(root, "build"),
        "run":   _auto_detect_build_cmd(root, "run"),
        "test":  _auto_detect_build_cmd(root, "test"),
        "path": path,
    }


@app.get("/project/init/scan")
def project_init_scan(path: str = "workspace") -> dict:
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    if not root.is_dir():
        return {"languages": [], "extensions": {}}
    exts: dict = {}
    for f in root.rglob("*"):
        if f.is_file():
            exts[f.suffix] = exts.get(f.suffix, 0) + 1
    return {"extensions": exts, "path": path}


@app.post("/project/init")
def project_init(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


# ─── Build detection ──────────────────────────────────────────────────────────

@app.get("/build/detect")
def build_detect(path: str = "workspace") -> dict:
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    return {
        "build": _auto_detect_build_cmd(root, "build") or None,
        "run":   _auto_detect_build_cmd(root, "run")   or None,
        "test":  _auto_detect_build_cmd(root, "test")  or None,
    }


# ─── Diff / Patch / Format / Lint ────────────────────────────────────────────

class _DiffReq(BaseModel):
    original: str
    modified: str


@app.post("/diff")
def compute_diff(req: _DiffReq) -> dict:
    diff = list(_difflib.unified_diff(
        req.original.splitlines(keepends=True),
        req.modified.splitlines(keepends=True),
        fromfile="original", tofile="modified",
    ))
    return {"diff": "".join(diff)}


class _PatchReq(BaseModel):
    patch: str
    path: str = "workspace"


@app.post("/patch")
def apply_patch(req: _PatchReq) -> dict:
    root = _ALLOWED_ROOTS.get(
        Path(req.path).parts[0].lower() if Path(req.path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    with _tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tf:
        tf.write(req.patch)
        pf = tf.name
    try:
        proc = subprocess.run(
            ["patch", "-p1", f"--input={pf}"],
            cwd=str(root), capture_output=True, text=True, timeout=30,
        )
        result = {
            "stdout": proc.stdout, "stderr": proc.stderr,
            "exit_code": proc.returncode, "success": proc.returncode == 0,
            "output": proc.stdout or proc.stderr,
        }
    except subprocess.TimeoutExpired:
        result = {"stdout": "", "stderr": "patch timed out.", "exit_code": -1,
                  "success": False, "output": "patch timed out."}
    finally:
        try:
            os.unlink(pf)
        except OSError:
            pass
    return result


class _FormatReq(BaseModel):
    code: str
    language: str = "python"


@app.post("/format")
def format_code(req: _FormatReq) -> dict:
    if req.language in ("python", "py"):
        try:
            import black
            formatted = black.format_str(req.code, mode=black.Mode())
            return {"code": formatted, "ok": True}
        except Exception as exc:
            return {"code": req.code, "ok": False, "error": str(exc)}
    return {"code": req.code, "ok": True}


class _LintReq(BaseModel):
    code: str
    language: str = "python"
    path: str = ""


@app.post("/lint")
def lint_code(req: _LintReq) -> dict:
    if req.language in ("python", "py"):
        tmp = ""
        try:
            with _tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
                tf.write(req.code)
                tmp = tf.name
            proc = subprocess.run(
                [sys.executable, "-m", "flake8", "--max-line-length=120", tmp],
                capture_output=True, text=True, timeout=15,
            )
            return {"issues": proc.stdout, "ok": proc.returncode == 0}
        except Exception as exc:
            return {"issues": str(exc), "ok": False}
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    return {"issues": "", "ok": True}


# ─── Scaffold / Templates stubs ───────────────────────────────────────────────

@app.post("/scaffold/module")
@app.post("/scaffold/plugin")
@app.post("/scaffold/tests")
def scaffold_stub(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok", "message": "Scaffold not yet implemented in ArbiterEngine mode."}


@app.get("/templates")
def list_templates() -> dict:
    return {"templates": []}


@app.post("/templates/apply")
def apply_template(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


# ─── Assistant / AI chat panel ────────────────────────────────────────────────

class _AssistantMsg(BaseModel):
    prompt: str
    project: str = "default"
    backend: str = ""
    context: str = ""
    mode: str = "chat"


@app.post("/assistant/chat")
def assistant_chat(msg: _AssistantMsg) -> dict:
    """Primary chat endpoint used by the Monaco IDE chat panel."""
    from core.agent import Agent
    history = _chat_histories.setdefault(msg.project, [])
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
            prompt=msg.prompt,
            project_path=msg.project,
            chat_history=history,
        )
    except Exception as exc:
        logger.error("assistant_chat error: %s", exc)
        response = f"[Arbiter Engine error] {exc}"
    history.append({"role": "user", "content": msg.prompt})
    history.append({"role": "assistant", "content": response})
    return {"response": response}


@app.post("/assistant/chat/agentic")
def assistant_chat_agentic(msg: _AssistantMsg) -> dict:
    """Agentic chat — delegates to the standard agent."""
    return assistant_chat(msg)


# ─── AI action / propose / timeline ──────────────────────────────────────────

class _AiActionReq(BaseModel):
    action: str = ""
    code: str = ""
    context: str = ""
    project: str = "default"


@app.post("/ai/action")
def ai_action(req: _AiActionReq) -> dict:
    prompt = f"Action: {req.action}\n\nCode:\n{req.code[:_MAX_AI_CODE_CHARS]}"
    if req.context:
        prompt += f"\n\nContext:\n{req.context[:_MAX_AI_CONTEXT_CHARS]}"
    from core.agent import Agent
    agent = Agent(llm=_llm, tool_registry=_registry, permission_system=_permissions,
                  task_runner=_runner, config=_config, project_path=req.project)
    try:
        response = agent.run(prompt=prompt, project_path=req.project)
    except Exception as exc:
        response = f"[Error] {exc}"
    return {"response": response}


@app.post("/ai/complete")
def ai_complete(req: _AiActionReq) -> dict:
    return ai_action(req)


@app.post("/ai/propose")
def ai_propose(req: _AiActionReq) -> dict:
    return ai_action(req)


@app.get("/ai/persona/active")
def ai_persona_active(project: str = "default") -> dict:
    return {"persona": _active_personas.get(project, "Arbiter")}


@app.get("/ai/backends")
def ai_backends() -> dict:
    available = []
    try:
        import urllib.request
        base_url = _config.get("llm.ollama.base_url", "http://localhost:11434")
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3) as resp:
            data = json.loads(resp.read())
            models = [m.get("name", "") for m in data.get("models", [])]
            for m in models:
                available.append({"name": "ollama", "model": m, "available": True})
    except Exception:
        available.append({"name": "ollama", "model": _config.get("llm.ollama.model", "llama3"),
                          "available": False})
    return {"backends": available, "active": _backend}


@app.post("/ai/backends/switch")
@app.post("/ai/backends/configure")
@app.post("/ai/backends/test")
def ai_backend_stub(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/ai/timeline")
def ai_timeline(limit: int = 100) -> dict:
    return {"events": []}


@app.post("/ai/timeline/clear")
def ai_timeline_clear() -> dict:
    return {"status": "ok"}


# ─── Misc stubs (panels that poll these endpoints) ───────────────────────────

@app.get("/stats")
def stats() -> dict:
    return {"requests": 0, "errors": 0, "uptime_s": 0}


@app.get("/profile")
def profile() -> dict:
    return {"name": "default", "theme": "dark"}


@app.get("/config/active")
@app.get("/config/profile")
def config_active() -> dict:
    return {"profile": "default"}


@app.get("/config/profiles")
def config_profiles() -> dict:
    return {"profiles": ["default"]}


@app.post("/config/profile")
def config_profile_set(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/toolchain")
def toolchain() -> dict:
    return {"tools": []}


@app.get("/notifications")
def notifications() -> dict:
    return {"notifications": []}


@app.post("/notifications/clear")
@app.post("/notifications/mark-read")
def notifications_modify(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/notify")
def notify(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/flags")
def flags() -> dict:
    return {"flags": {}}


@app.post("/flags/flag")
def flag(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/archive")
def archive_list() -> dict:
    """Return all archive entries."""
    if not _HAS_ARCHIVE or _archive is None:
        return {"count": 0, "entries": []}
    entries = _archive.entries
    return {
        "count": len(entries),
        "entries": [
            {
                "id": e.id,
                "title": e.title,
                "summary": e.summary,
                "language": e.language,
                "entry_type": e.entry_type,
                "source_file": e.source_file,
                "tags": e.tags,
                "indexed_at": e.indexed_at,
            }
            for e in entries
        ],
    }


@app.post("/archive/rebuild")
def archive_rebuild() -> dict:
    """Full rebuild — re-index all library files."""
    if not _HAS_ARCHIVE or _archive is None or _library is None:
        return {"status": "not_available", "entries": 0}
    count = _archive.rebuild(_library)
    return {"status": "rebuilt", "entries": count}


class _ArchiveSearchReq(BaseModel):
    query: str = ""
    top_k: int = 10


@app.get("/archive/search")
def archive_search(q: str = "") -> dict:
    """Search archive entries by keyword relevance (GET convenience)."""
    if not _HAS_ARCHIVE or _archive is None:
        return {"results": []}
    results = _archive.search(q, top_k=10)
    return {
        "query": q,
        "results": [
            {
                "id": e.id,
                "title": e.title,
                "summary": e.summary,
                "content_snippet": e.content[:300],
                "language": e.language,
                "entry_type": e.entry_type,
                "source_file": e.source_file,
                "tags": e.tags,
            }
            for e in results
        ],
    }


@app.post("/archive/search")
def archive_search_post(req: _ArchiveSearchReq) -> dict:
    """Search archive entries by keyword relevance."""
    if not _HAS_ARCHIVE or _archive is None:
        return {"results": []}
    results = _archive.search(req.query, top_k=req.top_k)
    return {
        "query": req.query,
        "results": [
            {
                "id": e.id,
                "title": e.title,
                "summary": e.summary,
                "content_snippet": e.content[:300],
                "language": e.language,
                "entry_type": e.entry_type,
                "source_file": e.source_file,
                "tags": e.tags,
            }
            for e in results
        ],
    }


@app.get("/archive/entry/{entry_id}")
def archive_entry(entry_id: str) -> dict:
    """Return full content of a single archive entry."""
    if not _HAS_ARCHIVE or _archive is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Archive not available")
    entry = next((e for e in _archive.entries if e.id == entry_id), None)
    if entry is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Archive entry not found")
    return {
        "id": entry.id,
        "title": entry.title,
        "summary": entry.summary,
        "content": entry.content,
        "language": entry.language,
        "entry_type": entry.entry_type,
        "source_file": entry.source_file,
        "library_id": entry.library_id,
        "tags": entry.tags,
        "indexed_at": entry.indexed_at,
    }


@app.delete("/archive/entry/{entry_id}")
def archive_delete_entry(entry_id: str) -> dict:
    """Remove a single entry from the archive."""
    if not _HAS_ARCHIVE or _archive is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Archive not available")
    removed = _archive.delete_entry(entry_id)
    if not removed:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Archive entry not found")
    return {"status": "removed"}


@app.get("/archive/export")
def archive_export() -> dict:
    """Export the full archive as a Markdown codex document."""
    if not _HAS_ARCHIVE or _archive is None:
        return {"content": ""}
    return {"content": _archive.export_markdown()}


@app.get("/metrics")
def metrics() -> dict:
    return {"metrics": {}}


@app.get("/metrics/alerts")
def metrics_alerts() -> dict:
    return {"alerts": []}


@app.post("/metrics/alert")
def metrics_alert(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/rules")
def rules() -> dict:
    return {"rules": []}


@app.get("/snippets")
def snippets() -> dict:
    return {"snippets": []}


@app.post("/snippet")
def snippet_create(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/snippet/run")
def snippet_run(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok", "output": ""}


@app.get("/notes")
def notes() -> dict:
    return {"notes": []}


@app.post("/notes")
def notes_create(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/tasks")
def tasks_list() -> dict:
    return {"tasks": []}


@app.get("/events/history")
def events_history() -> dict:
    return {"events": []}


@app.post("/events/publish")
def events_publish(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/events/subscribe")
def events_subscribe(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/events/subscriptions")
def events_subscriptions() -> dict:
    return {"subscriptions": []}


@app.get("/roadmap/next")
def roadmap_next() -> dict:
    """Return the next pending task from the repo-root roadmap.json."""
    if not _ROADMAP_FILE.is_file():
        return {"task": None, "milestone": None}
    try:
        from core.self_build import _roadmap_next
        task, ms = _roadmap_next(_ROADMAP_FILE)
        return {
            "task": task,
            "milestone": {"id": ms.get("id"), "title": ms.get("title")} if ms else None,
        }
    except Exception:
        return {"task": None, "milestone": None}


@app.get("/knowledge/fetch")
def knowledge_fetch(q: str = "") -> dict:
    return {"results": []}


@app.post("/knowledge/fetch")
def knowledge_fetch_post(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"results": []}


@app.post("/knowledge/remove")
def knowledge_remove(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/library")
def library_list() -> dict:
    """Return all registered library paths."""
    if not _HAS_ARCHIVE or _library is None:
        return {"paths": []}
    return {"paths": _library.list_paths()}


class _LibraryAddReq(BaseModel):
    path: str
    label: str = ""
    extensions: list[str] = []


@app.post("/library")
def library_add(req: _LibraryAddReq) -> dict:
    """Add a filesystem path to the library."""
    if not _HAS_ARCHIVE or _library is None:
        return {"status": "not_available"}
    entry = _library.add_path(req.path, label=req.label, extensions=req.extensions or None)
    return {"status": "added", "entry": entry}


@app.delete("/library/{path_id}")
def library_remove(path_id: str) -> dict:
    """Remove a library path by ID or exact path."""
    if not _HAS_ARCHIVE or _library is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Library not available")
    removed = _library.remove_path(path_id)
    if not removed:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Library path not found")
    return {"status": "removed"}


@app.get("/library/{path_id}/files")
def library_files(path_id: str) -> dict:
    """List all indexable files under a library path."""
    if not _HAS_ARCHIVE or _library is None:
        return {"files": []}
    files = _library.list_files(path_id)
    return {"files": files}


@app.get("/library/{path_id}/file")
def library_read_file(path_id: str, path: str) -> dict:
    """Read a single file from a library path (query param: path)."""
    if not _HAS_ARCHIVE or _library is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Library not available")
    content = _library.read_file(path_id, path)
    if content is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": content}


@app.post("/refactor/find-replace")
@app.post("/refactor/rename")
def refactor_stub(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok", "changes": []}


@app.post("/brainstorm/session")
def brainstorm_session(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"session_id": str(_uuid_mod.uuid4())[:8], "ideas": []}


@app.get("/brainstorm/sessions")
def brainstorm_sessions() -> dict:
    return {"sessions": []}


@app.post("/docgen/generate")
def docgen_generate(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"documentation": ""}


@app.get("/docgen/history")
def docgen_history(limit: int = 20) -> dict:
    return {"history": []}


@app.get("/apiclient/collections")
def apiclient_collections() -> dict:
    return {"collections": []}


@app.get("/apiclient/collection/{name}")
def apiclient_collection(name: str) -> dict:
    return {"name": name, "requests": []}


@app.post("/apiclient/collection")
def apiclient_collection_create(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/apiclient/collection/{name}/request")
def apiclient_request_create(name: str, req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/apiclient/send")
def apiclient_send(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": 0, "body": "", "headers": {}}


@app.get("/queue/stats")
def queue_stats() -> dict:
    return {"pending": 0, "running": 0, "done": 0}


@app.get("/queue/tasks")
def queue_tasks() -> dict:
    return {"tasks": []}


@app.post("/queue/task")
def queue_task(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"task_id": str(_uuid_mod.uuid4())[:8]}


@app.get("/ratelimit/status")
def ratelimit_status() -> dict:
    return {"limited": False}


@app.get("/ratelimit/rules")
def ratelimit_rules() -> dict:
    return {"rules": []}


@app.post("/ratelimit/rule")
def ratelimit_rule(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/deps/reports")
def deps_reports(limit: int = 10) -> dict:
    return {"reports": []}


@app.post("/deps/analyze")
def deps_analyze(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok", "dependencies": []}


@app.get("/env/files")
def env_files() -> dict:
    return {"files": []}


@app.post("/env/var")
def env_var_set(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/env/import")
def env_import(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/vault/keys")
def vault_keys() -> dict:
    return {"keys": []}


@app.post("/vault/set")
def vault_set(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/vault/export")
def vault_export(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/webhooks")
@app.get("/webhook/deliveries")
def webhooks_list() -> dict:
    return {"webhooks": []}


@app.post("/webhook/register")
def webhook_register(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/docker/containers")
def docker_containers() -> dict:
    return {"containers": []}


@app.post("/docker/build")
@app.post("/docker/run")
def docker_stub(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok", "output": ""}


@app.get("/ci/runs")
def ci_runs() -> dict:
    return {"runs": []}


@app.post("/ci/run")
def ci_run(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/deploy/configs")
@app.get("/deploy/history")
def deploy_list() -> dict:
    return {"items": []}


@app.post("/deploy/config")
def deploy_config(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/deploy/run")
def deploy_run(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/db/connections")
def db_connections() -> dict:
    return {"connections": []}


@app.post("/db/connect")
def db_connect(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/db/query")
def db_query(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"rows": [], "columns": []}


@app.get("/cron/jobs")
@app.get("/cron/history")
def cron_list() -> dict:
    return {"items": []}


@app.post("/cron/job")
def cron_job(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.get("/terminal/sessions")
def terminal_sessions() -> dict:
    return {"sessions": []}


@app.post("/terminal/session")
def terminal_session(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"session_id": str(_uuid_mod.uuid4())[:8]}


@app.get("/testrunner/reports")
def testrunner_reports(limit: int = 20) -> dict:
    return {"reports": []}


@app.post("/testrunner/run")
def testrunner_run(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


# ─── Graceful shutdown ────────────────────────────────────────────────────────

@app.post("/shutdown")
def shutdown_server() -> dict:
    """Save all session data then ask uvicorn to exit cleanly."""
    _save_snapshot()
    import threading

    def _stop() -> None:
        import time
        time.sleep(0.3)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_stop, daemon=True).start()
    return {"status": "shutting_down"}


if __name__ == "__main__":
    host = _config.get("server.host", "127.0.0.1")
    port = int(_config.get("server.port", 8001))
    logger.info("Starting Arbiter Engine at http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
