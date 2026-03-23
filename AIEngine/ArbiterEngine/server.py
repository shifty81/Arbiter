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


# ═════════════════════════════════════════════════════════════════════════════
#  M9-1: Scaffold system — generate boilerplate modules, plugins, and tests
# ─────────────────────────────────────────────────────────────────────────────
import re as _re

_SCAFFOLD_TEMPLATES: dict[str, dict[str, str]] = {
    "module": {
        "python": (
            '"""{{name}} module.\n\nAdd module description here.\n"""\nfrom __future__ import annotations\n\n\n'
            "def {{name}}_action(param: str) -> str:\n"
            '    """Perform the primary action for {{name}}.\n\n    Args:\n        param: Input parameter.\n\n'
            '    Returns:\n        Result string.\n    """\n    return param\n'
        ),
        "csharp": (
            "using System;\n\nnamespace Arbiter.{{Name}}\n{\n"
            "    /// <summary>{{Name}} module.</summary>\n"
            "    public class {{Name}}\n    {\n"
            "        public string Execute(string param)\n        {\n"
            '            return param;\n        }\n    }\n}\n'
        ),
    },
    "plugin": {
        "python": (
            '"""{{name}} plugin for Arbiter Engine.\n\nRegister tools by calling registry.register() below.\n"""\n'
            "from __future__ import annotations\n"
            "from core.tool_registry import ToolRegistry\n\n\n"
            "def register(registry: ToolRegistry) -> None:\n"
            '    """Register all tools provided by this plugin."""\n\n'
            "    def {{name}}_tool(param: str) -> str:\n"
            '        """{{name}} tool — replace with real implementation."""\n'
            "        return param\n\n"
            '    registry.register("{{name}}", {{name}}_tool)\n'
        ),
    },
    "tests": {
        "python": (
            '"""Tests for {{name}}."""\nfrom __future__ import annotations\nimport pytest\n\n\n'
            "class Test{{Name}}:\n"
            "    def test_placeholder(self) -> None:\n"
            '        """Replace with real test."""\n        assert True\n'
        ),
        "csharp": (
            "using Xunit;\n\nnamespace Arbiter.Tests\n{\n"
            "    public class {{Name}}Tests\n    {\n"
            "        [Fact]\n        public void Placeholder()\n        {\n"
            "            Assert.True(true);\n        }\n    }\n}\n"
        ),
    },
}


def _render_scaffold(template: str, name: str) -> str:
    """Substitute {{name}} and {{Name}} placeholders."""
    pascal = "".join(w.capitalize() for w in _re.split(r"[\W_]+", name) if w)
    return template.replace("{{name}}", name).replace("{{Name}}", pascal)


class _ScaffoldRequest(BaseModel):
    name: str
    language: str = "python"
    output_path: str = ""


@app.post("/scaffold/module")
def scaffold_module(req: _ScaffoldRequest) -> dict:
    """Generate a boilerplate module file (M9-1)."""
    kind = "module"
    lang_templates = _SCAFFOLD_TEMPLATES.get(kind, {})
    lang = req.language.lower()
    tpl = lang_templates.get(lang) or next(iter(lang_templates.values()), "")
    if not tpl:
        return {"status": "error", "detail": f"No template for language '{req.language}'"}
    code = _render_scaffold(tpl, req.name)
    ext = {"python": "py", "csharp": "cs"}.get(lang, "txt")
    filename = req.output_path or f"{req.name}.{ext}"
    if req.output_path:
        try:
            Path(req.output_path).write_text(code, encoding="utf-8")
        except OSError as exc:
            return {"status": "error", "detail": str(exc)}
    return {"status": "ok", "filename": filename, "code": code, "language": lang}


@app.post("/scaffold/plugin")
def scaffold_plugin(req: _ScaffoldRequest) -> dict:
    """Generate a boilerplate Arbiter plugin file (M9-1)."""
    kind = "plugin"
    lang_templates = _SCAFFOLD_TEMPLATES.get(kind, {})
    lang = req.language.lower()
    tpl = lang_templates.get(lang) or next(iter(lang_templates.values()), "")
    if not tpl:
        return {"status": "error", "detail": f"No template for language '{req.language}'"}
    code = _render_scaffold(tpl, req.name)
    filename = req.output_path or f"{req.name}_plugin.py"
    if req.output_path:
        try:
            Path(req.output_path).write_text(code, encoding="utf-8")
        except OSError as exc:
            return {"status": "error", "detail": str(exc)}
    return {"status": "ok", "filename": filename, "code": code, "language": lang}


@app.post("/scaffold/tests")
def scaffold_tests(req: _ScaffoldRequest) -> dict:
    """Generate a boilerplate test file (M9-1)."""
    kind = "tests"
    lang_templates = _SCAFFOLD_TEMPLATES.get(kind, {})
    lang = req.language.lower()
    tpl = lang_templates.get(lang) or next(iter(lang_templates.values()), "")
    if not tpl:
        return {"status": "error", "detail": f"No template for language '{req.language}'"}
    code = _render_scaffold(tpl, req.name)
    ext = {"python": "py", "csharp": "cs"}.get(lang, "txt")
    filename = req.output_path or f"test_{req.name}.{ext}"
    if req.output_path:
        try:
            Path(req.output_path).write_text(code, encoding="utf-8")
        except OSError as exc:
            return {"status": "error", "detail": str(exc)}
    return {"status": "ok", "filename": filename, "code": code, "language": lang}


@app.get("/templates")
def list_templates() -> dict:
    """List available scaffold templates (M9-1)."""
    items = []
    for kind, langs in _SCAFFOLD_TEMPLATES.items():
        for lang in langs:
            items.append({"type": kind, "language": lang})
    return {"templates": items}


class _TemplateApplyRequest(BaseModel):
    type: str
    name: str
    language: str = "python"
    output_path: str = ""


@app.post("/templates/apply")
def apply_template(req: _TemplateApplyRequest) -> dict:
    """Apply a named scaffold template (M9-1)."""
    lang_templates = _SCAFFOLD_TEMPLATES.get(req.type, {})
    lang = req.language.lower()
    tpl = lang_templates.get(lang) or next(iter(lang_templates.values()), "")
    if not tpl:
        return {"status": "error", "detail": f"Template '{req.type}/{req.language}' not found"}
    code = _render_scaffold(tpl, req.name)
    if req.output_path:
        try:
            Path(req.output_path).write_text(code, encoding="utf-8")
        except OSError as exc:
            return {"status": "error", "detail": str(exc)}
    return {"status": "ok", "code": code}


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


# ═════════════════════════════════════════════════════════════════════════════
#  M9-3: Code Refactoring Engine — rename symbols, find-replace across project
# ─────────────────────────────────────────────────────────────────────────────

class _FindReplaceRequest(BaseModel):
    project: str = "default"
    find: str
    replace: str
    file_pattern: str = "*"
    case_sensitive: bool = True
    whole_word: bool = False


class _RenameRequest(BaseModel):
    project: str = "default"
    old_name: str
    new_name: str
    file_pattern: str = "*.py"


@app.post("/refactor/find-replace")
def refactor_find_replace(req: _FindReplaceRequest) -> dict:
    """Find and replace text across all project files (M9-3)."""
    project_dir = Path("Projects") / req.project
    if not project_dir.is_dir():
        return {"status": "error", "detail": f"Project not found: {req.project}"}

    pattern = req.find
    if req.whole_word:
        pattern = rf"\b{_re.escape(req.find)}\b"
    flags = 0 if req.case_sensitive else _re.IGNORECASE

    changes: list[dict[str, Any]] = []
    glob_pattern = req.file_pattern or "*"
    for filepath in sorted(project_dir.rglob(glob_pattern)):
        if not filepath.is_file():
            continue
        try:
            original = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if req.find not in original and not _re.search(pattern, original, flags):
            continue
        updated = _re.sub(pattern, req.replace, original, flags=flags)
        if updated == original:
            continue
        count = len(_re.findall(pattern, original, flags))
        try:
            filepath.write_text(updated, encoding="utf-8")
        except OSError as exc:
            changes.append({"file": str(filepath.relative_to(project_dir)),
                            "replacements": 0, "error": str(exc)})
            continue
        changes.append({"file": str(filepath.relative_to(project_dir)), "replacements": count})

    total = sum(c.get("replacements", 0) for c in changes)
    logger.info("[refactor/find-replace] project=%s find=%r replace=%r changes=%d total=%d",
                req.project, req.find, req.replace, len(changes), total)
    return {"status": "ok", "changes": changes, "total_replacements": total}


@app.post("/refactor/rename")
def refactor_rename(req: _RenameRequest) -> dict:
    """Rename a symbol across all matching project files (M9-3)."""
    project_dir = Path("Projects") / req.project
    if not project_dir.is_dir():
        return {"status": "error", "detail": f"Project not found: {req.project}"}

    pattern = rf"\b{_re.escape(req.old_name)}\b"
    changes: list[dict[str, Any]] = []
    for filepath in sorted(project_dir.rglob(req.file_pattern)):
        if not filepath.is_file():
            continue
        try:
            original = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        updated = _re.sub(pattern, req.new_name, original)
        if updated == original:
            continue
        count = len(_re.findall(pattern, original))
        try:
            filepath.write_text(updated, encoding="utf-8")
        except OSError as exc:
            changes.append({"file": str(filepath.relative_to(project_dir)),
                            "replacements": 0, "error": str(exc)})
            continue
        changes.append({"file": str(filepath.relative_to(project_dir)), "replacements": count})

    total = sum(c.get("replacements", 0) for c in changes)
    logger.info("[refactor/rename] project=%s old=%r new=%r changes=%d total=%d",
                req.project, req.old_name, req.new_name, len(changes), total)
    return {"status": "ok", "changes": changes, "total_replacements": total}


# ═════════════════════════════════════════════════════════════════════════════
#  M9-7: AI Brainstorm Sessions — LLM-powered ideation with persistence
# ─────────────────────────────────────────────────────────────────────────────
_BRAINSTORM_DB = _BASE / "logs" / "brainstorm_sessions.json"
_brainstorm_sessions: dict[str, dict[str, Any]] = {}


def _load_brainstorm_sessions() -> None:
    global _brainstorm_sessions
    if _BRAINSTORM_DB.is_file():
        try:
            _brainstorm_sessions = json.loads(_BRAINSTORM_DB.read_text(encoding="utf-8"))
        except Exception:
            _brainstorm_sessions = {}


def _save_brainstorm_sessions() -> None:
    try:
        _BRAINSTORM_DB.parent.mkdir(parents=True, exist_ok=True)
        tmp = _BRAINSTORM_DB.with_suffix(".tmp")
        tmp.write_text(json.dumps(_brainstorm_sessions, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(_BRAINSTORM_DB)
    except Exception as exc:
        logger.warning("Could not save brainstorm sessions: %s", exc)


_load_brainstorm_sessions()


class _BrainstormRequest(BaseModel):
    topic: str
    project: str = "default"
    count: int = 5


@app.post("/brainstorm/session")
def brainstorm_session(req: _BrainstormRequest) -> dict:
    """Start an AI-powered brainstorm session and return generated ideas (M9-7)."""
    session_id = str(_uuid_mod.uuid4())[:8]
    prompt = (
        f"Brainstorm {req.count} distinct, actionable ideas for the following topic. "
        f"Reply with a numbered list only.\n\nTopic: {req.topic}"
    )
    from core.agent import Agent
    agent = Agent(llm=_llm, tool_registry=_registry, permission_system=_permissions,
                  task_runner=_runner, config=_config, project_path=req.project)
    try:
        raw = agent.run(prompt=prompt, project_path=req.project)
    except Exception as exc:
        logger.error("brainstorm_session error: %s", exc)
        raw = ""

    # Parse numbered list items
    ideas: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        cleaned = _re.sub(r"^\d+[.)]\s*", "", line)
        if cleaned:
            ideas.append(cleaned)

    session = {
        "session_id": session_id,
        "topic": req.topic,
        "project": req.project,
        "ideas": ideas,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _brainstorm_sessions[session_id] = session
    _save_brainstorm_sessions()
    logger.info("[brainstorm] session=%s topic=%r ideas=%d", session_id, req.topic, len(ideas))
    return session


@app.get("/brainstorm/sessions")
def brainstorm_sessions() -> dict:
    """List all brainstorm sessions (M9-7)."""
    items = sorted(_brainstorm_sessions.values(),
                   key=lambda s: s.get("created_at", ""), reverse=True)
    return {"sessions": items}


# ═════════════════════════════════════════════════════════════════════════════
#  M9-2: AI Documentation Generator — LLM-powered docstrings and README
# ─────────────────────────────────────────────────────────────────────────────
_DOCGEN_DB = _BASE / "logs" / "docgen_history.json"
_docgen_history_store: list[dict[str, Any]] = []


def _load_docgen_history() -> None:
    global _docgen_history_store
    if _DOCGEN_DB.is_file():
        try:
            _docgen_history_store = json.loads(_DOCGEN_DB.read_text(encoding="utf-8"))
        except Exception:
            _docgen_history_store = []


def _save_docgen_history() -> None:
    try:
        _DOCGEN_DB.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DOCGEN_DB.with_suffix(".tmp")
        tmp.write_text(json.dumps(_docgen_history_store[-200:], indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(_DOCGEN_DB)
    except Exception as exc:
        logger.warning("Could not save docgen history: %s", exc)


_load_docgen_history()


class _DocgenRequest(BaseModel):
    code: str
    language: str = "python"
    doc_type: str = "docstrings"   # "docstrings" | "readme" | "inline"
    project: str = "default"


@app.post("/docgen/generate")
def docgen_generate(req: _DocgenRequest) -> dict:
    """Generate AI documentation for code (M9-2)."""
    type_instructions: dict[str, str] = {
        "docstrings": (
            "Add comprehensive docstrings/doc-comments to every public function, class, "
            "and method in the code below. Preserve the original code exactly; only add "
            "documentation. Return the fully documented source code."
        ),
        "readme": (
            "Write a concise README section (Markdown) that explains what this code does, "
            "its public API, and usage examples."
        ),
        "inline": (
            "Add brief inline comments to the most complex or non-obvious lines. "
            "Return the fully annotated source code."
        ),
    }
    instruction = type_instructions.get(req.doc_type, type_instructions["docstrings"])
    prompt = (
        f"{instruction}\n\nLanguage: {req.language}\n\n"
        f"```{req.language}\n{req.code[:_MAX_AI_CODE_CHARS]}\n```"
    )
    from core.agent import Agent
    agent = Agent(llm=_llm, tool_registry=_registry, permission_system=_permissions,
                  task_runner=_runner, config=_config, project_path=req.project)
    try:
        documentation = agent.run(prompt=prompt, project_path=req.project)
    except Exception as exc:
        logger.error("docgen_generate error: %s", exc)
        documentation = f"[Error generating documentation] {exc}"

    entry = {
        "id": str(_uuid_mod.uuid4())[:8],
        "doc_type": req.doc_type,
        "language": req.language,
        "project": req.project,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "documentation": documentation,
    }
    _docgen_history_store.append(entry)
    _save_docgen_history()
    logger.info("[docgen] type=%s lang=%s project=%s", req.doc_type, req.language, req.project)
    return {"status": "ok", "documentation": documentation, "id": entry["id"]}


@app.get("/docgen/history")
def docgen_history(limit: int = 20) -> dict:
    """Return recent documentation generation history (M9-2)."""
    items = _docgen_history_store[-limit:][::-1]
    return {"history": items}


# ═════════════════════════════════════════════════════════════════════════════
#  M9-6: API Client — built-in HTTP request tester with persistent collections
# ─────────────────────────────────────────────────────────────────────────────
_APICLIENT_DB = _BASE / "logs" / "apiclient_collections.json"
_apiclient_collections_store: dict[str, dict[str, Any]] = {}


def _load_apiclient_collections() -> None:
    global _apiclient_collections_store
    if _APICLIENT_DB.is_file():
        try:
            _apiclient_collections_store = json.loads(_APICLIENT_DB.read_text(encoding="utf-8"))
        except Exception:
            _apiclient_collections_store = {}


def _save_apiclient_collections() -> None:
    try:
        _APICLIENT_DB.parent.mkdir(parents=True, exist_ok=True)
        tmp = _APICLIENT_DB.with_suffix(".tmp")
        tmp.write_text(json.dumps(_apiclient_collections_store, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(_APICLIENT_DB)
    except Exception as exc:
        logger.warning("Could not save apiclient collections: %s", exc)


_load_apiclient_collections()


class _ApiCollectionRequest(BaseModel):
    name: str
    description: str = ""


class _ApiRequestItem(BaseModel):
    name: str
    method: str = "GET"
    url: str
    headers: dict[str, str] = {}
    body: str = ""


class _ApiSendRequest(BaseModel):
    method: str = "GET"
    url: str
    headers: dict[str, str] = {}
    body: str = ""
    timeout: float = 30.0


@app.get("/apiclient/collections")
def apiclient_collections() -> dict:
    """List all API client collections (M9-6)."""
    items = [
        {"name": k, "description": v.get("description", ""),
         "request_count": len(v.get("requests", []))}
        for k, v in _apiclient_collections_store.items()
    ]
    return {"collections": items}


@app.get("/apiclient/collection/{name}")
def apiclient_collection(name: str) -> dict:
    """Get a specific API collection (M9-6)."""
    col = _apiclient_collections_store.get(name)
    if col is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")
    return {"name": name, "description": col.get("description", ""),
            "requests": col.get("requests", [])}


@app.post("/apiclient/collection")
def apiclient_collection_create(req: _ApiCollectionRequest) -> dict:
    """Create a new API collection (M9-6)."""
    _apiclient_collections_store[req.name] = {
        "description": req.description,
        "requests": [],
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _save_apiclient_collections()
    return {"status": "ok", "name": req.name}


@app.post("/apiclient/collection/{name}/request")
def apiclient_request_create(name: str, req: _ApiRequestItem) -> dict:
    """Add a request to a collection (M9-6)."""
    col = _apiclient_collections_store.setdefault(name, {"description": "", "requests": []})
    entry = {
        "id": str(_uuid_mod.uuid4())[:8],
        "name": req.name,
        "method": req.method.upper(),
        "url": req.url,
        "headers": req.headers,
        "body": req.body,
    }
    col.setdefault("requests", []).append(entry)
    _save_apiclient_collections()
    return {"status": "ok", "id": entry["id"]}


@app.post("/apiclient/send")
def apiclient_send(req: _ApiSendRequest) -> dict:
    """Send an HTTP request and return the response (M9-6)."""
    import urllib.request
    import urllib.error

    method = req.method.upper()
    body_bytes = req.body.encode("utf-8") if req.body else None
    request = urllib.request.Request(req.url, data=body_bytes, method=method)
    for k, v in req.headers.items():
        request.add_header(k, v)

    try:
        with urllib.request.urlopen(request, timeout=req.timeout) as resp:
            raw = resp.read()
            try:
                body = raw.decode("utf-8")
            except UnicodeDecodeError:
                body = raw.hex()
            headers_out = dict(resp.headers)
            status_code = resp.status
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        headers_out = dict(exc.headers) if exc.headers else {}
        status_code = exc.code
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

    logger.info("[apiclient/send] %s %s -> %d", method, req.url, status_code)
    return {"status": status_code, "body": body, "headers": headers_out}


# ═════════════════════════════════════════════════════════════════════════════
#  M9-5: Persistent Task Queue — async task execution with status tracking
# ─────────────────────────────────────────────────────────────────────────────
import threading as _queue_threading

_TASK_QUEUE_DB = _BASE / "logs" / "task_queue.json"
_task_queue_store: dict[str, dict[str, Any]] = {}   # task_id -> task record
_task_queue_lock = _queue_threading.Lock()


def _load_task_queue() -> None:
    global _task_queue_store
    if _TASK_QUEUE_DB.is_file():
        try:
            _task_queue_store = json.loads(_TASK_QUEUE_DB.read_text(encoding="utf-8"))
        except Exception:
            _task_queue_store = {}


def _save_task_queue() -> None:
    try:
        _TASK_QUEUE_DB.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TASK_QUEUE_DB.with_suffix(".tmp")
        with _task_queue_lock:
            data = dict(_task_queue_store)
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_TASK_QUEUE_DB)
    except Exception as exc:
        logger.warning("Could not save task queue: %s", exc)


_load_task_queue()


class _QueueTaskRequest(BaseModel):
    command: str
    project: str = "default"
    label: str = ""


def _run_queued_task(task_id: str, command: str, project: str) -> None:
    """Execute a queued shell command in the background."""
    project_dir = Path("Projects") / project
    cwd = str(project_dir) if project_dir.is_dir() else None
    with _task_queue_lock:
        _task_queue_store[task_id]["status"] = "running"
        _task_queue_store[task_id]["started_at"] = (
            datetime.datetime.now(datetime.timezone.utc).isoformat()
        )
    _save_task_queue()

    try:
        result = subprocess.run(
            command, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=300,
        )
        output = (result.stdout + result.stderr).strip()
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        output = "Task timed out after 300 seconds."
        exit_code = -1
    except Exception as exc:
        output = str(exc)
        exit_code = -1

    with _task_queue_lock:
        _task_queue_store[task_id].update({
            "status": "done" if exit_code == 0 else "failed",
            "exit_code": exit_code,
            "output": output,
            "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
    _save_task_queue()
    logger.info("[queue] task=%s command=%r exit_code=%d", task_id, command, exit_code)


@app.get("/queue/stats")
def queue_stats() -> dict:
    """Return task queue statistics (M9-5)."""
    with _task_queue_lock:
        statuses = [t["status"] for t in _task_queue_store.values()]
    return {
        "pending": statuses.count("pending"),
        "running": statuses.count("running"),
        "done": statuses.count("done"),
        "failed": statuses.count("failed"),
        "total": len(statuses),
    }


@app.get("/queue/tasks")
def queue_tasks() -> dict:
    """List all tasks in the queue (M9-5)."""
    with _task_queue_lock:
        items = sorted(_task_queue_store.values(),
                       key=lambda t: t.get("created_at", ""), reverse=True)
    return {"tasks": items}


@app.post("/queue/task")
def queue_task(req: _QueueTaskRequest) -> dict:
    """Enqueue a shell command for background execution (M9-5)."""
    task_id = str(_uuid_mod.uuid4())[:8]
    record: dict[str, Any] = {
        "task_id": task_id,
        "command": req.command,
        "project": req.project,
        "label": req.label or req.command[:60],
        "status": "pending",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "output": "",
        "exit_code": None,
    }
    with _task_queue_lock:
        _task_queue_store[task_id] = record
    _save_task_queue()
    t = _queue_threading.Thread(
        target=_run_queued_task, args=(task_id, req.command, req.project), daemon=True,
    )
    t.start()
    logger.info("[queue] enqueued task=%s command=%r", task_id, req.command)
    return {"task_id": task_id, "status": "pending"}


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


# ═════════════════════════════════════════════════════════════════════════════
#  M9-4: Docker Integration — list containers, build/run images from IDE
# ─────────────────────────────────────────────────────────────────────────────

def _docker_available() -> bool:
    """Return True if the docker CLI is reachable."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


class _DockerBuildRequest(BaseModel):
    project: str = "default"
    tag: str = ""
    dockerfile: str = "Dockerfile"
    build_args: dict[str, str] = {}


class _DockerRunRequest(BaseModel):
    image: str
    name: str = ""
    ports: dict[str, str] = {}   # host_port -> container_port
    env: dict[str, str] = {}
    detach: bool = True
    remove: bool = False


@app.get("/docker/containers")
def docker_containers() -> dict:
    """List Docker containers via the docker CLI (M9-4)."""
    if not _docker_available():
        return {"containers": [], "available": False,
                "detail": "Docker daemon not reachable"}
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format",
             '{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}",'
             '"status":"{{.Status}}","ports":"{{.Ports}}"}'],
            capture_output=True, text=True, timeout=10,
        )
        containers: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception as exc:
        return {"containers": [], "available": True, "detail": str(exc)}
    return {"containers": containers, "available": True}


@app.post("/docker/build")
def docker_build(req: _DockerBuildRequest) -> dict:
    """Build a Docker image from a project directory (M9-4)."""
    if not _docker_available():
        return {"status": "error", "detail": "Docker daemon not reachable"}
    project_dir = Path("Projects") / req.project
    if not project_dir.is_dir():
        return {"status": "error", "detail": f"Project not found: {req.project}"}
    tag = req.tag or req.project.lower()
    cmd = ["docker", "build", "-t", tag, "-f", req.dockerfile]
    for k, v in req.build_args.items():
        cmd += ["--build-arg", f"{k}={v}"]
    cmd.append(".")
    try:
        result = subprocess.run(
            cmd, cwd=str(project_dir),
            capture_output=True, text=True, timeout=600,
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        return {"status": "error", "detail": "docker build timed out"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
    logger.info("[docker/build] project=%s tag=%s success=%s", req.project, tag, success)
    return {"status": "ok" if success else "error", "tag": tag,
            "output": output, "success": success}


@app.post("/docker/run")
def docker_run(req: _DockerRunRequest) -> dict:
    """Run a Docker container (M9-4)."""
    if not _docker_available():
        return {"status": "error", "detail": "Docker daemon not reachable"}
    cmd = ["docker", "run"]
    if req.detach:
        cmd.append("-d")
    if req.remove:
        cmd.append("--rm")
    if req.name:
        cmd += ["--name", req.name]
    for host_port, container_port in req.ports.items():
        cmd += ["-p", f"{host_port}:{container_port}"]
    for k, v in req.env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd.append(req.image)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        return {"status": "error", "detail": "docker run timed out"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
    logger.info("[docker/run] image=%s success=%s", req.image, success)
    return {"status": "ok" if success else "error",
            "output": output, "success": success}


# ═════════════════════════════════════════════════════════════════════════════
#  M9-9: CI Integration — trigger local CI script, view recent run history
# ─────────────────────────────────────────────────────────────────────────────
_CI_RUNS_DB = _BASE / "logs" / "ci_runs.json"
_ci_runs_store: list[dict[str, Any]] = []
_ci_runs_lock = _queue_threading.Lock()


def _load_ci_runs() -> None:
    global _ci_runs_store
    if _CI_RUNS_DB.is_file():
        try:
            _ci_runs_store = json.loads(_CI_RUNS_DB.read_text(encoding="utf-8"))
        except Exception:
            _ci_runs_store = []


def _save_ci_runs() -> None:
    try:
        _CI_RUNS_DB.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CI_RUNS_DB.with_suffix(".tmp")
        with _ci_runs_lock:
            data = list(_ci_runs_store[-500:])
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CI_RUNS_DB)
    except Exception as exc:
        logger.warning("Could not save CI runs: %s", exc)


_load_ci_runs()


class _CiRunRequest(BaseModel):
    project: str = "default"
    script: str = ""     # explicit script path, otherwise auto-detected
    label: str = ""


def _execute_ci_run(run_id: str, command: str, project: str) -> None:
    """Run a CI command in the background and record the result."""
    project_dir = Path("Projects") / project
    cwd = str(project_dir) if project_dir.is_dir() else None

    try:
        result = subprocess.run(
            command, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=600,
        )
        output = (result.stdout + result.stderr).strip()
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        output = "CI run timed out after 600 seconds."
        exit_code = -1
    except Exception as exc:
        output = str(exc)
        exit_code = -1

    with _ci_runs_lock:
        for run in _ci_runs_store:
            if run.get("run_id") == run_id:
                run.update({
                    "status": "passed" if exit_code == 0 else "failed",
                    "exit_code": exit_code,
                    "output": output,
                    "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
                break
    _save_ci_runs()
    logger.info("[ci/run] run_id=%s project=%s exit_code=%d", run_id, project, exit_code)


def _auto_detect_ci_script(project_dir: Path) -> str:
    """Return a CI command for the project, preferring local scripts."""
    if (project_dir / "ci.sh").is_file():
        return "bash ci.sh"
    if (project_dir / "Makefile").is_file():
        return "make test"
    if (project_dir / "package.json").is_file():
        return "npm test"
    if any(project_dir.glob("*.csproj")):
        return "dotnet test"
    if list(project_dir.glob("*.py")):
        return "python -m pytest"
    if (project_dir / "Cargo.toml").is_file():
        return "cargo test"
    return ""


@app.get("/ci/runs")
def ci_runs(limit: int = 50) -> dict:
    """Return recent CI run history (M9-9)."""
    with _ci_runs_lock:
        items = list(_ci_runs_store[-limit:][::-1])
    return {"runs": items}


@app.post("/ci/run")
def ci_run(req: _CiRunRequest) -> dict:
    """Trigger a CI run for a project (M9-9)."""
    project_dir = Path("Projects") / req.project
    if not project_dir.is_dir():
        return {"status": "error", "detail": f"Project not found: {req.project}"}
    command = req.script or _auto_detect_ci_script(project_dir)
    if not command:
        return {"status": "error", "detail": "Cannot auto-detect CI command for this project"}

    run_id = str(_uuid_mod.uuid4())[:8]
    record: dict[str, Any] = {
        "run_id": run_id,
        "project": req.project,
        "command": command,
        "label": req.label or command,
        "status": "running",
        "exit_code": None,
        "output": "",
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "finished_at": None,
    }
    with _ci_runs_lock:
        _ci_runs_store.append(record)
    _save_ci_runs()
    t = _queue_threading.Thread(
        target=_execute_ci_run, args=(run_id, command, req.project), daemon=True,
    )
    t.start()
    logger.info("[ci/run] run_id=%s project=%s command=%r", run_id, req.project, command)
    return {"status": "ok", "run_id": run_id}


# ═════════════════════════════════════════════════════════════════════════════
#  M9-10: Deployment Manager — configure and run project deployments
# ─────────────────────────────────────────────────────────────────────────────
_DEPLOY_DB = _BASE / "logs" / "deployments.json"
_deploy_configs_store: dict[str, dict[str, Any]] = {}
_deploy_history_store: list[dict[str, Any]] = []
_deploy_lock = _queue_threading.Lock()


def _load_deploy_data() -> None:
    global _deploy_configs_store, _deploy_history_store
    if _DEPLOY_DB.is_file():
        try:
            data = json.loads(_DEPLOY_DB.read_text(encoding="utf-8"))
            _deploy_configs_store = data.get("configs", {})
            _deploy_history_store = data.get("history", [])
        except Exception:
            pass


def _save_deploy_data() -> None:
    try:
        _DEPLOY_DB.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DEPLOY_DB.with_suffix(".tmp")
        with _deploy_lock:
            data = {
                "configs": dict(_deploy_configs_store),
                "history": list(_deploy_history_store[-200:]),
            }
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_DEPLOY_DB)
    except Exception as exc:
        logger.warning("Could not save deploy data: %s", exc)


_load_deploy_data()


class _DeployConfigRequest(BaseModel):
    name: str
    project: str = "default"
    command: str
    environment: dict[str, str] = {}
    description: str = ""


class _DeployRunRequest(BaseModel):
    config_name: str
    project: str = "default"


def _execute_deployment(deploy_id: str, command: str, project: str,
                        environment: dict[str, str]) -> None:
    """Run a deployment command in the background."""
    project_dir = Path("Projects") / project
    cwd = str(project_dir) if project_dir.is_dir() else None
    env = dict(os.environ)
    env.update(environment)
    try:
        result = subprocess.run(
            command, shell=True, cwd=cwd, env=env,
            capture_output=True, text=True, timeout=600,
        )
        output = (result.stdout + result.stderr).strip()
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        output = "Deployment timed out after 600 seconds."
        exit_code = -1
    except Exception as exc:
        output = str(exc)
        exit_code = -1

    with _deploy_lock:
        for item in _deploy_history_store:
            if item.get("deploy_id") == deploy_id:
                item.update({
                    "status": "success" if exit_code == 0 else "failed",
                    "exit_code": exit_code,
                    "output": output,
                    "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
                break
    _save_deploy_data()
    logger.info("[deploy] deploy_id=%s project=%s exit_code=%d", deploy_id, project, exit_code)


@app.get("/deploy/configs")
def deploy_configs() -> dict:
    """List deploy configurations (M9-10)."""
    with _deploy_lock:
        items = list(_deploy_configs_store.values())
    return {"items": items}


@app.get("/deploy/history")
def deploy_history(limit: int = 50) -> dict:
    """Return deployment run history (M9-10)."""
    with _deploy_lock:
        items = list(_deploy_history_store[-limit:][::-1])
    return {"items": items}


@app.post("/deploy/config")
def deploy_config(req: _DeployConfigRequest) -> dict:
    """Create or update a deploy configuration (M9-10)."""
    config: dict[str, Any] = {
        "name": req.name,
        "project": req.project,
        "command": req.command,
        "environment": req.environment,
        "description": req.description,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with _deploy_lock:
        _deploy_configs_store[req.name] = config
    _save_deploy_data()
    return {"status": "ok", "name": req.name}


@app.post("/deploy/run")
def deploy_run(req: _DeployRunRequest) -> dict:
    """Run a named deploy configuration (M9-10)."""
    with _deploy_lock:
        cfg = _deploy_configs_store.get(req.config_name)
    if cfg is None:
        return {"status": "error", "detail": f"Deploy config '{req.config_name}' not found"}

    deploy_id = str(_uuid_mod.uuid4())[:8]
    record: dict[str, Any] = {
        "deploy_id": deploy_id,
        "config_name": req.config_name,
        "project": cfg.get("project", req.project),
        "command": cfg["command"],
        "status": "running",
        "exit_code": None,
        "output": "",
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "finished_at": None,
    }
    with _deploy_lock:
        _deploy_history_store.append(record)
    _save_deploy_data()
    t = _queue_threading.Thread(
        target=_execute_deployment,
        args=(deploy_id, cfg["command"], cfg.get("project", req.project),
              cfg.get("environment", {})),
        daemon=True,
    )
    t.start()
    logger.info("[deploy/run] deploy_id=%s config=%s", deploy_id, req.config_name)
    return {"status": "ok", "deploy_id": deploy_id}


@app.get("/db/connections")
def db_connections() -> dict:
    return {"connections": []}


@app.post("/db/connect")
def db_connect(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"status": "ok"}


@app.post("/db/query")
def db_query(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"rows": [], "columns": []}


# ═════════════════════════════════════════════════════════════════════════════
#  M9-9 continued: Cron Job Scheduler — schedule recurring tasks
# ─────────────────────────────────────────────────────────────────────────────
_CRON_DB = _BASE / "logs" / "cron_jobs.json"
_cron_jobs_store: dict[str, dict[str, Any]] = {}
_cron_history_store: list[dict[str, Any]] = []
_cron_lock = _queue_threading.Lock()
_cron_thread: "_queue_threading.Thread | None" = None
_cron_stop_event = _queue_threading.Event()


def _load_cron_data() -> None:
    global _cron_jobs_store, _cron_history_store
    if _CRON_DB.is_file():
        try:
            data = json.loads(_CRON_DB.read_text(encoding="utf-8"))
            _cron_jobs_store = data.get("jobs", {})
            _cron_history_store = data.get("history", [])
        except Exception:
            pass


def _save_cron_data() -> None:
    try:
        _CRON_DB.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CRON_DB.with_suffix(".tmp")
        with _cron_lock:
            data = {
                "jobs": dict(_cron_jobs_store),
                "history": list(_cron_history_store[-500:]),
            }
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CRON_DB)
    except Exception as exc:
        logger.warning("Could not save cron data: %s", exc)


_load_cron_data()


class _CronJobRequest(BaseModel):
    name: str
    command: str
    project: str = "default"
    interval_seconds: int = 3600   # default: every hour
    enabled: bool = True


def _cron_worker() -> None:
    """Background thread that fires cron jobs at their scheduled intervals."""
    import time
    while not _cron_stop_event.wait(timeout=30):
        now = datetime.datetime.now(datetime.timezone.utc)
        with _cron_lock:
            jobs = list(_cron_jobs_store.values())
        for job in jobs:
            if not job.get("enabled", True):
                continue
            last_run_str = job.get("last_run_at")
            interval = int(job.get("interval_seconds", 3600))
            if last_run_str:
                last_run = datetime.datetime.fromisoformat(last_run_str)
                elapsed = (now - last_run).total_seconds()
                if elapsed < interval:
                    continue
            # Execute
            job_id = job["job_id"]
            command = job["command"]
            project = job.get("project", "default")
            project_dir = Path("Projects") / project
            cwd = str(project_dir) if project_dir.is_dir() else None
            try:
                result = subprocess.run(
                    command, shell=True, cwd=cwd,
                    capture_output=True, text=True, timeout=120,
                )
                output = (result.stdout + result.stderr).strip()
                exit_code = result.returncode
            except Exception as exc:
                output = str(exc)
                exit_code = -1
            run_record = {
                "job_id": job_id,
                "name": job.get("name", ""),
                "command": command,
                "project": project,
                "exit_code": exit_code,
                "output": output[:2000],
                "ran_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            with _cron_lock:
                _cron_jobs_store[job_id]["last_run_at"] = run_record["ran_at"]
                _cron_history_store.append(run_record)
            _save_cron_data()
            logger.info("[cron] job=%s exit_code=%d", job_id, exit_code)


_cron_thread = _queue_threading.Thread(target=_cron_worker, daemon=True, name="cron-worker")
_cron_thread.start()


@app.get("/cron/jobs")
def cron_jobs_list() -> dict:
    """List cron job definitions (M9-9)."""
    with _cron_lock:
        items = list(_cron_jobs_store.values())
    return {"items": items}


@app.get("/cron/history")
def cron_history(limit: int = 100) -> dict:
    """Return cron execution history (M9-9)."""
    with _cron_lock:
        items = list(_cron_history_store[-limit:][::-1])
    return {"items": items}


@app.post("/cron/job")
def cron_job(req: _CronJobRequest) -> dict:
    """Create or update a cron job (M9-9)."""
    # Reuse existing ID if name already registered
    existing_id: str | None = None
    with _cron_lock:
        for jid, j in _cron_jobs_store.items():
            if j.get("name") == req.name:
                existing_id = jid
                break
    job_id = existing_id or str(_uuid_mod.uuid4())[:8]
    record: dict[str, Any] = {
        "job_id": job_id,
        "name": req.name,
        "command": req.command,
        "project": req.project,
        "interval_seconds": req.interval_seconds,
        "enabled": req.enabled,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "last_run_at": None,
    }
    with _cron_lock:
        _cron_jobs_store[job_id] = record
    _save_cron_data()
    logger.info("[cron] registered job=%s name=%r interval=%ds", job_id, req.name,
                req.interval_seconds)
    return {"status": "ok", "job_id": job_id}


@app.get("/terminal/sessions")
def terminal_sessions() -> dict:
    return {"sessions": []}


@app.post("/terminal/session")
def terminal_session(req: dict = {}) -> dict:  # type: ignore[assignment]
    return {"session_id": str(_uuid_mod.uuid4())[:8]}


# ═════════════════════════════════════════════════════════════════════════════
#  M9-8: Test Runner — collect, run, store test reports
# ─────────────────────────────────────────────────────────────────────────────
_TESTRUNNER_DB = _BASE / "logs" / "testrunner_reports.json"
_testrunner_reports_store: list[dict[str, Any]] = []
_testrunner_lock = _queue_threading.Lock()


def _load_testrunner_reports() -> None:
    global _testrunner_reports_store
    if _TESTRUNNER_DB.is_file():
        try:
            _testrunner_reports_store = json.loads(_TESTRUNNER_DB.read_text(encoding="utf-8"))
        except Exception:
            _testrunner_reports_store = []


def _save_testrunner_reports() -> None:
    try:
        _TESTRUNNER_DB.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TESTRUNNER_DB.with_suffix(".tmp")
        with _testrunner_lock:
            data = list(_testrunner_reports_store[-200:])
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_TESTRUNNER_DB)
    except Exception as exc:
        logger.warning("Could not save test runner reports: %s", exc)


_load_testrunner_reports()


class _TestrunnerRequest(BaseModel):
    project: str = "default"
    command: str = ""      # explicit test command; auto-detected if blank
    label: str = ""


def _parse_test_summary(output: str) -> dict[str, Any]:
    """Extract pass/fail counts from common test output formats."""
    summary: dict[str, Any] = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    # pytest: "5 passed, 2 failed, 1 warning"
    m = _re.search(r"(\d+) passed", output)
    if m:
        summary["passed"] = int(m.group(1))
    m = _re.search(r"(\d+) failed", output)
    if m:
        summary["failed"] = int(m.group(1))
    m = _re.search(r"(\d+) error", output, _re.IGNORECASE)
    if m:
        summary["errors"] = int(m.group(1))
    m = _re.search(r"(\d+) skipped", output, _re.IGNORECASE)
    if m:
        summary["skipped"] = int(m.group(1))
    # dotnet: "Passed: 10, Failed: 0, Skipped: 0"
    m = _re.search(r"Passed:\s*(\d+)", output)
    if m:
        summary["passed"] = int(m.group(1))
    m = _re.search(r"Failed:\s*(\d+)", output)
    if m:
        summary["failed"] = int(m.group(1))
    # cargo: "test result: ok. 5 passed; 0 failed"
    m = _re.search(r"(\d+) passed;", output)
    if m:
        summary["passed"] = int(m.group(1))
    m = _re.search(r"(\d+) failed", output)
    if m:
        summary["failed"] = int(m.group(1))
    return summary


@app.get("/testrunner/reports")
def testrunner_reports(limit: int = 20) -> dict:
    """Return recent test run reports (M9-8)."""
    with _testrunner_lock:
        items = list(_testrunner_reports_store[-limit:][::-1])
    return {"reports": items}


@app.post("/testrunner/run")
def testrunner_run(req: _TestrunnerRequest) -> dict:
    """Run tests for a project and store the report (M9-8)."""
    project_dir = Path("Projects") / req.project
    if not project_dir.is_dir():
        return {"status": "error", "detail": f"Project not found: {req.project}"}
    command = req.command or _auto_detect_command(project_dir, "test")
    if not command:
        return {"status": "error", "detail": "Cannot auto-detect test command for this project"}

    report_id = str(_uuid_mod.uuid4())[:8]
    try:
        result = subprocess.run(
            command, shell=True, cwd=str(project_dir),
            capture_output=True, text=True, timeout=300,
        )
        output = (result.stdout + result.stderr).strip()
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        output = "Tests timed out after 300 seconds."
        exit_code = -1
    except Exception as exc:
        output = str(exc)
        exit_code = -1

    summary = _parse_test_summary(output)
    report: dict[str, Any] = {
        "report_id": report_id,
        "project": req.project,
        "command": command,
        "label": req.label or command,
        "exit_code": exit_code,
        "success": exit_code == 0,
        "output": output,
        "summary": summary,
        "ran_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with _testrunner_lock:
        _testrunner_reports_store.append(report)
    _save_testrunner_reports()
    logger.info("[testrunner] project=%s exit_code=%d passed=%d failed=%d",
                req.project, exit_code, summary["passed"], summary["failed"])
    return {"status": "ok", "report_id": report_id, "summary": summary, "success": exit_code == 0}


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


# ═════════════════════════════════════════════════════════════════════════════
#  M5-1: RAG-injected chat — enrich /chat context with Archive search results
# ─────────────────────────────────────────────────────────────────────────────
# The existing /chat endpoint is extended: if the Archive is available it injects
# the top-3 archive snippets relevant to the user's message into the agent prompt.
# This is transparent — no API changes are required on the client side.

def _get_rag_context(query: str, top_k: int = 3) -> str:
    """Return a formatted string of the top-k archive hits for *query*."""
    if not _HAS_ARCHIVE or _archive is None:
        return ""
    try:
        results = _archive.search(query, top_k=top_k)
        if not results:
            return ""
        parts = ["[Archive context]"]
        for e in results:
            parts.append(f"### {e.title} ({e.language})\n{e.content[:400]}")
        return "\n\n".join(parts)
    except Exception:
        return ""


# ═════════════════════════════════════════════════════════════════════════════
#  M5-2: Context-aware completions — /ai/complete with file + archive context
# ─────────────────────────────────────────────────────────────────────────────

class _CompletionReq(BaseModel):
    code: str               # the code up to the cursor
    file_path: str = ""     # relative path of the open file (for language hint)
    project: str = "default"
    max_tokens: int = 256


@app.post("/ai/complete/context")
def ai_complete_context(req: _CompletionReq) -> dict:
    """Context-aware completion: injects open-file + Archive + project profile
    into the system prompt before asking the LLM to complete the code.

    M5-2
    """
    archive_ctx = _get_rag_context(req.code[-500:], top_k=2)
    profile_ctx = _build_project_profile_text(req.project)

    system = (
        "You are an expert code completion engine.\n"
        "Complete the code exactly where it stops — output ONLY the completion, no explanation.\n"
    )
    if archive_ctx:
        system += f"\n{archive_ctx}\n"
    if profile_ctx:
        system += f"\n[Project profile]\n{profile_ctx}\n"

    prompt = f"Continue the following code:\n```\n{req.code[-_MAX_AI_CODE_CHARS:]}\n```"
    from core.agent import Agent
    agent = Agent(llm=_llm, tool_registry=_registry, permission_system=_permissions,
                  task_runner=_runner, config=_config, project_path=req.project)
    try:
        completion = agent.run(
            prompt=prompt,
            project_path=req.project,
            system_prompt=system,
        )
    except TypeError:
        # Older Agent may not accept system_prompt kwarg — fall back
        try:
            completion = _llm.chat([
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ])
        except Exception as exc:
            completion = f"[Completion error] {exc}"
    except Exception as exc:
        completion = f"[Completion error] {exc}"
    return {"completion": completion, "file_path": req.file_path}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-3: Voice in ArbiterEngine — /voice/tts and /voice/stt
# ─────────────────────────────────────────────────────────────────────────────
# These endpoints mirror the voice support in fastapi_bridge.py so that
# clients connected to ArbiterEngine (port 8001) can also use TTS/STT.

class _TtsRequest(BaseModel):
    text: str
    voice: str = "British_Female"


def _matches_voice_preference(voice_obj: object, keyword: str) -> bool:
    """Return True if *voice_obj* (a pyttsx3 Voice) matches the *keyword* spec.

    Handles tokens like 'british_female', 'american_male', etc.
    """
    vid = (getattr(voice_obj, "id",   "") or "").lower()
    vn  = (getattr(voice_obj, "name", "") or "").lower()
    wants_british = "british" in keyword
    wants_female  = "female"  in keyword
    wants_male    = "male"    in keyword and not wants_female

    if wants_british and ("british" not in vid and "british" not in vn):
        return False
    if wants_female and "female" not in vid and "female" not in vn:
        return False
    if wants_male and ("male" not in vid or "female" in vid):
        return False
    return True


@app.post("/voice/tts")
def voice_tts(req: _TtsRequest) -> dict:
    """Synthesise speech for *text* using the system TTS engine.

    Returns ``{"status": "ok"}`` when speech has been played, or
    ``{"status": "error", "detail": "..."}`` if TTS is unavailable.

    M5-3
    """
    try:
        import pyttsx3
        engine = pyttsx3.init()
        kw = req.voice.lower()
        for voice_obj in engine.getProperty("voices"):
            if _matches_voice_preference(voice_obj, kw):
                engine.setProperty("voice", voice_obj.id)
                break
        engine.say(req.text)
        engine.runAndWait()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


class _SttRequest(BaseModel):
    duration: int = 5   # seconds to record


@app.post("/voice/stt")
def voice_stt(req: _SttRequest) -> dict:
    """Record microphone audio for *duration* seconds and return the transcript.

    Requires ``SpeechRecognition`` and ``pyaudio`` to be installed.
    Returns ``{"transcript": "...", "status": "ok"}`` or an error dict.

    M5-3
    """
    try:
        import speech_recognition as sr  # type: ignore[import]
        recogniser = sr.Recognizer()
        with sr.Microphone() as source:
            recogniser.adjust_for_ambient_noise(source, duration=0.5)
            audio = recogniser.listen(source, timeout=req.duration + 2,
                                      phrase_time_limit=req.duration)
        transcript = recogniser.recognize_google(audio)
        return {"transcript": transcript, "status": "ok"}
    except Exception as exc:
        return {"transcript": "", "status": "error", "detail": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-4: AI code review panel — /ai/review
# ─────────────────────────────────────────────────────────────────────────────

class _ReviewReq(BaseModel):
    code: str
    file_path: str = ""
    project: str = "default"
    guidelines: str = ""   # optional custom review guidelines


@app.post("/ai/review")
def ai_code_review(req: _ReviewReq) -> dict:
    """Return a structured AI code review for the supplied code.

    The response includes a summary and a list of issues (line, severity,
    message) extracted from the LLM response.

    M5-4
    """
    guidelines_section = ""
    if req.guidelines:
        guidelines_section = f"\nApply the following custom guidelines:\n{req.guidelines[:800]}\n"
    system = (
        "You are a strict code reviewer. Review the provided code for:\n"
        "  - Bugs and logic errors (severity: error)\n"
        "  - Security vulnerabilities (severity: warning)\n"
        "  - Code style and readability issues (severity: info)\n"
        "  - Missing tests or documentation (severity: info)\n"
        f"{guidelines_section}"
        "Format your response as:\n"
        "SUMMARY: <one-sentence summary>\n"
        "ISSUES:\n"
        "- [LINE <n>] [<severity>] <description>\n"
        "...\n"
        "If no issues found, write: ISSUES: none\n"
    )
    file_hint = f" ({req.file_path})" if req.file_path else ""
    prompt = f"Review this code{file_hint}:\n```\n{req.code[:_MAX_AI_CODE_CHARS]}\n```"

    try:
        raw = _llm.chat([
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ])
    except Exception as exc:
        raw = f"[Review error] {exc}"

    # Parse the structured response
    summary = ""
    issues: list[dict] = []
    for line in raw.splitlines():
        if line.startswith("SUMMARY:"):
            summary = line[len("SUMMARY:"):].strip()
        elif line.startswith("- [LINE"):
            # Example: - [LINE 12] [error] Missing null check
            import re as _re
            m = _re.match(r"- \[LINE (\d+)\] \[(\w+)\] (.+)", line)
            if m:
                issues.append({"line": int(m.group(1)), "severity": m.group(2),
                                "message": m.group(3)})
            else:
                issues.append({"line": 0, "severity": "info", "message": line[2:]})

    return {"summary": summary, "issues": issues, "raw": raw}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-5: Chat: inline diff preview — /ai/diff
# ─────────────────────────────────────────────────────────────────────────────

class _AiDiffReq(BaseModel):
    code: str           # original file content
    instruction: str    # natural-language change instruction
    file_path: str = ""
    project: str = "default"


@app.post("/ai/diff")
def ai_diff_preview(req: _AiDiffReq) -> dict:
    """Ask the LLM to apply *instruction* to *code* and return a unified diff
    preview so the user can inspect the change before applying it.

    M5-5
    """
    system = (
        "You are a code editing assistant.\n"
        "Given the original code and an instruction, produce ONLY the modified file content.\n"
        "Output the complete modified file — nothing else."
    )
    prompt = (
        f"Instruction: {req.instruction}\n\n"
        f"Original code ({req.file_path or 'file'}):\n"
        f"```\n{req.code[:_MAX_AI_CODE_CHARS]}\n```"
    )
    try:
        modified = _llm.chat([
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ])
        # Strip markdown fences if LLM wraps output
        if modified.strip().startswith("```"):
            lines = modified.strip().splitlines()
            modified = "\n".join(
                lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            )
    except Exception as exc:
        return {"diff": "", "modified": "", "error": str(exc)}

    diff_lines = list(_difflib.unified_diff(
        req.code.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f"a/{req.file_path or 'file'}",
        tofile=f"b/{req.file_path or 'file'}",
    ))
    return {"diff": "".join(diff_lines), "modified": modified}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-6 / M5-7: Chat with file attachment and selection context
# ─────────────────────────────────────────────────────────────────────────────
# The UserMessage model is extended at request time via a new endpoint so that
# existing /chat clients are unaffected.

class _ChatWithContextReq(BaseModel):
    message: str
    project: str = "default"
    attachment: str = ""    # M5-6: file content pasted / dragged
    attachment_name: str = "" # original filename for context hint
    selection: str = ""     # M5-7: selected text from editor
    use_voice: bool = False
    voice: str = "British_Female"


@app.post("/chat/context")
def chat_with_context(msg: _ChatWithContextReq) -> dict:
    """Chat endpoint that accepts an optional file attachment (M5-6)
    and/or editor selection (M5-7) as additional context.

    Both are injected into the agent prompt before the user message.
    """
    from core.agent import Agent

    # Build augmented prompt
    extra_parts: list[str] = []
    if msg.selection:
        extra_parts.append(
            f"[Selected text in editor]\n```\n{msg.selection[:_MAX_AI_CONTEXT_CHARS]}\n```"
        )
    if msg.attachment:
        name_hint = f" ({msg.attachment_name})" if msg.attachment_name else ""
        extra_parts.append(
            f"[Attached file{name_hint}]\n```\n{msg.attachment[:_MAX_AI_CODE_CHARS]}\n```"
        )

    # RAG injection (M5-1)
    rag_ctx = _get_rag_context(msg.message, top_k=2)
    if rag_ctx:
        extra_parts.append(rag_ctx)

    augmented_prompt = "\n\n".join(extra_parts + [msg.message]) if extra_parts else msg.message

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
            prompt=augmented_prompt,
            project_path=msg.project,
            chat_history=history,
        )
    except Exception as exc:
        logger.error("chat_with_context error: %s", exc)
        response = f"[Arbiter Engine error] {exc}"

    history.append({"role": "user", "content": msg.message})
    history.append({"role": "assistant", "content": response})
    if len(history) > _MAX_CHAT_HISTORY_TURNS:
        history[:] = history[-_MAX_CHAT_HISTORY_TURNS:]

    return {"response": response, "persona": _active_personas.get(msg.project, "Arbiter")}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-14: Chat export as Markdown
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/history/{project_name}/export")
def history_export(project_name: str, fmt: str = "markdown") -> dict:
    """Export the conversation history for *project_name* as Markdown.

    Query params:
      - fmt: "markdown" (default) — returns {"content": "..."}

    M5-14
    """
    history = _chat_histories.get(project_name, [])
    if not history:
        return {"content": f"# Arbiter Chat — {project_name}\n\n*(No conversation history)*\n"}

    lines = [f"# Arbiter Chat — {project_name}\n",
             f"_Exported {datetime.datetime.now(datetime.timezone.utc).isoformat()}_\n\n---\n"]
    for turn in history:
        role  = turn.get("role", "user")
        text  = turn.get("content", "")
        label = "**You**" if role == "user" else "**Arbiter**"
        lines.append(f"{label}\n\n{text}\n\n---\n")
    return {"content": "\n".join(lines), "format": fmt, "turns": len(history)}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-15: Chat full-text search across all conversation history
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/history/search")
def history_search(q: str = "", project: str = "", limit: int = 20) -> dict:
    """Search all conversation history for messages matching *q*.

    Optional *project* restricts search to a single project.
    Returns a list of matches: {project, role, content, turn_index}.

    M5-15
    """
    if not q:
        return {"results": []}
    q_lower = q.lower()
    results: list[dict] = []
    scope = {project: _chat_histories[project]} if project and project in _chat_histories \
            else _chat_histories
    for proj, history in scope.items():
        for idx, turn in enumerate(history):
            if q_lower in turn.get("content", "").lower():
                snippet = turn["content"]
                # Return a 200-char snippet around the first hit
                pos = snippet.lower().find(q_lower)
                start = max(0, pos - 80)
                end = min(len(snippet), pos + 120)
                results.append({
                    "project": proj,
                    "role": turn.get("role", "user"),
                    "snippet": snippet[start:end],
                    "turn_index": idx,
                })
                if len(results) >= limit:
                    return {"results": results, "query": q}
    return {"results": results, "query": q}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-16: Custom personas — user-defined system-prompt personas
# ─────────────────────────────────────────────────────────────────────────────
# Custom personas are stored in  logs/custom_personas.json  so they persist
# across restarts alongside the session snapshot.

_CUSTOM_PERSONAS_FILE = _BASE / "logs" / "custom_personas.json"
_custom_personas: dict[str, str] = {}  # name → system_prompt


def _load_custom_personas() -> None:
    global _custom_personas
    if _CUSTOM_PERSONAS_FILE.is_file():
        try:
            _custom_personas = json.loads(
                _CUSTOM_PERSONAS_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            pass


def _save_custom_personas() -> None:
    try:
        _CUSTOM_PERSONAS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CUSTOM_PERSONAS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_custom_personas, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(_CUSTOM_PERSONAS_FILE)
    except Exception as exc:
        logger.warning("Could not save custom personas: %s", exc)


_load_custom_personas()  # load at import time


class _CustomPersonaReq(BaseModel):
    name: str
    system_prompt: str


@app.get("/persona/custom")
def list_custom_personas() -> dict:
    """Return all user-defined custom personas.

    M5-16
    """
    return {"personas": [{"name": k, "system_prompt": v}
                          for k, v in _custom_personas.items()]}


@app.post("/persona/custom")
def create_custom_persona(req: _CustomPersonaReq) -> dict:
    """Create or update a custom persona with a user-defined system prompt.

    The persona becomes immediately available in /personas and /chat.

    M5-16
    """
    if not req.name.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Persona name must not be empty")
    _custom_personas[req.name] = req.system_prompt
    if req.name not in _PERSONAS:
        _PERSONAS.append(req.name)
    _save_custom_personas()
    return {"status": "ok", "name": req.name}


@app.delete("/persona/custom/{name}")
def delete_custom_persona(name: str) -> dict:
    """Remove a custom persona by name.

    M5-16
    """
    if name not in _custom_personas:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Custom persona '{name}' not found")
    del _custom_personas[name]
    if name in _PERSONAS:
        _PERSONAS.remove(name)
    _save_custom_personas()
    return {"status": "removed", "name": name}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-17: Session memory — per-project KV store
# ─────────────────────────────────────────────────────────────────────────────
# Stored in  .arbiter/session_memory.json  inside each project directory so
# that memory is project-local and travels with the workspace.

def _session_memory_path(project: str) -> Path:
    """Resolve the session memory file for *project*."""
    base = _ALLOWED_ROOTS.get("projects", _BASE / "workspace")
    # Handle both "ProjectName" and full paths
    p = Path(project)
    if p.is_absolute() and p.exists():
        return p / ".arbiter" / "session_memory.json"
    return base / project / ".arbiter" / "session_memory.json"


def _load_session_memory(project: str) -> dict:
    path = _session_memory_path(project)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_session_memory(project: str, data: dict) -> None:
    path = _session_memory_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        logger.warning("Could not save session memory for %r: %s", project, exc)


class _MemorySetReq(BaseModel):
    key: str
    value: str


@app.get("/memory/{project_name}")
def memory_get_all(project_name: str) -> dict:
    """Return all session memory entries for *project_name*.

    M5-17
    """
    return {"project": project_name, "memory": _load_session_memory(project_name)}


@app.get("/memory/{project_name}/{key}")
def memory_get(project_name: str, key: str) -> dict:
    """Return a single memory entry by *key*.

    M5-17
    """
    mem = _load_session_memory(project_name)
    if key not in mem:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found in memory")
    return {"key": key, "value": mem[key]}


@app.post("/memory/{project_name}")
def memory_set(project_name: str, req: _MemorySetReq) -> dict:
    """Store or update a memory key-value pair.

    M5-17
    """
    mem = _load_session_memory(project_name)
    mem[req.key] = req.value
    _save_session_memory(project_name, mem)
    return {"status": "ok", "key": req.key}


@app.delete("/memory/{project_name}/{key}")
def memory_delete(project_name: str, key: str) -> dict:
    """Remove a memory entry by *key*.

    M5-17
    """
    mem = _load_session_memory(project_name)
    if key not in mem:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found in memory")
    del mem[key]
    _save_session_memory(project_name, mem)
    return {"status": "removed", "key": key}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-18: Project profile — reads README / pyproject / package.json
# ─────────────────────────────────────────────────────────────────────────────

def _build_project_profile_text(project: str) -> str:
    """Read the project profile files and return a text summary for LLM injection."""
    base = _ALLOWED_ROOTS.get("projects", _BASE / "workspace")
    p = Path(project)
    project_dir = p if (p.is_absolute() and p.exists()) else base / project
    if not project_dir.is_dir():
        return ""

    parts: list[str] = []

    # README
    for fname in ("README.md", "README.rst", "README.txt", "readme.md"):
        readme = project_dir / fname
        if readme.is_file():
            parts.append(f"[README]\n{readme.read_text(encoding='utf-8', errors='ignore')[:1200]}")
            break

    # Python project metadata
    for fname in ("pyproject.toml", "setup.cfg", "setup.py"):
        f = project_dir / fname
        if f.is_file():
            parts.append(f"[{fname}]\n{f.read_text(encoding='utf-8', errors='ignore')[:600]}")
            break

    # Node project metadata
    pkg = project_dir / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
            parts.append(
                f"[package.json] name={data.get('name','')} "
                f"version={data.get('version','')} "
                f"description={data.get('description','')}"
            )
        except Exception:
            pass

    # .NET project metadata
    csproj = next(project_dir.glob("*.csproj"), None)
    if csproj:
        parts.append(f"[{csproj.name}]\n{csproj.read_text(encoding='utf-8', errors='ignore')[:400]}")

    return "\n\n".join(parts)


@app.get("/project/profile")
def project_profile(project: str = "default") -> dict:
    """Return the project profile: tech stack, conventions, README summary.

    Reads README.md (or .rst/.txt), pyproject.toml / package.json / .csproj
    and returns structured profile data for context injection.

    M5-18
    """
    profile_text = _build_project_profile_text(project)
    if not profile_text:
        return {"project": project, "profile": "", "available": False}

    # Ask LLM for a brief summary of the tech stack
    try:
        summary = _llm.chat([
            {"role": "system", "content":
                "You are a project analyst. Given project files, return a short JSON object with:\n"
                '{"language": "...", "framework": "...", "summary": "..."}\n'
                "Output ONLY the JSON, nothing else."},
            {"role": "user", "content": profile_text[:2000]},
        ])
        profile_data = json.loads(summary)
    except Exception:
        profile_data = {"language": "unknown", "framework": "unknown", "summary": profile_text[:200]}

    return {"project": project, "profile": profile_data, "available": True, "raw": profile_text[:1000]}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-20: Automated dependency vulnerability scanning
# ─────────────────────────────────────────────────────────────────────────────

class _DepsScanReq(BaseModel):
    project: str = "default"


@app.post("/deps/scan")
def deps_scan(req: _DepsScanReq) -> dict:
    """Run pip-audit and/or npm-audit for *project* and return an AI summary
    of discovered vulnerabilities.

    M5-20
    """
    base = _ALLOWED_ROOTS.get("projects", _BASE / "workspace")
    p = Path(req.project)
    project_dir = p if (p.is_absolute() and p.exists()) else base / req.project
    if not project_dir.is_dir():
        return {"vulnerabilities": [], "summary": "Project directory not found.", "error": True}

    raw_outputs: list[str] = []

    # pip-audit (Python projects)
    if (project_dir / "requirements.txt").is_file() or (project_dir / "pyproject.toml").is_file():
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip_audit", "--format", "json", "--no-progress"],
                cwd=str(project_dir), capture_output=True, text=True, timeout=60,
            )
            raw_outputs.append(f"pip-audit:\n{proc.stdout or proc.stderr}")
        except Exception as exc:
            raw_outputs.append(f"pip-audit unavailable: {exc}")

    # npm audit (Node projects)
    if (project_dir / "package.json").is_file():
        try:
            proc = subprocess.run(
                ["npm", "audit", "--json"],
                cwd=str(project_dir), capture_output=True, text=True, timeout=60,
            )
            raw_outputs.append(f"npm audit:\n{(proc.stdout or proc.stderr)[:3000]}")
        except Exception as exc:
            raw_outputs.append(f"npm audit unavailable: {exc}")

    if not raw_outputs:
        return {
            "vulnerabilities": [],
            "summary": "No supported package manager found (requires requirements.txt, pyproject.toml, or package.json).",
            "error": False,
        }

    combined = "\n\n".join(raw_outputs)

    # Ask LLM for a human-readable summary
    try:
        summary = _llm.chat([
            {"role": "system", "content":
                "You are a security analyst. Summarise the following vulnerability audit output "
                "concisely: list each CVE/vulnerability with severity and a one-line fix recommendation. "
                "If no vulnerabilities are found, say so clearly."},
            {"role": "user", "content": combined[:3000]},
        ])
    except Exception as exc:
        summary = f"[AI summary error] {exc}\n\nRaw output:\n{combined[:500]}"

    return {"raw": combined[:2000], "summary": summary, "error": False}


# ═════════════════════════════════════════════════════════════════════════════
#  M5-21: Mermaid diagram generation
# ─────────────────────────────────────────────────────────────────────────────

class _DiagramReq(BaseModel):
    description: str        # natural-language description of what to diagram
    diagram_type: str = "flowchart"  # flowchart | sequence | class | er | gantt | pie
    project: str = "default"
    code: str = ""          # optional: code to analyse for class/flow diagrams


@app.post("/ai/diagram")
def ai_diagram(req: _DiagramReq) -> dict:
    """Generate a Mermaid diagram DSL string from a natural-language description.

    Supported diagram types: flowchart, sequence, class, er, gantt, pie.
    Returns ``{"diagram": "...", "diagram_type": "..."}`` where *diagram* is
    valid Mermaid syntax that can be rendered with mermaid.js.

    M5-21
    """
    type_hints = {
        "flowchart": "flowchart TD",
        "sequence":  "sequenceDiagram",
        "class":     "classDiagram",
        "er":        "erDiagram",
        "gantt":     "gantt",
        "pie":       "pie",
    }
    hint = type_hints.get(req.diagram_type, "flowchart TD")
    system = (
        f"You are a Mermaid diagram expert. Generate a valid Mermaid {req.diagram_type} diagram.\n"
        f"Start the diagram with: {hint}\n"
        "Output ONLY the Mermaid DSL — no explanation, no markdown fences."
    )
    user_parts = [f"Description: {req.description}"]
    if req.code:
        user_parts.append(f"Code to analyse:\n```\n{req.code[:_MAX_AI_CODE_CHARS]}\n```")
    try:
        diagram = _llm.chat([
            {"role": "system", "content": system},
            {"role": "user",   "content": "\n".join(user_parts)},
        ])
        # Strip accidental fences
        diagram = diagram.strip()
        if diagram.startswith("```"):
            lines = diagram.splitlines()
            diagram = "\n".join(
                lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            )
    except Exception as exc:
        diagram = f"{hint}\n    %% Error: {exc}"
    return {"diagram": diagram, "diagram_type": req.diagram_type}


# ═════════════════════════════════════════════════════════════════════════════
#  M7-16: Self-build for VSIX — Arbiter generates new VS extension features
# ─────────────────────────────────────────────────────────────────────────────
# The SelfBuildController already handles generic code generation.  For VSIX
# tasks (C#/.csproj files), we need:
#   1. A dedicated start endpoint that scopes the roadmap filter to VSIX tasks.
#   2. The self-build core to use `dotnet build` for syntax validation and
#      `dotnet test` for test execution of C# files.
#
# This is implemented via two thin extensions:
#   a. /self-build/vsix/start — starts the loop filtered to VSIX tasks
#   b. /self-build/vsix/status — mirrors /self-build/status but with VSIX label

class _VsixBuildStartRequest(BaseModel):
    task_id: str = ""
    mode: str = "assist"


@app.post("/self-build/vsix/start")
async def self_build_vsix_start(req: _VsixBuildStartRequest) -> dict:
    """Start the self-build loop scoped to VSIX / Visual Studio extension tasks.

    Equivalent to ``/self-build/start`` but pre-selects the first pending task
    whose ID starts with ``M6-`` or ``M7-`` and whose title mentions VSIX,
    C#, or Visual Studio.

    M7-16
    """
    # If no task_id given, auto-select the next VSIX/VS task
    task_id = req.task_id
    if not task_id and _ROADMAP_FILE.is_file():
        try:
            data = json.loads(_ROADMAP_FILE.read_text(encoding="utf-8"))
            vsix_keywords = ("vsix", "visual studio", "c#", "extension")
            for ms in data.get("milestones", []):
                for task in ms.get("tasks", []):
                    if task.get("status") in ("pending", "in_progress"):
                        title_lower = task.get("title", "").lower()
                        if any(kw in title_lower for kw in vsix_keywords):
                            task_id = task["id"]
                            break
                if task_id:
                    break
        except Exception:
            pass

    # Delegate to the main self-build start endpoint
    sb_req = SelfBuildStartRequest(task_id=task_id, mode=req.mode)
    return await self_build_start(sb_req)


@app.get("/self-build/vsix/status")
def self_build_vsix_status() -> dict:
    """Return self-build status with a VSIX context label.

    M7-16
    """
    base = self_build_status()
    base["context"] = "vsix"
    return base


# ═════════════════════════════════════════════════════════════════════════════
#  M8-5: CLI support — expose a /cli endpoint for arbiter_cli.py integration
# ─────────────────────────────────────────────────────────────────════════════

class _CliCommandReq(BaseModel):
    command: str                 # "build" | "run" | "test" | "chat" | "archive"
    project: str = "default"
    args: list[str] = []
    message: str = ""            # for "chat" command


@app.post("/cli/run")
def cli_run(req: _CliCommandReq) -> dict:
    """Execute an Arbiter CLI command via REST.

    This endpoint allows ``arbiter_cli.py`` to delegate commands to the
    running server rather than executing them inline.

    M8-5
    """
    cmd = req.command.lower()
    if cmd in ("build", "run", "test"):
        build_req = BuildRequest(project=req.project, command=" ".join(req.args))
        return _run_project_command(build_req, cmd)
    elif cmd == "chat":
        msg = UserMessage(message=req.message or " ".join(req.args), project=req.project)
        return chat(msg)
    elif cmd == "archive":
        sub = req.args[0] if req.args else "list"
        if sub == "rebuild":
            return archive_rebuild()
        elif sub == "search":
            query = " ".join(req.args[1:])
            return archive_search(query)
        return archive_list()
    elif cmd == "self-build":
        sub = req.args[0] if req.args else "status"
        if sub == "status":
            return self_build_status()
        elif sub == "next":
            return self_build_next()
        return self_build_status()
    return {"error": f"Unknown CLI command: {cmd}"}


# ═════════════════════════════════════════════════════════════════════════════
#  M8-2: Auto-update — check GitHub Releases for a newer version
# ─────────────────────────────────────────────────────────────────────────────

_APP_VERSION     = "0.5.0"
_GH_OWNER        = "shifty81"
_GH_REPO         = "Arbiter"
_GH_RELEASES_URL = f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/releases/latest"


def _semver_gt(a: str, b: str) -> bool:
    """Return True when *a* is strictly greater than *b* (semver comparison)."""
    def _parts(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.lstrip("vV").split(".")[:3])
        except ValueError:
            return (0, 0, 0)
    return _parts(a) > _parts(b)


@app.get("/updates/check")
def updates_check() -> dict:
    """Query the GitHub Releases API and return update availability info.

    Returns::

        {
          "current_version": "0.5.0",
          "latest_version":  "0.6.0",    # tag name, 'v' stripped
          "update_available": true,
          "release_url":  "https://github.com/...",
          "download_url": "https://github.com/.../arbiter-setup-0.6.0.exe",
          "release_notes": "...",
          "error": ""
        }

    M8-2
    """
    try:
        req = urllib.request.Request(
            _GH_RELEASES_URL,
            headers={
                "User-Agent":  f"Arbiter/{_APP_VERSION}",
                "Accept":      "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())

        tag         = data.get("tag_name", "").lstrip("vV")
        release_url = data.get("html_url", "")
        notes       = data.get("body", "")

        download_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".exe"):
                download_url = asset.get("browser_download_url", "")
                break

        return {
            "current_version":  _APP_VERSION,
            "latest_version":   tag,
            "update_available": _semver_gt(tag, _APP_VERSION),
            "release_url":      release_url,
            "download_url":     download_url,
            "release_notes":    notes[:1000],
            "error":            "",
        }
    except Exception as exc:
        return {
            "current_version":  _APP_VERSION,
            "latest_version":   _APP_VERSION,
            "update_available": False,
            "release_url":      "",
            "download_url":     "",
            "release_notes":    "",
            "error":            str(exc),
        }


# ═════════════════════════════════════════════════════════════════════════════
#  M8-3: Plugin marketplace — browse, install, rate community plugins
# ─────────────────────────────────────────════════════════════════════════════
# The marketplace registry is a JSON file maintained in the plugins/ directory.
# For community use, this can be hosted publicly (e.g. as a GitHub Gist or
# GitHub Pages JSON).  The default points to the Arbiter repo.

_MARKETPLACE_INDEX_URL = (
    f"https://raw.githubusercontent.com/{_GH_OWNER}/{_GH_REPO}/main"
    "/AIEngine/ArbiterEngine/plugins/marketplace_index.json"
)
_MARKETPLACE_RATINGS_FILE = _BASE / "plugins" / "marketplace_ratings.json"

# In-memory ratings cache (loaded on first access)
_marketplace_ratings: dict[str, dict] = {}


def _load_marketplace_ratings() -> None:
    global _marketplace_ratings
    if _MARKETPLACE_RATINGS_FILE.is_file():
        try:
            _marketplace_ratings = json.loads(
                _MARKETPLACE_RATINGS_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            pass


def _save_marketplace_ratings() -> None:
    try:
        _MARKETPLACE_RATINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _MARKETPLACE_RATINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_marketplace_ratings, indent=2), encoding="utf-8")
        tmp.replace(_MARKETPLACE_RATINGS_FILE)
    except Exception as exc:
        logger.warning("Could not save marketplace ratings: %s", exc)


_load_marketplace_ratings()


@app.get("/marketplace/plugins")
def marketplace_list(q: str = "", category: str = "") -> dict:
    """Browse the Arbiter plugin marketplace.

    Fetches the marketplace index from GitHub and merges local rating data.
    Optional *q* filters by plugin name/description; *category* filters by tag.

    M8-3
    """
    # Try to fetch the remote index; fall back to an empty catalogue on error
    try:
        req = urllib.request.Request(
            _MARKETPLACE_INDEX_URL,
            headers={"User-Agent": f"Arbiter/{_APP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            index = json.loads(resp.read())
        plugins: list[dict] = index.get("plugins", [])
    except Exception as exc:
        logger.warning("Could not fetch marketplace index: %s", exc)
        plugins = []

    # Merge local ratings
    for p in plugins:
        name = p.get("name", "")
        if name in _marketplace_ratings:
            p["rating"]      = _marketplace_ratings[name].get("average", 0.0)
            p["rating_count"] = _marketplace_ratings[name].get("count", 0)
        else:
            p.setdefault("rating", 0.0)
            p.setdefault("rating_count", 0)

    # Apply filters
    q_lower  = q.lower()
    cat_lower = category.lower()
    if q_lower:
        plugins = [p for p in plugins
                   if q_lower in p.get("name", "").lower() or
                      q_lower in p.get("description", "").lower()]
    if cat_lower:
        plugins = [p for p in plugins
                   if cat_lower in [t.lower() for t in p.get("tags", [])]]

    return {"plugins": plugins, "total": len(plugins)}


class _MarketplaceInstallReq(BaseModel):
    name: str = ""   # plugin name from the marketplace index
    url:  str = ""   # direct URL to a plugin .zip or plugin.json (fallback)


@app.post("/marketplace/install")
def marketplace_install(req: _MarketplaceInstallReq) -> dict:
    """Download and install a plugin from the marketplace or a direct URL.

    The plugin zip must contain a ``plugin.json`` manifest at the root.
    After installation the plugin is immediately hot-loaded.

    M8-3
    """
    import zipfile as _zipfile
    import tempfile as _tmpmod
    import shutil as _shutil

    # Resolve download URL
    download_url = req.url
    if req.name and not download_url:
        # Fetch marketplace index to find the URL
        try:
            r = urllib.request.Request(
                _MARKETPLACE_INDEX_URL,
                headers={"User-Agent": f"Arbiter/{_APP_VERSION}"},
            )
            with urllib.request.urlopen(r, timeout=8) as resp:
                index = json.loads(resp.read())
            for p in index.get("plugins", []):
                if p.get("name") == req.name:
                    download_url = p.get("download_url", "")
                    break
        except Exception as exc:
            return {"status": "error", "detail": f"Could not fetch marketplace: {exc}"}

    if not download_url:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Provide 'name' (marketplace) or 'url'")

    plugins_dir = _BASE / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    # Download to a temp file
    try:
        with _tmpmod.NamedTemporaryFile(delete=False, suffix=".zip") as tf:
            tmp_path = tf.name

        dl_req = urllib.request.Request(
            download_url,
            headers={"User-Agent": f"Arbiter/{_APP_VERSION}"},
        )
        with urllib.request.urlopen(dl_req, timeout=30) as resp, \
             open(tmp_path, "wb") as out:
            out.write(resp.read())
    except Exception as exc:
        return {"status": "error", "detail": f"Download failed: {exc}"}

    # Extract and install
    try:
        with _zipfile.ZipFile(tmp_path, "r") as zf:
            # Validate manifest exists
            names = zf.namelist()
            manifest_paths = [n for n in names if n.endswith("plugin.json")]
            if not manifest_paths:
                return {"status": "error", "detail": "No plugin.json found in archive"}

            # Determine plugin directory name from first manifest path
            manifest_rel = manifest_paths[0]
            top_dir = manifest_rel.split("/")[0] if "/" in manifest_rel else ""
            plugin_name = top_dir or req.name or "plugin"
            dest = plugins_dir / plugin_name

            if dest.exists():
                _shutil.rmtree(str(dest))
            zf.extractall(str(plugins_dir))

        # Hot-load the plugin
        _plugin_loader.load_all()
        installed = plugin_name

        return {"status": "installed", "plugin": installed}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
    finally:
        try:
            import os as _os
            _os.unlink(tmp_path)
        except OSError:
            pass


class _MarketplaceRateReq(BaseModel):
    name:   str
    rating: float   # 1.0 – 5.0


@app.post("/marketplace/rate")
def marketplace_rate(req: _MarketplaceRateReq) -> dict:
    """Submit a 1–5 star rating for a marketplace plugin.

    Ratings are stored locally in ``plugins/marketplace_ratings.json`` and
    merged into marketplace listing results.

    M8-3
    """
    if not 1.0 <= req.rating <= 5.0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="rating must be between 1.0 and 5.0")
    entry = _marketplace_ratings.get(req.name, {"total": 0.0, "count": 0, "average": 0.0})
    entry["total"]   = entry.get("total", 0.0) + req.rating
    entry["count"]   = entry.get("count", 0) + 1
    entry["average"] = round(entry["total"] / entry["count"], 2)
    _marketplace_ratings[req.name] = entry
    _save_marketplace_ratings()
    return {"status": "ok", "name": req.name, "average": entry["average"], "count": entry["count"]}


@app.get("/marketplace/ratings/{name}")
def marketplace_ratings(name: str) -> dict:
    """Return the local rating stats for a plugin.

    M8-3
    """
    entry = _marketplace_ratings.get(name, {})
    return {"name": name, "average": entry.get("average", 0.0), "count": entry.get("count", 0)}


# ═════════════════════════════════════════════════════════════════════════════
#  M8-8: Cloud sync — encrypted project backup to S3 / Backblaze B2
# ─────────────────────────────────────────════════════════════════════════════
# Backup strategy:
#   1. Tar the target directories (Memory/, Projects/<name>/, .arbiter/)
#   2. Encrypt with AES-256-GCM using a user-supplied passphrase (PBKDF2)
#   3. Upload the encrypted .tar.gz to S3-compatible storage (AWS S3 / Backblaze B2)
#
# Storage credentials are read from environment variables:
#   ARBITER_SYNC_PROVIDER   "s3" | "b2" | "local"  (default: local — saves to logs/)
#   ARBITER_SYNC_BUCKET     Bucket / container name
#   ARBITER_SYNC_KEY_ID     AWS access key ID / Backblaze key ID
#   ARBITER_SYNC_SECRET     AWS secret / Backblaze application key
#   ARBITER_SYNC_ENDPOINT   Optional custom S3 endpoint (for B2, Minio, etc.)
#   ARBITER_SYNC_PASSPHRASE Encryption passphrase (required for encrypt/decrypt)

import base64 as _b64
import hashlib as _hashlib
import struct as _struct


def _derive_key(passphrase: str, salt: bytes, iterations: int = 200_000) -> bytes:
    """Derive a 32-byte AES key from *passphrase* + *salt* via PBKDF2-HMAC-SHA256."""
    return _hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, iterations, 32)


def _encrypt_bytes(data: bytes, passphrase: str) -> bytes:
    """Encrypt *data* with AES-256-GCM and return a self-contained ciphertext blob.

    Format: MAGIC(4) | SALT(16) | IV(12) | TAG(16) | CIPHERTEXT
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise RuntimeError(
            "The 'cryptography' package is required for cloud sync. "
            "Install it with: pip install cryptography"
        )
    salt = os.urandom(16)
    iv   = os.urandom(12)
    key  = _derive_key(passphrase, salt)
    aes  = AESGCM(key)
    ct_with_tag = aes.encrypt(iv, data, None)   # ciphertext + 16-byte GCM tag appended
    # Split: last 16 bytes = tag, rest = ciphertext
    tag = ct_with_tag[-16:]
    ct  = ct_with_tag[:-16]
    return b"ARBK" + salt + iv + tag + ct


def _decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    """Decrypt a blob produced by :func:`_encrypt_bytes`."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise RuntimeError("The 'cryptography' package is required for cloud sync.")
    if blob[:4] != b"ARBK":
        raise ValueError("Not an Arbiter backup blob (missing magic header)")
    salt = blob[4:20]
    iv   = blob[20:32]
    tag  = blob[32:48]
    ct   = blob[48:]
    key  = _derive_key(passphrase, salt)
    aes  = AESGCM(key)
    return aes.decrypt(iv, ct + tag, None)


def _upload_to_storage(data: bytes, object_key: str) -> str:
    """Upload *data* to S3/B2/local.  Returns the object URL / path."""
    provider   = os.environ.get("ARBITER_SYNC_PROVIDER", "local").lower()
    bucket     = os.environ.get("ARBITER_SYNC_BUCKET", "arbiter-backups")
    key_id     = os.environ.get("ARBITER_SYNC_KEY_ID", "")
    secret     = os.environ.get("ARBITER_SYNC_SECRET", "")
    endpoint   = os.environ.get("ARBITER_SYNC_ENDPOINT", "")

    if provider == "local":
        dest = _BASE / "logs" / "backups" / object_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return str(dest)

    if provider in ("s3", "b2"):
        try:
            import boto3  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "The 'boto3' package is required for S3/Backblaze sync. "
                "Install it with: pip install boto3"
            )
        kwargs: dict = dict(
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
        )
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        s3 = boto3.client("s3", **kwargs)
        s3.put_object(Bucket=bucket, Key=object_key, Body=data)
        base = endpoint.rstrip("/") if endpoint else f"https://s3.amazonaws.com"
        return f"{base}/{bucket}/{object_key}"

    raise ValueError(f"Unknown ARBITER_SYNC_PROVIDER: {provider!r}")


def _download_from_storage(object_key: str) -> bytes:
    """Download *object_key* from S3/B2/local.  Returns raw bytes."""
    provider = os.environ.get("ARBITER_SYNC_PROVIDER", "local").lower()
    bucket   = os.environ.get("ARBITER_SYNC_BUCKET", "arbiter-backups")
    key_id   = os.environ.get("ARBITER_SYNC_KEY_ID", "")
    secret   = os.environ.get("ARBITER_SYNC_SECRET", "")
    endpoint = os.environ.get("ARBITER_SYNC_ENDPOINT", "")

    if provider == "local":
        src = _BASE / "logs" / "backups" / object_key
        return src.read_bytes()

    if provider in ("s3", "b2"):
        try:
            import boto3  # type: ignore[import]
        except ImportError:
            raise RuntimeError("boto3 is required. Install with: pip install boto3")
        kwargs: dict = dict(
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
        )
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        s3 = boto3.client("s3", **kwargs)
        obj = s3.get_object(Bucket=bucket, Key=object_key)
        return obj["Body"].read()

    raise ValueError(f"Unknown ARBITER_SYNC_PROVIDER: {provider!r}")


class _SyncBackupReq(BaseModel):
    project:    str = ""       # optional; if empty, backs up all Memory/
    passphrase: str = ""       # AES-256-GCM encryption passphrase


@app.post("/sync/backup")
def sync_backup(req: _SyncBackupReq) -> dict:
    """Create an encrypted backup and upload to the configured storage provider.

    If *project* is given, only that project's directory is backed up.
    Otherwise the entire ``Memory/`` directory is archived.

    Uses AES-256-GCM encryption (PBKDF2-derived key from *passphrase*).
    Requires environment variable ``ARBITER_SYNC_PASSPHRASE`` or a non-empty
    ``passphrase`` field in the request body.

    M8-8
    """
    import tarfile as _tarfile
    import io as _io

    passphrase = req.passphrase or os.environ.get("ARBITER_SYNC_PASSPHRASE", "")
    if not passphrase:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Provide 'passphrase' or set ARBITER_SYNC_PASSPHRASE env var",
        )

    # Determine what to archive
    base = _ALLOWED_ROOTS.get("projects", _BASE / "workspace")
    if req.project:
        p = Path(req.project)
        target = p if (p.is_absolute() and p.exists()) else base / req.project
        if not target.exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Project '{req.project}' not found")
        archive_root = target.parent
        arcname      = target.name
    else:
        archive_root = _BASE.parent.parent   # repo root (contains Memory/)
        arcname      = "Memory"
        target       = archive_root / "Memory"

    # Create in-memory tar.gz
    buf = _io.BytesIO()
    try:
        with _tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(str(target), arcname=arcname)
    except Exception as exc:
        return {"status": "error", "detail": f"Archive failed: {exc}"}

    raw = buf.getvalue()

    # Encrypt
    try:
        encrypted = _encrypt_bytes(raw, passphrase)
    except Exception as exc:
        return {"status": "error", "detail": f"Encryption failed: {exc}"}

    # Upload
    ts  = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"arbiter-backup-{arcname}-{ts}.tar.gz.enc"
    try:
        location = _upload_to_storage(encrypted, key)
    except Exception as exc:
        return {"status": "error", "detail": f"Upload failed: {exc}"}

    return {
        "status": "ok",
        "object_key": key,
        "location":   location,
        "size_bytes": len(encrypted),
        "timestamp":  ts,
    }


class _SyncRestoreReq(BaseModel):
    object_key:  str          # key returned by /sync/backup
    passphrase:  str = ""
    destination: str = ""     # optional override for restore target path


@app.post("/sync/restore")
def sync_restore(req: _SyncRestoreReq) -> dict:
    """Download, decrypt, and restore a backup created by /sync/backup.

    M8-8
    """
    import tarfile as _tarfile
    import io as _io

    passphrase = req.passphrase or os.environ.get("ARBITER_SYNC_PASSPHRASE", "")
    if not passphrase:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Provide 'passphrase' or set ARBITER_SYNC_PASSPHRASE env var",
        )

    # Download
    try:
        blob = _download_from_storage(req.object_key)
    except Exception as exc:
        return {"status": "error", "detail": f"Download failed: {exc}"}

    # Decrypt
    try:
        raw = _decrypt_bytes(blob, passphrase)
    except Exception as exc:
        return {"status": "error", "detail": f"Decryption failed: {exc}"}

    # Extract
    dest = Path(req.destination) if req.destination else _BASE.parent.parent
    try:
        with _tarfile.open(fileobj=_io.BytesIO(raw), mode="r:gz") as tar:
            # Safety: reject absolute paths and path-traversal members
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    return {"status": "error", "detail": f"Unsafe archive member: {member.name}"}
            tar.extractall(str(dest))
    except Exception as exc:
        return {"status": "error", "detail": f"Extraction failed: {exc}"}

    return {
        "status":      "ok",
        "object_key":  req.object_key,
        "destination": str(dest),
        "size_bytes":  len(raw),
    }


@app.get("/sync/list")
def sync_list() -> dict:
    """List available local backups (local provider only).

    For S3/B2 providers, use the storage console to browse objects.

    M8-8
    """
    provider = os.environ.get("ARBITER_SYNC_PROVIDER", "local").lower()
    if provider != "local":
        return {"provider": provider, "backups": [], "note": "Use your storage console to list remote backups."}

    backup_dir = _BASE / "logs" / "backups"
    if not backup_dir.is_dir():
        return {"provider": "local", "backups": []}

    backups = []
    for f in sorted(backup_dir.iterdir(), reverse=True):
        if f.is_file():
            backups.append({
                "object_key": f.name,
                "size_bytes": f.stat().st_size,
                "modified":   datetime.datetime.fromtimestamp(
                    f.stat().st_mtime, tz=datetime.timezone.utc
                ).isoformat(),
            })
    return {"provider": "local", "backups": backups}


if __name__ == "__main__":
    host = _config.get("server.host", "127.0.0.1")
    port = int(_config.get("server.port", 8001))
    logger.info("Starting Arbiter Engine at http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
