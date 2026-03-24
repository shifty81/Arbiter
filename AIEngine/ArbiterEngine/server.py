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

import collections
import functools
import threading
import time

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as _StarletteRequest
from starlette.responses import JSONResponse as _StarletteJSONResponse
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

setup_logging()  # writes to <repo_root>/logs/arbiter_engine/arbiter_engine.log
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
# M13-8: wrap with failover if fallback backends are configured
_llm = _build_failover_llm(_llm, _config)
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

# ─── M13: Metrics, Budget tracking, and LRU response cache ───────────────────

# Metrics (M13-7): per-endpoint counters and latency
_metrics_lock = threading.Lock()
_metrics: dict[str, dict[str, Any]] = collections.defaultdict(
    lambda: {"requests": 0, "errors": 0, "total_ms": 0.0, "latencies_ms": collections.deque(maxlen=200)}
)

# Budget tracking (M13-6): per-project token/call counts
_budget_lock = threading.Lock()
_budget: dict[str, dict[str, int]] = collections.defaultdict(
    lambda: {"calls": 0, "estimated_tokens": 0}
)

# LRU response cache (M13-4): key = (project, prompt), value = (response, expiry)
_LLM_CACHE_TTL = 300          # seconds
_LLM_CACHE_MAX = 128
_llm_cache: "collections.OrderedDict[tuple[str, str], tuple[str, float]]" = collections.OrderedDict()
_llm_cache_lock = threading.Lock()


def _cache_get(project: str, prompt: str) -> str | None:
    """Return cached LLM response or None if miss/expired."""
    key = (project, prompt)
    with _llm_cache_lock:
        if key not in _llm_cache:
            return None
        response, expiry = _llm_cache[key]
        if time.time() > expiry:
            del _llm_cache[key]
            return None
        _llm_cache.move_to_end(key)        # LRU refresh
        return response


def _cache_set(project: str, prompt: str, response: str) -> None:
    """Store an LLM response in the cache."""
    key = (project, prompt)
    with _llm_cache_lock:
        if key in _llm_cache:
            _llm_cache.move_to_end(key)
        _llm_cache[key] = (response, time.time() + _LLM_CACHE_TTL)
        while len(_llm_cache) > _LLM_CACHE_MAX:
            _llm_cache.popitem(last=False)


def _budget_record(project: str, prompt: str, response: str) -> None:
    """Accumulate token estimates and call count for a project."""
    # Rough token estimate: 1 token ≈ 4 chars
    tokens = (len(prompt) + len(response)) // 4
    with _budget_lock:
        _budget[project]["calls"] += 1
        _budget[project]["estimated_tokens"] += tokens


def _metrics_record(route: str, elapsed_ms: float, error: bool = False) -> None:
    """Record a single request in the in-memory metrics store."""
    with _metrics_lock:
        m = _metrics[route]
        m["requests"] += 1
        if error:
            m["errors"] += 1
        m["total_ms"] += elapsed_ms
        m["latencies_ms"].append(elapsed_ms)


# ─── M13-8: LLM backend failover wrapper ─────────────────────────────────────

class _FailoverLLM:
    """Wraps the primary LLM and falls back to secondary backends on error."""

    def __init__(self, primary: Any, fallbacks: list[Any]) -> None:
        self._primary = primary
        self._fallbacks = fallbacks

    def _backends(self) -> list[Any]:
        return [self._primary] + self._fallbacks

    def chat(self, messages: list[dict[str, str]]) -> str:
        for backend in self._backends():
            try:
                result = backend.chat(messages)
                if result and not result.startswith("[ERROR]") and "not reachable" not in result:
                    return result
                # Treat graceful-error strings as failures so we try the next backend
            except Exception as exc:
                logger.warning("LLM backend %s failed: %s", type(backend).__name__, exc)
        return self._primary.chat(messages)   # return primary's error message as last resort

    def generate(self, messages: list[dict[str, str]]) -> str:
        for backend in self._backends():
            try:
                result = backend.generate(messages)
                if result and not result.startswith("[ERROR]") and "not reachable" not in result:
                    return result
            except Exception as exc:
                logger.warning("LLM backend %s failed: %s", type(backend).__name__, exc)
        return self._primary.generate(messages)

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for backend in self._backends():
            try:
                result = backend.tool_call(messages, tools)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning("LLM backend %s tool_call failed: %s", type(backend).__name__, exc)
        return []

    def stream_chat(self, messages: list[dict[str, str]]) -> Any:
        return self._primary.stream_chat(messages)

    def list_models(self) -> list[str]:
        try:
            return self._primary.list_models()  # type: ignore[return-value]
        except Exception:
            return []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._primary, name)


def _build_failover_llm(primary: Any, cfg: "ConfigLoader") -> Any:
    """Build a _FailoverLLM using the fallback_backends config list."""
    fallback_names: list[str] = []
    raw = cfg.get("agent.fallback_llm_backends", "")
    if isinstance(raw, str) and raw:
        fallback_names = [b.strip() for b in raw.split(",") if b.strip()]
    elif isinstance(raw, list):
        fallback_names = [b for b in raw if b]
    if not fallback_names:
        return primary
    from llm.factory import create_llm as _create_llm
    fallbacks = []
    for name in fallback_names:
        try:
            fb = _create_llm(name, cfg)
            fallbacks.append(fb)
        except Exception as exc:
            logger.warning("Could not build fallback LLM %r: %s", name, exc)
    if not fallbacks:
        return primary
    return _FailoverLLM(primary, fallbacks)

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
_VERSION = "1.0.0"
app = FastAPI(title="Arbiter Engine", version=_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── M13-2: Global request timeout middleware (30 s) ─────────────────────────

_REQUEST_TIMEOUT_SECS = 30


class _TimeoutMiddleware(BaseHTTPMiddleware):
    """Return a 504 JSON error if a handler has not responded within the timeout."""

    async def dispatch(self, request: _StarletteRequest, call_next: Any) -> Any:
        import asyncio as _aio
        _t0 = time.monotonic()
        try:
            response = await _aio.wait_for(call_next(request), timeout=_REQUEST_TIMEOUT_SECS)
        except _aio.TimeoutError:
            path = request.url.path
            logger.warning("Request timeout after %ss: %s", _REQUEST_TIMEOUT_SECS, path)
            _metrics_record(path, _REQUEST_TIMEOUT_SECS * 1000, error=True)
            return _StarletteJSONResponse(
                {"detail": f"Request timed out after {_REQUEST_TIMEOUT_SECS} s. "
                           "Check that your LLM backend is running."},
                status_code=504,
            )
        elapsed = (time.monotonic() - _t0) * 1000
        _metrics_record(request.url.path, elapsed)
        return response


app.add_middleware(_TimeoutMiddleware)


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

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    """M13-3: Enhanced health check — probes configured LLM backend reachability.

    Returns a ``backends`` map showing each backend's status, latency (ms),
    and which model is loaded, so operators can diagnose connectivity problems
    without inspecting logs.

    The probe calls are short (3 s timeout) and run in FastAPI's sync-route
    thread pool, so they never block the asyncio event loop.
    """
    import requests as _req_lib

    def _probe(url: str, path: str = "/api/tags", timeout: float = 3.0) -> dict[str, Any]:
        """Probe a single backend URL; return status dict with optional body."""
        try:
            t0 = time.monotonic()
            r = _req_lib.get(f"{url.rstrip('/')}{path}", timeout=timeout)
            latency_ms = round((time.monotonic() - t0) * 1000, 1)
            ok = r.status_code < 400
            result: dict[str, Any] = {
                "reachable": ok,
                "latency_ms": latency_ms,
                "http_status": r.status_code,
            }
            # Parse model list from the same response, avoiding a duplicate request
            if ok:
                try:
                    body = r.json()
                    if path == "/api/tags":
                        result["models"] = [m.get("name", "") for m in body.get("models", [])]
                    elif path == "/v1/models":
                        result["models"] = [m.get("id", "") for m in body.get("data", [])]
                except Exception:
                    pass
            return result
        except Exception as exc:
            return {"reachable": False, "error": str(exc)}

    backends: dict[str, Any] = {}

    if _backend == "ollama":
        backends["ollama"] = {
            "primary": True,
            **_probe(_config.get("llm.ollama.base_url", "http://localhost:11434"), "/api/tags"),
        }
    elif _backend == "lmstudio":
        backends["lmstudio"] = {
            "primary": True,
            **_probe(_config.get("llm.lmstudio.base_url", "http://localhost:1234"), "/v1/models"),
        }
    elif _backend == "api":
        backends["api"] = {
            "primary": True,
            **_probe(_config.get("llm.api.base_url", "https://api.openai.com"), "/v1/models"),
        }
    else:
        backends[_backend] = {"primary": True, "reachable": "unknown"}

    primary_ok = any(v.get("reachable") for v in backends.values() if v.get("primary"))
    return {
        "status": "ok" if primary_ok else "degraded",
        "engine": "arbiter-engine",
        "version": _VERSION,
        "primary_backend": _backend,
        "backends": backends,
    }


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


@app.get("/metrics")
def get_metrics() -> dict:
    """M13-7: Per-endpoint request counts, error counts, and P50/P95 latency (ms).

    Counters reset on server restart.  The cache hit/miss ratio for the
    M13-4 LRU response cache is also included here.
    """
    snapshot: dict[str, Any] = {}
    with _metrics_lock:
        for route, m in _metrics.items():
            lats = sorted(m["latencies_ms"])
            n = len(lats)
            p50 = lats[n // 2] if n else 0.0
            p95 = lats[int(n * 0.95)] if n else 0.0
            avg = (m["total_ms"] / m["requests"]) if m["requests"] else 0.0
            snapshot[route] = {
                "requests": m["requests"],
                "errors": m["errors"],
                "avg_ms": round(avg, 1),
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
            }
    with _llm_cache_lock:
        cache_size = len(_llm_cache)
    return {
        "routes": snapshot,
        "llm_cache": {
            "entries": cache_size,
            "max_entries": _LLM_CACHE_MAX,
            "ttl_secs": _LLM_CACHE_TTL,
        },
    }


@app.get("/budget/{project_name}")
def budget_get(project_name: str) -> dict:
    """M13-6: Return accumulated AI call count and estimated token usage for a project."""
    with _budget_lock:
        data = dict(_budget.get(project_name, {"calls": 0, "estimated_tokens": 0}))
    return {"project": project_name, **data}


@app.post("/budget/{project_name}/reset")
def budget_reset(project_name: str) -> dict:
    """M13-6: Reset the AI budget counters for a project."""
    with _budget_lock:
        _budget[project_name] = {"calls": 0, "estimated_tokens": 0}
    return {"project": project_name, "status": "reset"}


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

    # M13-4: check LRU cache for identical prompt+project
    cached = _cache_get(msg.project, msg.message)
    if cached:
        history.append({"role": "user",      "content": msg.message})
        history.append({"role": "assistant", "content": cached})
        if len(history) > _MAX_CHAT_HISTORY_TURNS:
            history[:] = history[-_MAX_CHAT_HISTORY_TURNS:]
        return {"response": cached, "persona": persona, "cached": True}

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

    _cache_set(msg.project, msg.message, response)   # M13-4: populate cache
    _budget_record(msg.project, msg.message, response)  # M13-6: track budget

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
def git_diff(path: str = "workspace", file: str = "", staged: bool = False) -> dict:
    """Return the current diff for a workspace path.

    Pass ``?staged=true`` to see the staged (cached) diff.  P3-3
    """
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    git_args = ["diff"]
    if staged:
        git_args.append("--cached")
    if file:
        git_args += ["--", file]
    r = _run_git_cmd(git_args, root, timeout=10)
    return {"diff": r.get("stdout", ""), "staged": staged}


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

    # M13-4: serve from cache on exact prompt+project match
    cached = _cache_get(msg.project, msg.prompt)
    if cached:
        history.append({"role": "user",      "content": msg.prompt})
        history.append({"role": "assistant", "content": cached})
        return {"response": cached, "cached": True}

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
    _cache_set(msg.project, msg.prompt, response)   # M13-4
    _budget_record(msg.project, msg.prompt, response)  # M13-6
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


# ─────────────────────────────────────────────────────────────────────────────
# SSA0-5 / P1 — Projects panel: list all Arbiter-tracked projects
# Scans Projects/ for sub-directories that contain a roadmap.json and returns
# a summary entry for each one.  This is the data source for the Projects panel
# in the WPF IDE and the remote web UI.
# ─────────────────────────────────────────────────────────────────────────────

_PROJECTS_DIR = _BASE.parent.parent / "Projects"


@app.get("/projects/list")
def projects_list() -> dict:
    """Return all Arbiter-tracked projects found under the repo-root Projects/ directory.

    Each project is identified by the presence of a ``roadmap.json`` file inside
    its sub-folder.  Returns summary metadata so the WPF Projects panel and
    remote web UI can render a project list without reading every roadmap in full.
    """
    if not _PROJECTS_DIR.is_dir():
        return {"projects": []}

    projects = []
    for proj_dir in sorted(_PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir():
            continue
        roadmap_path = proj_dir / "roadmap.json"
        if not roadmap_path.exists():
            continue
        try:
            data = json.loads(roadmap_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

        # Tally phase/milestone progress
        phases = data.get("phases", data.get("milestones", []))
        total_tasks = sum(len(p.get("tasks", [])) for p in phases)
        done_tasks = sum(
            sum(1 for t in p.get("tasks", []) if t.get("status") == "done")
            for p in phases
        )
        active_phase = next(
            (p.get("name") or p.get("title") or p.get("id")
             for p in phases if p.get("status") in ("active", "in_progress")),
            None,
        )

        projects.append({
            "id":            proj_dir.name,
            "name":          data.get("project", proj_dir.name),
            "description":   data.get("description", ""),
            "version":       data.get("version", ""),
            "last_updated":  data.get("last_updated", ""),
            "tech_stack":    data.get("tech_stack", {}),
            "active_phase":  active_phase,
            "tasks_done":    done_tasks,
            "tasks_total":   total_tasks,
            "roadmap_path":  str(roadmap_path.relative_to(_BASE.parent.parent)),
        })

    return {"projects": projects, "total": len(projects)}


@app.get("/projects/{project_id}/roadmap")
def project_roadmap(project_id: str) -> dict:
    """Return the full roadmap.json for a specific tracked project."""
    # Prevent path traversal
    if "/" in project_id or "\\" in project_id or ".." in project_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid project id")
    roadmap_path = _PROJECTS_DIR / project_id / "roadmap.json"
    if not roadmap_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    try:
        return json.loads(roadmap_path.read_text(encoding="utf-8"))
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Could not read roadmap: {exc}")


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
        if req.whole_word:
            if not _re.search(pattern, original, flags):
                continue
        else:
            if req.find not in original:
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
    """Send an HTTP request and return the response (M9-6).

    Only http and https schemes are permitted to prevent unintended
    protocol handlers from being invoked.
    """
    import urllib.request
    import urllib.error
    import urllib.parse

    # Restrict to safe schemes only — block file://, ftp://, etc.
    parsed = urllib.parse.urlparse(req.url)
    if parsed.scheme not in ("http", "https"):
        return {"status": "error", "detail": f"Unsupported scheme '{parsed.scheme}'; only http and https are allowed"}

    method = req.method.upper()
    body_bytes = req.body.encode("utf-8") if req.body else None
    # Build request from validated URL
    safe_url = urllib.parse.urlunparse(parsed)
    http_req = urllib.request.Request(safe_url, data=body_bytes, method=method)
    for k, v in req.headers.items():
        http_req.add_header(k, v)

    try:
        with urllib.request.urlopen(http_req, timeout=req.timeout) as resp:
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

    logger.info("[apiclient/send] %s %s -> %d", method, safe_url, status_code)
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


# ═══════════════════════════════════════════════════════════════════════════════
#  M10 — Enhanced Chat & Conversational AI
# ═══════════════════════════════════════════════════════════════════════════════

# ── M10 shared state ──────────────────────────────────────────────────────────
_chat_branches: dict[str, dict[str, list[dict]]] = {}
_response_feedback: dict[str, list[dict]] = {}
_chat_bookmarks: dict[str, list[dict]] = {}
# Maps project → {"path": str, "content": str}
_active_file_contexts: dict[str, dict[str, str]] = {}
_message_threads: dict[str, dict[str, list[dict]]] = {}

_STREAM_CHUNK_WORDS = 8   # words per simulated streaming chunk (M10-7)

_FEEDBACK_FILE  = _BASE / "logs" / "response_feedback.json"
_BOOKMARKS_FILE = _BASE / "logs" / "chat_bookmarks.json"


def _load_json_file(path: Path, default: Any) -> Any:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _save_json_file(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        logger.warning("Could not save %s: %s", path, exc)


# Load persisted state on startup
_response_feedback = _load_json_file(_FEEDBACK_FILE, {})
_chat_bookmarks    = _load_json_file(_BOOKMARKS_FILE, {})

# ── Conversation templates (M10-2) ────────────────────────────────────────────
_CONV_TEMPLATES: dict[str, dict[str, str]] = {
    "code_review": {
        "name": "Code Review",
        "description": "Review code for quality, bugs, and best practices.",
        "prompt": "Please review the following code thoroughly. Identify bugs, code smells, security issues, and suggest improvements:\n\n```\n{code}\n```",
    },
    "explain_code": {
        "name": "Explain Code",
        "description": "Explain what a piece of code does in plain English.",
        "prompt": "Please explain the following code in clear, plain English. Describe what it does, how it works, and any important patterns used:\n\n```\n{code}\n```",
    },
    "write_tests": {
        "name": "Write Tests",
        "description": "Generate a comprehensive test suite for the given code.",
        "prompt": "Write a comprehensive test suite for the following code. Include unit tests, edge cases, and error scenarios:\n\n```\n{code}\n```",
    },
    "write_docs": {
        "name": "Write Documentation",
        "description": "Generate documentation for the given code.",
        "prompt": "Write clear, professional documentation for the following code. Include docstrings, parameter descriptions, return values, and usage examples:\n\n```\n{code}\n```",
    },
    "debug_error": {
        "name": "Debug Error",
        "description": "Help diagnose and fix an error or bug.",
        "prompt": "I need help debugging this error. Analyse the code, identify the root cause, and provide a fix:\n\n```\n{code}\n```",
    },
    "optimize_code": {
        "name": "Optimize Code",
        "description": "Suggest performance and efficiency improvements.",
        "prompt": "Analyse the following code for performance and efficiency. Suggest concrete optimizations with explanations:\n\n```\n{code}\n```",
    },
    "security_audit": {
        "name": "Security Audit",
        "description": "Identify security vulnerabilities and risks.",
        "prompt": "Perform a security audit of the following code. Identify all vulnerabilities (injection, auth flaws, data exposure, etc.) and suggest remediation:\n\n```\n{code}\n```",
    },
    "refactor_suggestion": {
        "name": "Refactor Suggestion",
        "description": "Suggest refactoring to improve code structure.",
        "prompt": "Suggest refactoring improvements for the following code. Focus on readability, maintainability, and adherence to SOLID principles:\n\n```\n{code}\n```",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-1: Chat session branching
# ───────────────────────────────────────────────────────────────────────────────

class _BranchCreateReq(BaseModel):
    project: str
    from_message_index: int
    branch_name: str = ""


class _BranchSwitchReq(BaseModel):
    project: str
    branch_id: str


@app.post("/chat/branch")
def chat_branch_create(req: _BranchCreateReq) -> dict:
    """Fork the conversation at from_message_index into a new branch.

    M10-1
    """
    history = _chat_histories.get(req.project, [])
    forked_history = history[:req.from_message_index]
    bid     = str(_uuid.uuid4())
    name    = req.branch_name or f"branch-{bid[:8]}"
    _chat_branches.setdefault(req.project, {})[bid] = {
        "name":    name,
        "history": list(forked_history),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    return {"branch_id": bid, "name": name, "message_count": len(forked_history)}


@app.get("/chat/branches/{project}")
def chat_branches_list(project: str) -> dict:
    """List all branches for a project.

    M10-1
    """
    branches = _chat_branches.get(project, {})
    result = [
        {
            "branch_id":     bid,
            "name":          info["name"],
            "message_count": len(info["history"]),
            "created_at":    info.get("created_at", ""),
        }
        for bid, info in branches.items()
    ]
    return {"project": project, "branches": result}


@app.post("/chat/branch/switch")
def chat_branch_switch(req: _BranchSwitchReq) -> dict:
    """Switch the active conversation to a saved branch.

    M10-1
    """
    branches = _chat_branches.get(req.project, {})
    if req.branch_id not in branches:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Branch '{req.branch_id}' not found")
    _chat_histories[req.project] = list(branches[req.branch_id]["history"])
    return {"status": "ok", "branch_id": req.branch_id,
            "message_count": len(_chat_histories[req.project])}


@app.delete("/chat/branch/{project}/{branch_id}")
def chat_branch_delete(project: str, branch_id: str) -> dict:
    """Delete a branch.

    M10-1
    """
    branches = _chat_branches.get(project, {})
    if branch_id not in branches:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Branch '{branch_id}' not found")
    del branches[branch_id]
    return {"status": "removed", "branch_id": branch_id}


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-2: Conversation templates
# ───────────────────────────────────────────────────────────────────────────────

class _TemplateApplyReq(BaseModel):
    template_id: str
    code: str = ""
    project: str = "default"


@app.get("/chat/templates")
def chat_templates_list() -> dict:
    """Return all built-in conversation templates.

    M10-2
    """
    templates = [
        {"template_id": tid, "name": t["name"], "description": t["description"]}
        for tid, t in _CONV_TEMPLATES.items()
    ]
    return {"templates": templates}


@app.post("/chat/templates/apply")
def chat_templates_apply(req: _TemplateApplyReq) -> dict:
    """Apply a template: fill in the prompt and get an LLM response.

    M10-2
    """
    if req.template_id not in _CONV_TEMPLATES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Template '{req.template_id}' not found")
    tpl    = _CONV_TEMPLATES[req.template_id]
    prompt = tpl["prompt"].replace("{code}", req.code or "(no code provided)")
    persona = _active_personas.get(req.project, "Arbiter")
    try:
        response = _llm.chat([
            {"role": "system", "content": f"You are {persona}, a helpful AI programming assistant."},
            {"role": "user", "content": prompt},
        ])
    except Exception as exc:
        response = f"[Arbiter Engine error] {exc}"
    history = _chat_histories.setdefault(req.project, [])
    history.append({"role": "user",      "content": prompt})
    history.append({"role": "assistant", "content": response})
    return {"response": response, "template_id": req.template_id, "persona": persona}


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-3: AI response rating & feedback
# ───────────────────────────────────────────────────────────────────────────────

class _FeedbackReq(BaseModel):
    project: str
    message_index: int
    rating: str          # "up" | "down"
    comment: str = ""


@app.post("/chat/feedback")
def chat_feedback_post(req: _FeedbackReq) -> dict:
    """Store feedback for a specific message.

    M10-3
    """
    if req.rating not in ("up", "down"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="rating must be 'up' or 'down'")
    record = {
        "message_index": req.message_index,
        "rating":        req.rating,
        "comment":       req.comment,
        "timestamp":     datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _response_feedback.setdefault(req.project, []).append(record)
    _save_json_file(_FEEDBACK_FILE, _response_feedback)
    return {"status": "ok", "feedback_count": len(_response_feedback[req.project])}


@app.get("/chat/feedback/{project}")
def chat_feedback_get(project: str) -> dict:
    """Return all feedback for a project.

    M10-3
    """
    return {"project": project, "feedback": _response_feedback.get(project, [])}


@app.get("/chat/feedback/summary")
def chat_feedback_summary() -> dict:
    """Return aggregate feedback statistics.

    M10-3
    """
    total = 0
    up    = 0
    down  = 0
    by_project: dict[str, dict[str, int]] = {}
    for proj, records in _response_feedback.items():
        p_up   = sum(1 for r in records if r.get("rating") == "up")
        p_down = sum(1 for r in records if r.get("rating") == "down")
        by_project[proj] = {"up": p_up, "down": p_down, "total": len(records)}
        total += len(records)
        up    += p_up
        down  += p_down
    return {"total": total, "up": up, "down": down, "by_project": by_project}


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-4: Chat message bookmarks & pinning
# ───────────────────────────────────────────────────────────────────────────────

class _BookmarkReq(BaseModel):
    project: str
    message_index: int
    note: str = ""
    pinned: bool = False


class _BookmarkPinReq(BaseModel):
    project: str
    bookmark_id: str
    pinned: bool


@app.post("/chat/bookmark")
def chat_bookmark_create(req: _BookmarkReq) -> dict:
    """Bookmark a message in the conversation.

    M10-4
    """
    history = _chat_histories.get(req.project, [])
    if req.message_index < 0 or req.message_index >= len(history):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="message_index out of range")
    msg = history[req.message_index]
    bid = str(_uuid.uuid4())
    bookmark = {
        "bookmark_id":    bid,
        "message_index":  req.message_index,
        "role":           msg.get("role", ""),
        "content_preview": msg.get("content", "")[:120],
        "note":           req.note,
        "pinned":         req.pinned,
        "created_at":     datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _chat_bookmarks.setdefault(req.project, []).append(bookmark)
    _save_json_file(_BOOKMARKS_FILE, _chat_bookmarks)
    return {"bookmark_id": bid, "status": "ok"}


@app.get("/chat/bookmarks/{project}")
def chat_bookmarks_list(project: str) -> dict:
    """Return all bookmarks for a project, pinned first.

    M10-4
    """
    bookmarks = _chat_bookmarks.get(project, [])
    sorted_bm = sorted(bookmarks, key=lambda b: (0 if b.get("pinned") else 1, b.get("created_at", "")))
    return {"project": project, "bookmarks": sorted_bm}


@app.delete("/chat/bookmark/{project}/{bookmark_id}")
def chat_bookmark_delete(project: str, bookmark_id: str) -> dict:
    """Delete a bookmark.

    M10-4
    """
    bookmarks = _chat_bookmarks.get(project, [])
    new_bms   = [b for b in bookmarks if b.get("bookmark_id") != bookmark_id]
    if len(new_bms) == len(bookmarks):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Bookmark '{bookmark_id}' not found")
    _chat_bookmarks[project] = new_bms
    _save_json_file(_BOOKMARKS_FILE, _chat_bookmarks)
    return {"status": "removed", "bookmark_id": bookmark_id}


@app.post("/chat/bookmark/pin")
def chat_bookmark_pin(req: _BookmarkPinReq) -> dict:
    """Toggle the pinned state of a bookmark.

    M10-4
    """
    bookmarks = _chat_bookmarks.get(req.project, [])
    for bm in bookmarks:
        if bm.get("bookmark_id") == req.bookmark_id:
            bm["pinned"] = req.pinned
            _save_json_file(_BOOKMARKS_FILE, _chat_bookmarks)
            return {"status": "ok", "bookmark_id": req.bookmark_id, "pinned": req.pinned}
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Bookmark '{req.bookmark_id}' not found")


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-5: Multi-modal input (image context)
# ───────────────────────────────────────────────────────────────────────────────

class _ImageChatReq(BaseModel):
    project: str
    message: str
    image_base64: str
    image_name: str = "image.png"


@app.post("/chat/image")
def chat_image(req: _ImageChatReq) -> dict:
    """Send a chat message with an image as context.

    The image base64 is described in the prompt; vision-capable LLMs will
    receive the actual data while text-only LLMs get a description.

    M10-5
    """
    augmented = (
        f"[Image: {req.image_name}] (base64 image provided — "
        "vision-capable models will use the actual pixel data)\n\n"
        f"{req.message}"
    )
    persona = _active_personas.get(req.project, "Arbiter")
    history = _chat_histories.setdefault(req.project, [])
    try:
        response = _llm.chat([
            {"role": "system", "content": f"You are {persona}, a helpful AI programming assistant."},
            *history[-10:],
            {"role": "user", "content": augmented},
        ])
    except Exception as exc:
        response = f"[Arbiter Engine error] {exc}"
    history.append({"role": "user",      "content": augmented})
    history.append({"role": "assistant", "content": response})
    if len(history) > _MAX_CHAT_HISTORY_TURNS:
        history[:] = history[-_MAX_CHAT_HISTORY_TURNS:]
    return {"response": response, "persona": persona}


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-6: Smart context switching
# ───────────────────────────────────────────────────────────────────────────────

class _FileContextReq(BaseModel):
    project: str
    file_path: str


@app.post("/chat/context/file")
def chat_context_file_set(req: _FileContextReq) -> dict:
    """Set the active file context for a project (reads up to 4000 chars).

    M10-6
    """
    try:
        p = Path(req.file_path)
        if not p.is_file():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
        content = p.read_text(encoding="utf-8", errors="replace")[:4000]
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc))
    _active_file_contexts[req.project] = {"path": req.file_path, "content": content}
    return {
        "status":          "ok",
        "file_path":       req.file_path,
        "content_preview": content[:200],
    }


@app.get("/chat/context/file/{project}")
def chat_context_file_get(project: str) -> dict:
    """Return the active file context for a project.

    M10-6
    """
    ctx     = _active_file_contexts.get(project, {})
    fp      = ctx.get("path", "")
    content = ctx.get("content", "")
    return {"project": project, "file_path": fp, "content_preview": content[:200]}


@app.delete("/chat/context/file/{project}")
def chat_context_file_clear(project: str) -> dict:
    """Clear the active file context for a project.

    M10-6
    """
    _active_file_contexts.pop(project, None)
    return {"status": "cleared", "project": project}


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-7: Real-time streaming
# ───────────────────────────────────────────────────────────────────────────────

class _StreamChatReq(BaseModel):
    project: str
    message: str


@app.post("/chat/stream")
async def chat_stream(req: _StreamChatReq):
    """Stream the AI response token-by-token as Server-Sent Events.

    M10-7 / M13-1: Synchronous LLM calls are now executed in a thread-pool
    via asyncio.to_thread() so the event loop is never blocked.
    """
    import json as _json_mod

    persona = _active_personas.get(req.project, "Arbiter")
    history = _chat_histories.setdefault(req.project, [])
    messages = [
        {"role": "system", "content": f"You are {persona}."},
        *history[-10:],
        {"role": "user", "content": req.message},
    ]

    async def _generate():
        full: str = ""
        try:
            # M13-1: run blocking LLM call in a thread to avoid event-loop stall
            full = await asyncio.to_thread(_llm.chat, messages)
            # Simulate streaming: split into ~8-word chunks
            words = full.split()
            for i in range(0, len(words), _STREAM_CHUNK_WORDS):
                chunk = " ".join(words[i:i + _STREAM_CHUNK_WORDS])
                yield f"data: {_json_mod.dumps({'token': chunk, 'done': False})}\n\n"
                await asyncio.sleep(0.03)
        except Exception as exc:
            full = f"[Arbiter Engine error] {exc}"
            yield f"data: {_json_mod.dumps({'token': full, 'done': False})}\n\n"

        history.append({"role": "user",      "content": req.message})
        history.append({"role": "assistant", "content": full})
        if len(history) > _MAX_CHAT_HISTORY_TURNS:
            history[:] = history[-_MAX_CHAT_HISTORY_TURNS:]
        _budget_record(req.project, req.message, full)

        yield f"data: {_json_mod.dumps({'token': '', 'done': True, 'full_response': full})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-8: Message threading
# ───────────────────────────────────────────────────────────────────────────────

class _ThreadReq(BaseModel):
    project: str
    parent_message_index: int
    message: str


@app.post("/chat/thread")
def chat_thread_create(req: _ThreadReq) -> dict:
    """Create a threaded reply to a specific message.

    M10-8
    """
    history = _chat_histories.get(req.project, [])
    if req.parent_message_index < 0 or req.parent_message_index >= len(history):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="parent_message_index out of range")
    parent_msg = history[req.parent_message_index]
    thread_id  = str(req.parent_message_index)
    persona    = _active_personas.get(req.project, "Arbiter")
    thread_ctx = _message_threads.get(req.project, {}).get(thread_id, [])
    try:
        response = _llm.chat([
            {"role": "system", "content": f"You are {persona}. You are replying in a sub-thread."},
            {"role": "user",   "content": f"[Parent message]: {parent_msg.get('content', '')[:500]}"},
            *thread_ctx[-6:],
            {"role": "user",   "content": req.message},
        ])
    except Exception as exc:
        response = f"[Arbiter Engine error] {exc}"

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _message_threads.setdefault(req.project, {}).setdefault(thread_id, []).extend([
        {"role": "user",      "content": req.message,  "timestamp": ts},
        {"role": "assistant", "content": response,     "timestamp": ts},
    ])
    return {"thread_id": thread_id, "response": response, "persona": persona}


@app.get("/chat/threads/{project}")
def chat_threads_list(project: str) -> dict:
    """List all thread metadata for a project.

    M10-8
    """
    threads = _message_threads.get(project, {})
    result  = [
        {"parent_message_index": int(pid), "message_count": len(msgs)}
        for pid, msgs in threads.items()
    ]
    return {"project": project, "threads": result}


@app.get("/chat/thread/{project}/{parent_message_index}")
def chat_thread_get(project: str, parent_message_index: int) -> dict:
    """Return all messages in a specific thread.

    M10-8
    """
    thread_id = str(parent_message_index)
    msgs      = _message_threads.get(project, {}).get(thread_id, [])
    return {"project": project, "parent_message_index": parent_message_index, "messages": msgs}


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-9: Chat analytics dashboard
# ───────────────────────────────────────────────────────────────────────────────

@app.get("/chat/analytics")
def chat_analytics(project: str = "") -> dict:
    """Return aggregated chat analytics.

    M10-9
    """
    scope = (
        {project: _chat_histories.get(project, [])}
        if project
        else _chat_histories
    )

    total_messages    = 0
    by_project:  dict[str, int] = {}
    assistant_lengths: list[int] = []

    for proj, hist in scope.items():
        by_project[proj] = len(hist)
        total_messages  += len(hist)
        for msg in hist:
            if msg.get("role") == "assistant":
                assistant_lengths.append(len(msg.get("content", "")))

    most_active = max(by_project, key=lambda k: by_project[k]) if by_project else ""

    # persona_usage
    persona_usage: dict[str, int] = {}
    for proj, persona in _active_personas.items():
        if not project or proj == project:
            persona_usage[persona] = persona_usage.get(persona, 0) + by_project.get(proj, 0)

    # feedback summary
    fb_up   = sum(1 for recs in _response_feedback.values() for r in recs if r.get("rating") == "up")
    fb_down = sum(1 for recs in _response_feedback.values() for r in recs if r.get("rating") == "down")

    # bookmark count
    bookmark_count = sum(len(bms) for bms in _chat_bookmarks.values())

    # branch count
    branch_count = sum(len(branches) for branches in _chat_branches.values())

    # thread count
    thread_count = sum(
        len(msgs)
        for threads in _message_threads.values()
        for msgs in threads.values()
    )

    avg_len = sum(assistant_lengths) // len(assistant_lengths) if assistant_lengths else 0

    return {
        "total_messages":          total_messages,
        "by_project":              by_project,
        "most_active_project":     most_active,
        "persona_usage":           persona_usage,
        "feedback_summary":        {"up": fb_up, "down": fb_down},
        "bookmark_count":          bookmark_count,
        "branch_count":            branch_count,
        "thread_count":            thread_count,
        "average_response_length": avg_len,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  M10-10: Conversation summarization
# ───────────────────────────────────────────────────────────────────────────────

class _SummarizeReq(BaseModel):
    project: str
    max_turns: int = 20


@app.post("/chat/summarize")
def chat_summarize(req: _SummarizeReq) -> dict:
    """Summarize the oldest portion of a long conversation to save context.

    M10-10
    """
    history = _chat_histories.get(req.project, [])
    if len(history) <= req.max_turns:
        return {
            "status":          "no_action",
            "original_turns":  len(history),
            "compressed_turns": len(history),
            "summary_preview": "",
        }
    half        = len(history) // 2
    to_summarize = history[:half]
    remaining    = history[half:]
    text_block   = "\n".join(
        f"{m.get('role','?')}: {m.get('content','')[:300]}" for m in to_summarize
    )
    try:
        summary = _llm.chat([
            {"role": "system", "content":
                "Summarise the following conversation excerpt concisely, preserving key decisions, "
                "code snippets, and conclusions. Start with '[Summary]'."},
            {"role": "user", "content": text_block[:3000]},
        ])
    except Exception as exc:
        summary = f"[Summary] (auto-generated) — {exc}"

    new_history = [{"role": "system", "content": summary}] + remaining
    _chat_histories[req.project] = new_history
    return {
        "status":           "ok",
        "original_turns":   len(history),
        "compressed_turns": len(new_history),
        "summary_preview":  summary[:200],
    }


@app.get("/chat/summary/{project}")
def chat_summary_get(project: str) -> dict:
    """Return the current summary entry if one exists in history.

    M10-10
    """
    history = _chat_histories.get(project, [])
    for msg in history:
        if msg.get("role") == "system" and str(msg.get("content", "")).startswith("[Summary]"):
            return {"project": project, "summary": msg["content"]}
    return {"project": project, "summary": None}


# ═══════════════════════════════════════════════════════════════════════════════
#  M11 — Advanced AI Intelligence
# ═══════════════════════════════════════════════════════════════════════════════

# ── M11 shared state ──────────────────────────────────────────────────────────

_MODEL_ROUTING_RULES: list[dict] = [
    {"keywords": ["vulnerability", "CVE", "injection", "XSS", "CSRF", "auth", "exploit", "pentest"],
     "task_type": "security", "preferred_backend": "ollama"},
    {"keywords": ["test", "unittest", "pytest", "spec", "assert", "coverage", "mock"],
     "task_type": "testing", "preferred_backend": "ollama"},
    {"keywords": ["document", "docstring", "README", "javadoc", "comment", "explain"],
     "task_type": "documentation", "preferred_backend": "ollama"},
    {"keywords": ["refactor", "clean", "SOLID", "pattern", "restructure", "simplify"],
     "task_type": "refactoring", "preferred_backend": "ollama"},
    {"keywords": ["optimize", "performance", "speed", "memory", "profil", "benchmark"],
     "task_type": "performance", "preferred_backend": "ollama"},
    {"keywords": [],  # default catch-all
     "task_type": "general", "preferred_backend": "ollama"},
]

_SPECIALIST_AGENTS: dict[str, dict] = {
    "security_auditor": {
        "name":        "Security Auditor",
        "description": "Expert in identifying security vulnerabilities, CVEs, and secure coding practices.",
        "system_prompt": (
            "You are an expert security auditor specialising in application security. "
            "Identify vulnerabilities (OWASP Top 10, injection, broken auth, data exposure, etc.), "
            "assess severity, and provide concrete remediation steps. Be thorough and precise."
        ),
        "task_type": "security",
    },
    "devops_engineer": {
        "name":        "DevOps Engineer",
        "description": "Expert in CI/CD, infrastructure-as-code, containers, and cloud deployment.",
        "system_prompt": (
            "You are a senior DevOps engineer. You specialise in CI/CD pipelines, Docker, Kubernetes, "
            "Terraform, and cloud platforms (AWS, Azure, GCP). Provide practical, production-ready guidance."
        ),
        "task_type": "devops",
    },
    "documentation_writer": {
        "name":        "Documentation Writer",
        "description": "Expert in writing clear technical documentation, API docs, and READMEs.",
        "system_prompt": (
            "You are a professional technical writer. Write clear, accurate, well-structured documentation "
            "including API references, tutorials, READMEs, and inline code comments. Follow best practices."
        ),
        "task_type": "documentation",
    },
    "test_engineer": {
        "name":        "Test Engineer",
        "description": "Expert in writing comprehensive test suites and improving test coverage.",
        "system_prompt": (
            "You are an expert test engineer. Write comprehensive test suites covering unit, integration, "
            "and edge-case scenarios. Use appropriate frameworks (pytest, Jest, xUnit, etc.) and follow "
            "AAA (Arrange-Act-Assert) patterns. Aim for high coverage and meaningful assertions."
        ),
        "task_type": "testing",
    },
    "performance_analyst": {
        "name":        "Performance Analyst",
        "description": "Expert in profiling, benchmarking, and optimising code performance.",
        "system_prompt": (
            "You are a performance specialist. Analyse code for bottlenecks, memory leaks, and inefficiencies. "
            "Suggest data structure improvements, algorithm optimisations, and caching strategies. "
            "Provide measurable recommendations."
        ),
        "task_type": "performance",
    },
    "database_architect": {
        "name":        "Database Architect",
        "description": "Expert in database schema design, query optimisation, and data modelling.",
        "system_prompt": (
            "You are a senior database architect. Design efficient schemas, write optimised queries, "
            "advise on indexing strategies, normalisation, and choose the right database technology "
            "(relational, document, graph, time-series) for the use case."
        ),
        "task_type": "database",
    },
}

_knowledge_graph: dict[str, Any] = {"nodes": [], "edges": [], "last_updated": ""}
_KG_FILE = _BASE / "logs" / "knowledge_graph.json"
_knowledge_graph = _load_json_file(_KG_FILE, {"nodes": [], "edges": [], "last_updated": ""})

_code_index: dict[str, dict[str, Any]] = {}

_persona_feedback_log: dict[str, list[dict]] = {}
_PERSONA_FB_FILE = _BASE / "logs" / "persona_feedback.json"
_persona_feedback_log = _load_json_file(_PERSONA_FB_FILE, {})

_pair_sessions: dict[str, dict] = {}

_SPECIALIST_AGENTS_FILE = _BASE / "logs" / "specialist_agents.json"
# Merge any persisted custom agents
for _k, _v in _load_json_file(_SPECIALIST_AGENTS_FILE, {}).items():
    if _k not in _SPECIALIST_AGENTS:
        _SPECIALIST_AGENTS[_k] = _v


# ═══════════════════════════════════════════════════════════════════════════════
#  M11-1: Multi-model routing
# ───────────────────────────────────────────────────────────────────────────────

class _RouteReq(BaseModel):
    query: str
    available_backends: list[str] = []


class _RoutingRuleReq(BaseModel):
    keywords: list[str]
    task_type: str
    preferred_backend: str


@app.post("/ai/route")
def ai_route(req: _RouteReq) -> dict:
    """Route a query to the best backend based on content.

    M11-1
    """
    q_lower = req.query.lower()
    for rule in _MODEL_ROUTING_RULES:
        kws = rule.get("keywords", [])
        if not kws:
            # default rule
            backend = rule["preferred_backend"]
            if req.available_backends and backend not in req.available_backends:
                backend = req.available_backends[0]
            return {
                "task_type":        rule["task_type"],
                "preferred_backend": backend,
                "matched_rule":     rule,
                "confidence":       0.5,
            }
        matched = [kw for kw in kws if kw.lower() in q_lower]
        if matched:
            backend = rule["preferred_backend"]
            if req.available_backends and backend not in req.available_backends:
                backend = req.available_backends[0]
            confidence = min(1.0, len(matched) / max(len(kws), 1))
            return {
                "task_type":        rule["task_type"],
                "preferred_backend": backend,
                "matched_rule":     rule,
                "confidence":       round(confidence, 2),
            }
    return {"task_type": "general", "preferred_backend": "ollama", "matched_rule": None, "confidence": 0.0}


@app.get("/ai/routing/rules")
def ai_routing_rules_list() -> dict:
    """Return all routing rules.

    M11-1
    """
    return {"rules": _MODEL_ROUTING_RULES}


@app.post("/ai/routing/rules")
def ai_routing_rules_add(req: _RoutingRuleReq) -> dict:
    """Add a custom routing rule (inserted before the default catch-all).

    M11-1
    """
    rule = {
        "keywords":          req.keywords,
        "task_type":         req.task_type,
        "preferred_backend": req.preferred_backend,
    }
    # Insert before the default (last) rule
    _MODEL_ROUTING_RULES.insert(len(_MODEL_ROUTING_RULES) - 1, rule)
    return {"status": "ok", "rule": rule, "total_rules": len(_MODEL_ROUTING_RULES)}


# ═══════════════════════════════════════════════════════════════════════════════
#  M11-2: AI agents marketplace
# ───────────────────────────────────────────────────────────────────────────────

class _SpecialistRunReq(BaseModel):
    agent_name: str
    task: str
    code: str = ""
    project: str = ""


class _SpecialistInstallReq(BaseModel):
    name: str
    description: str
    system_prompt: str


@app.get("/agents/specialist")
def agents_specialist_list() -> dict:
    """Return the specialist agent catalog.

    M11-2
    """
    agents = [
        {
            "agent_id":            aid,
            "name":                info["name"],
            "description":         info["description"],
            "task_type":           info.get("task_type", "general"),
            "system_prompt_preview": info["system_prompt"][:100],
        }
        for aid, info in _SPECIALIST_AGENTS.items()
    ]
    return {"agents": agents}


@app.post("/agents/specialist/run")
def agents_specialist_run(req: _SpecialistRunReq) -> dict:
    """Run a specialist agent on a task.

    M11-2
    """
    if req.agent_name not in _SPECIALIST_AGENTS:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_name}' not found")
    agent  = _SPECIALIST_AGENTS[req.agent_name]
    prompt = req.task
    if req.code:
        prompt += f"\n\n```\n{req.code[:4000]}\n```"
    try:
        response = _llm.chat([
            {"role": "system", "content": agent["system_prompt"]},
            {"role": "user",   "content": prompt},
        ])
    except Exception as exc:
        response = f"[Arbiter Engine error] {exc}"
    if req.project:
        history = _chat_histories.setdefault(req.project, [])
        history.append({"role": "user",      "content": f"[{agent['name']}] {prompt[:200]}"})
        history.append({"role": "assistant", "content": response})
    return {"agent_name": req.agent_name, "response": response, "task_type": agent.get("task_type", "general")}


@app.post("/agents/specialist/install")
def agents_specialist_install(req: _SpecialistInstallReq) -> dict:
    """Install a custom specialist agent.

    M11-2
    """
    if not req.name.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Agent name must not be empty")
    import re as _re
    agent_id = _re.sub(r"[^a-z0-9_]", "_", req.name.lower().strip().replace(" ", "_"))
    _SPECIALIST_AGENTS[agent_id] = {
        "name":          req.name,
        "description":   req.description,
        "system_prompt": req.system_prompt,
        "task_type":     "custom",
    }
    # Persist custom agents
    custom = {k: v for k, v in _SPECIALIST_AGENTS.items() if v.get("task_type") == "custom"}
    _save_json_file(_SPECIALIST_AGENTS_FILE, custom)
    return {"status": "ok", "agent_id": agent_id}


# ═══════════════════════════════════════════════════════════════════════════════
#  M11-3: Code generation from requirements
# ───────────────────────────────────────────────────────────────────────────────

class _GenerateFromReqReq(BaseModel):
    requirements: str
    language: str = "python"
    project: str = ""
    module_name: str = ""


@app.post("/ai/generate/from-requirements")
def ai_generate_from_requirements(req: _GenerateFromReqReq) -> dict:
    """Generate a full implementation from natural-language requirements.

    M11-3
    """
    module_hint = f" for module '{req.module_name}'" if req.module_name else ""
    try:
        code = _llm.chat([
            {"role": "system", "content":
                f"You are an expert {req.language} developer. Generate a complete, production-ready "
                f"implementation{module_hint}. Include all necessary imports, classes, functions, "
                "error handling, and inline comments. Output only code."},
            {"role": "user", "content": req.requirements},
        ])
    except Exception as exc:
        code = f"# [Arbiter Engine error] {exc}"
    token_estimate = len(code.split())
    if req.project:
        history = _chat_histories.setdefault(req.project, [])
        history.append({"role": "user",      "content": f"Generate {req.language} code: {req.requirements[:100]}"})
        history.append({"role": "assistant", "content": code})
    return {
        "code":            code,
        "language":        req.language,
        "module_name":     req.module_name,
        "token_estimate":  token_estimate,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  M11-4: Cross-project knowledge graph
# ───────────────────────────────────────────────────────────────────────────────

class _KGScanReq(BaseModel):
    projects: list[str]
    scan_types: list[str] = ["functions", "classes", "imports"]


def _extract_symbols(file_path: Path, scan_types: list[str]) -> tuple[list[dict], list[dict]]:
    """Extract symbol nodes and relationship edges from a source file."""
    import re as _re_local
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")[:10240]
    except Exception:
        return [], []
    nodes: list[dict] = []
    edges: list[dict] = []
    fp    = str(file_path)
    if "functions" in scan_types:
        for m in _re_local.finditer(r"(?:def |function |func |void |public \w+ )\s*(\w+)\s*\(", content):
            nodes.append({"file": fp, "name": m.group(1), "type": "function"})
    if "classes" in scan_types:
        for m in _re_local.finditer(r"class\s+(\w+)\s*(?:\(([^)]*)\))?", content):
            nodes.append({"file": fp, "name": m.group(1), "type": "class"})
            if m.group(2):
                for parent in m.group(2).split(","):
                    parent = parent.strip()
                    if parent and parent not in ("object", ""):
                        edges.append({"from": m.group(1), "to": parent, "relation": "inherits", "file": fp})
    if "imports" in scan_types:
        for m in _re_local.finditer(r"(?:^import |^from )\s*([\w.]+)", content, _re_local.MULTILINE):
            edges.append({"from": fp, "to": m.group(1), "relation": "imports", "file": fp})
    return nodes, edges


@app.post("/knowledge/scan")
def knowledge_scan(req: _KGScanReq) -> dict:
    """Scan projects and build the cross-project knowledge graph.

    M11-4
    """
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    projects_scanned = 0

    for project in req.projects:
        p = Path(project)
        if not p.is_dir():
            base = _ALLOWED_ROOTS.get("projects", _BASE / "workspace")
            p    = base / project
        if not p.is_dir():
            continue
        projects_scanned += 1
        count = 0
        for ext in ("*.py", "*.js", "*.ts", "*.cs"):
            for fp in p.rglob(ext):
                if any(part.startswith(".") for part in fp.parts):
                    continue
                if count >= 200:
                    break
                nodes, edges = _extract_symbols(fp, req.scan_types)
                all_nodes.extend(nodes)
                all_edges.extend(edges)
                count += 1

    _knowledge_graph["nodes"]        = all_nodes
    _knowledge_graph["edges"]        = all_edges
    _knowledge_graph["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_json_file(_KG_FILE, _knowledge_graph)

    return {
        "nodes":            len(all_nodes),
        "edges":            len(all_edges),
        "projects_scanned": projects_scanned,
    }


@app.get("/knowledge/graph")
def knowledge_graph_get() -> dict:
    """Return the full knowledge graph.

    M11-4
    """
    return {
        "nodes":        _knowledge_graph["nodes"],
        "edges":        _knowledge_graph["edges"],
        "last_updated": _knowledge_graph.get("last_updated", ""),
    }


@app.get("/knowledge/search")
def knowledge_search(q: str = "") -> dict:
    """Search the knowledge graph for nodes whose name contains q.

    M11-4
    """
    if not q:
        return {"results": []}
    q_lower = q.lower()
    matched_nodes = [n for n in _knowledge_graph["nodes"] if q_lower in n.get("name", "").lower()]
    node_names    = {n["name"] for n in matched_nodes}
    related_edges = [
        e for e in _knowledge_graph["edges"]
        if e.get("from") in node_names or e.get("to") in node_names
    ]
    return {"results": matched_nodes, "edges": related_edges}


# ═══════════════════════════════════════════════════════════════════════════════
#  M11-5: AI-powered test intelligence
# ───────────────────────────────────────────────────────────────────────────────

class _TestsGenerateReq(BaseModel):
    code: str
    language: str = "python"
    project: str = ""
    test_framework: str = ""


class _TestsCoverageReq(BaseModel):
    code: str
    existing_tests: str = ""
    language: str = "python"


@app.post("/ai/tests/generate")
def ai_tests_generate(req: _TestsGenerateReq) -> dict:
    """Generate a comprehensive test suite for the given code.

    M11-5
    """
    fw_hint = f" using {req.test_framework}" if req.test_framework else ""
    try:
        tests = _llm.chat([
            {"role": "system", "content":
                f"You are an expert {req.language} test engineer. Generate a comprehensive test suite"
                f"{fw_hint}. Cover happy paths, edge cases, and error scenarios. Output only test code."},
            {"role": "user", "content": req.code[:4000]},
        ])
    except Exception as exc:
        tests = f"# [Arbiter Engine error] {exc}"

    if req.test_framework:
        framework = req.test_framework
    elif req.language == "python":
        framework = "pytest"
    elif req.language in ("javascript", "typescript"):
        framework = "jest"
    else:
        framework = "xunit"
    return {
        "tests":              tests,
        "language":           req.language,
        "framework":          framework,
        "estimated_coverage": "70-90% (AI estimate)",
    }


@app.post("/ai/tests/coverage-hints")
def ai_tests_coverage_hints(req: _TestsCoverageReq) -> dict:
    """Identify untested edge cases and suggest coverage improvements.

    M11-5
    """
    existing_hint = f"\n\nExisting tests:\n```\n{req.existing_tests[:2000]}\n```" if req.existing_tests else ""
    try:
        raw = _llm.chat([
            {"role": "system", "content":
                "You are a test coverage expert. Identify untested edge cases, missing branches, and "
                "priority improvements. Respond with JSON: "
                '{"suggestions": [...], "untested_paths": [...], "priority_hints": [...]}'},
            {"role": "user", "content": f"```{req.language}\n{req.code[:3000]}\n```{existing_hint}"},
        ])
        data = json.loads(raw)
    except Exception:
        data = {
            "suggestions":    ["Add tests for error/exception paths", "Test boundary conditions"],
            "untested_paths": ["Error handling branches", "Empty/null inputs"],
            "priority_hints": ["Focus on public API methods first"],
        }
    return {
        "suggestions":    data.get("suggestions", []),
        "untested_paths": data.get("untested_paths", []),
        "priority_hints": data.get("priority_hints", []),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  M11-6: Semantic code search
# ───────────────────────────────────────────────────────────────────────────────

class _SemanticIndexReq(BaseModel):
    project: str
    max_files: int = 100


class _SemanticSearchReq(BaseModel):
    query: str
    project: str = ""
    top_k: int = 5


@app.post("/search/semantic/index")
def search_semantic_index(req: _SemanticIndexReq) -> dict:
    """Index a project's source files for semantic search.

    M11-6
    """
    import re as _re_local

    p = Path(req.project)
    if not p.is_dir():
        base = _ALLOWED_ROOTS.get("projects", _BASE / "workspace")
        p    = base / req.project
    if not p.is_dir():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Project directory not found: {req.project}")

    files_indexed   = 0
    symbols_indexed = 0

    for ext in ("*.py", "*.js", "*.ts", "*.cs"):
        for fp in p.rglob(ext):
            if any(part.startswith(".") for part in fp.parts):
                continue
            if files_indexed >= req.max_files:
                break
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")[:8000]
            except Exception:
                continue
            symbols: list[str] = []
            for pattern in (r"def (\w+)\s*\(", r"class (\w+)", r"function (\w+)\s*\(",
                             r"const (\w+)\s*=", r"public \w+ (\w+)\s*\("):
                symbols.extend(_re_local.findall(pattern, content))
            _code_index[str(fp)] = {
                "content":      content[:2000],
                "symbols":      list(set(symbols)),
                "last_indexed": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "project":      req.project,
            }
            files_indexed   += 1
            symbols_indexed += len(symbols)

    return {"files_indexed": files_indexed, "symbols_indexed": symbols_indexed}


@app.post("/search/semantic")
def search_semantic(req: _SemanticSearchReq) -> dict:
    """Semantic code search: find relevant symbols/files using LLM ranking.

    M11-6
    """
    scope = {
        fp: info for fp, info in _code_index.items()
        if not req.project or info.get("project") == req.project
    }
    if not scope:
        return {"results": []}

    # Build a compact index summary for the LLM
    index_lines: list[str] = []
    for fp, info in list(scope.items())[:50]:
        syms = ", ".join(info.get("symbols", [])[:10])
        index_lines.append(f"{fp}: [{syms}]")
    index_text = "\n".join(index_lines)

    try:
        raw = _llm.chat([
            {"role": "system", "content":
                f"Given a code index and a search query, return the top {req.top_k} most relevant "
                "files/symbols as JSON array: "
                '[{"file": "...", "symbol": "...", "relevance_score": 0.0-1.0, "snippet": "..."}]. '
                "Output ONLY the JSON array."},
            {"role": "user", "content": f"Query: {req.query}\n\nIndex:\n{index_text}"},
        ])
        results = json.loads(raw)
        if not isinstance(results, list):
            raise ValueError("Not a list")
    except Exception:
        # Fallback: keyword match
        q_lower = req.query.lower()
        results = []
        for fp, info in scope.items():
            score = sum(1 for s in info.get("symbols", []) if q_lower in s.lower())
            if score:
                results.append({
                    "file":            fp,
                    "symbol":          ", ".join(s for s in info["symbols"] if q_lower in s.lower())[:50],
                    "relevance_score": min(1.0, score / 5),
                    "snippet":         info["content"][:120],
                })
        results = sorted(results, key=lambda x: x["relevance_score"], reverse=True)[:req.top_k]

    return {"results": results[:req.top_k]}


@app.get("/search/semantic/index/status")
def search_semantic_index_status() -> dict:
    """Return current semantic index statistics.

    M11-6
    """
    projects: set[str] = set()
    total_symbols = 0
    for info in _code_index.values():
        projects.add(info.get("project", ""))
        total_symbols += len(info.get("symbols", []))
    return {
        "files_indexed":   len(_code_index),
        "total_symbols":   total_symbols,
        "projects":        list(projects),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  M11-7: Adaptive persona learning
# ───────────────────────────────────────────────────────────────────────────────

class _PersonaFeedbackReq(BaseModel):
    persona: str
    rating: str          # "up" | "down"
    comment: str = ""
    project: str = ""


class _PersonaAdaptReq(BaseModel):
    persona: str


@app.post("/persona/feedback")
def persona_feedback_post(req: _PersonaFeedbackReq) -> dict:
    """Log feedback for a persona.

    M11-7
    """
    if req.rating not in ("up", "down"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="rating must be 'up' or 'down'")
    record = {
        "rating":    req.rating,
        "comment":   req.comment,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "project":   req.project,
    }
    _persona_feedback_log.setdefault(req.persona, []).append(record)
    _save_json_file(_PERSONA_FB_FILE, _persona_feedback_log)
    return {"status": "ok", "persona": req.persona,
            "feedback_count": len(_persona_feedback_log[req.persona])}


@app.post("/persona/adapt")
def persona_adapt(req: _PersonaAdaptReq) -> dict:
    """Use feedback to suggest improvements to a persona's system prompt.

    M11-7
    """
    feedback = _persona_feedback_log.get(req.persona, [])
    # Gather current prompt preview
    from_custom = _custom_personas.get(req.persona, "")
    current_preview = from_custom[:200] if from_custom else f"Default persona: {req.persona}"

    feedback_text = "\n".join(
        f"- {'👍' if r['rating']=='up' else '👎'} {r.get('comment','(no comment)')}"
        for r in feedback[-20:]
    )
    try:
        suggestion = _llm.chat([
            {"role": "system", "content":
                "You are an AI persona tuner. Given feedback on a persona and its current system prompt, "
                "suggest specific improvements to the system prompt. Be concise and actionable."},
            {"role": "user", "content":
                f"Persona: {req.persona}\n\nCurrent prompt: {current_preview}\n\nFeedback:\n{feedback_text}"},
        ])
    except Exception as exc:
        suggestion = f"[Arbiter Engine error] {exc}"

    return {
        "persona":               req.persona,
        "suggestion":            suggestion,
        "feedback_analyzed":     len(feedback),
        "current_prompt_preview": current_preview,
    }


@app.get("/persona/feedback/{persona}")
def persona_feedback_get(persona: str) -> dict:
    """Return feedback log for a persona.

    M11-7
    """
    return {"persona": persona, "feedback": _persona_feedback_log.get(persona, [])}


@app.get("/persona/learning/summary")
def persona_learning_summary() -> dict:
    """Return learning stats across all personas.

    M11-7
    """
    by_persona: dict[str, dict] = {}
    total_feedback = 0
    for persona, records in _persona_feedback_log.items():
        up   = sum(1 for r in records if r.get("rating") == "up")
        down = sum(1 for r in records if r.get("rating") == "down")
        last = records[-1]["timestamp"] if records else ""
        by_persona[persona] = {"up": up, "down": down, "last_adapted": last}
        total_feedback += len(records)
    return {"by_persona": by_persona, "total_feedback": total_feedback}


# ═══════════════════════════════════════════════════════════════════════════════
#  M11-8: AI pair programming mode
# ───────────────────────────────────────────────────────────────────────────────

class _PairStartReq(BaseModel):
    project: str
    file_path: str


class _PairAnalyzeReq(BaseModel):
    project: str
    code: str
    cursor_line: int = 0


class _PairStopReq(BaseModel):
    project: str


@app.post("/pair/start")
def pair_start(req: _PairStartReq) -> dict:
    """Activate AI pair programming mode for a project file.

    M11-8
    """
    try:
        fp      = Path(req.file_path)
        content = fp.read_text(encoding="utf-8", errors="ignore")[:4000] if fp.is_file() else ""
    except Exception:
        content = ""

    analysis    = ""
    suggestions: list[str] = []
    warnings:    list[str] = []

    if content:
        try:
            raw = _llm.chat([
                {"role": "system", "content":
                    "You are an AI pair programmer. Analyse the code and return JSON: "
                    '{"analysis": "...", "suggestions": [...], "warnings": [...]}'},
                {"role": "user", "content": content},
            ])
            data        = json.loads(raw)
            analysis    = data.get("analysis", "")
            suggestions = data.get("suggestions", [])
            warnings    = data.get("warnings", [])
        except Exception as exc:
            analysis = f"[Initial analysis error] {exc}"

    _pair_sessions[req.project] = {
        "active":          True,
        "file_path":       req.file_path,
        "last_analysis":   analysis,
        "suggestions":     suggestions,
        "warnings":        warnings,
        "analysis_count":  1 if content else 0,
    }
    return {
        "status":      "active",
        "file_path":   req.file_path,
        "analysis":    analysis,
        "suggestions": suggestions,
        "warnings":    warnings,
    }


@app.post("/pair/analyze")
def pair_analyze(req: _PairAnalyzeReq) -> dict:
    """Run LLM analysis on a code snippet at a cursor position.

    M11-8
    """
    session = _pair_sessions.setdefault(req.project, {
        "active": True, "file_path": "", "last_analysis": "",
        "suggestions": [], "warnings": [], "analysis_count": 0,
    })
    cursor_hint = f" (cursor at line {req.cursor_line})" if req.cursor_line else ""
    try:
        raw = _llm.chat([
            {"role": "system", "content":
                "You are an AI pair programmer. Analyse the code snippet and return JSON: "
                '{"suggestions": [...], "warnings": [...], "refactor_hints": [...]}'},
            {"role": "user", "content": f"Code{cursor_hint}:\n```\n{req.code[:3000]}\n```"},
        ])
        data            = json.loads(raw)
        suggestions     = data.get("suggestions", [])
        warnings        = data.get("warnings", [])
        refactor_hints  = data.get("refactor_hints", [])
    except Exception as exc:
        suggestions    = []
        warnings       = [f"Analysis error: {exc}"]
        refactor_hints = []

    session["last_analysis"]  = req.code[:200]
    session["suggestions"]    = suggestions
    session["warnings"]       = warnings
    session["analysis_count"] = session.get("analysis_count", 0) + 1

    return {
        "suggestions":    suggestions,
        "warnings":       warnings,
        "refactor_hints": refactor_hints,
        "analysis_count": session["analysis_count"],
    }


@app.post("/pair/stop")
def pair_stop(req: _PairStopReq) -> dict:
    """Deactivate AI pair programming mode for a project.

    M11-8
    """
    session = _pair_sessions.get(req.project, {})
    count   = session.get("analysis_count", 0)
    _pair_sessions[req.project] = {
        "active":         False,
        "file_path":      session.get("file_path", ""),
        "last_analysis":  session.get("last_analysis", ""),
        "suggestions":    [],
        "warnings":       [],
        "analysis_count": count,
    }
    return {"status": "stopped", "analysis_count": count}


@app.get("/pair/status/{project}")
def pair_status(project: str) -> dict:
    """Return the current pair programming session state.

    M11-8
    """
    session = _pair_sessions.get(project, {
        "active": False, "file_path": "", "last_analysis": "",
        "suggestions": [], "warnings": [], "analysis_count": 0,
    })
    return {"project": project, **session}


# ═══════════════════════════════════════════════════════════════════════════════
#  M12-1: System-wide workspace logging
# ───────────────────────────────────────────────────────────────────────────────

from core.logger import (
    write_workspace_log as _write_workspace_log,
    read_workspace_log as _read_workspace_log,
    capture_crash as _capture_crash,
)


class _LogWriteReq(BaseModel):
    workspace: str
    message: str
    level: str = "INFO"
    source: str = ""


class _LogReadReq(BaseModel):
    workspace: str
    level: str | None = None
    limit: int = 200


@app.post("/log/workspace")
def log_workspace_write(req: _LogWriteReq) -> dict:
    """Write a structured log entry to the workspace log.

    M12-1
    """
    entry = _write_workspace_log(req.workspace, req.level, req.message, source=req.source)
    return {"status": "ok", "entry": entry}


@app.get("/log/workspace")
def log_workspace_read(workspace: str, level: str | None = None, limit: int = 200) -> dict:
    """Return recent workspace log entries, optionally filtered by *level*.

    M12-1
    """
    entries = _read_workspace_log(workspace, level=level, limit=limit)
    return {"workspace": workspace, "count": len(entries), "entries": entries}


# ═══════════════════════════════════════════════════════════════════════════════
#  M12-2: Crash reports → local issues tracker
# ───────────────────────────────────────────────────────────────────────────────

from modules.issues.src.issues import (
    issues_create as _issues_create,
    issues_list as _issues_list,
    issues_get as _issues_get,
    issues_close as _issues_close,
    issues_comment as _issues_comment,
)


class _CrashReportReq(BaseModel):
    workspace: str
    title: str
    traceback: str = ""
    source: str = ""
    extra: dict[str, Any] | None = None


class _IssueCreateReq(BaseModel):
    workspace: str
    title: str
    body: str = ""
    kind: str = "bug"
    labels: list[str] = []


class _IssueCloseReq(BaseModel):
    workspace: str
    issue_id: str
    resolution: str = ""


class _IssueCommentReq(BaseModel):
    workspace: str
    issue_id: str
    comment: str
    author: str = "arbiter"


@app.post("/log/crash")
def log_crash_report(req: _CrashReportReq) -> dict:
    """File a crash report: log it to the workspace log *and* open a local issue.

    The crash is written as a CRASH-level workspace log entry and a
    ``kind=crash`` issue is created in the git-backed local issues tracker.

    M12-2
    """
    # 1. Write to workspace log
    _write_workspace_log(
        req.workspace,
        "CRASH",
        req.title,
        source=req.source,
        extra={"traceback": req.traceback, **(req.extra or {})},
    )

    # 2. Create an issue in the local tracker
    body_parts = []
    if req.traceback:
        body_parts.append(f"```\n{req.traceback}\n```")
    if req.source:
        body_parts.append(f"**Source:** {req.source}")
    if req.extra:
        body_parts.append(f"**Extra:** {json.dumps(req.extra, indent=2)}")

    result = _issues_create(
        req.workspace,
        title=req.title,
        body="\n\n".join(body_parts),
        kind="crash",
        labels=["crash", "auto-filed"],
    )
    return {"status": "filed", "log_level": "CRASH", "issue": result.get("issue")}


@app.post("/issues/create")
def issues_create_endpoint(req: _IssueCreateReq) -> dict:
    """Create a new issue in the workspace's local git issues tracker.

    M12-2
    """
    return _issues_create(
        req.workspace,
        title=req.title,
        body=req.body,
        kind=req.kind,
        labels=req.labels,
    )


@app.get("/issues/list")
def issues_list_endpoint(workspace: str, status: str | None = None, kind: str | None = None) -> dict:
    """List issues in the workspace's local issues tracker.

    M12-2
    """
    return _issues_list(workspace, status=status, kind=kind)


@app.get("/issues/{issue_id}")
def issues_get_endpoint(workspace: str, issue_id: str) -> dict:
    """Return the full record for a single issue.

    M12-2
    """
    return _issues_get(workspace, issue_id)


@app.post("/issues/close")
def issues_close_endpoint(req: _IssueCloseReq) -> dict:
    """Close an issue with an optional resolution note.

    M12-2
    """
    return _issues_close(req.workspace, req.issue_id, resolution=req.resolution)


@app.post("/issues/comment")
def issues_comment_endpoint(req: _IssueCommentReq) -> dict:
    """Add a comment to an existing issue.

    M12-2
    """
    return _issues_comment(req.workspace, req.issue_id, req.comment, author=req.author)


# ═══════════════════════════════════════════════════════════════════════════════
#  M13-5: WebSocket /ws/chat — full-duplex real-time streaming chat
# ───────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """Full-duplex streaming chat over WebSocket.

    Protocol (JSON frames):
    - Client → Server: ``{"message": "...", "project": "default"}``
    - Server → Client (tokens): ``{"token": "...", "done": false}``
    - Server → Client (final):  ``{"token": "", "done": true, "full_response": "..."}``

    M13-5
    """
    await websocket.accept()
    # Track the active project for use in the disconnect log message
    _active_project: str = "?"
    try:
        while True:
            data = await websocket.receive_json()
            message: str = data.get("message", "")
            project: str = data.get("project", "default")
            _active_project = project
            if not message:
                await websocket.send_json({"error": "Empty message"})
                continue

            # Check LRU cache first (M13-4)
            cached = _cache_get(project, message)
            if cached:
                await websocket.send_json({"token": cached, "done": False, "cached": True})
                await websocket.send_json({"token": "", "done": True, "full_response": cached})
                _budget_record(project, message, cached)
                continue

            persona = _active_personas.get(project, "Arbiter")
            history = _chat_histories.setdefault(project, [])
            messages = [
                {"role": "system", "content": f"You are {persona}."},
                *history[-10:],
                {"role": "user", "content": message},
            ]

            try:
                # M13-1: run blocking LLM call off the event loop
                full = await asyncio.to_thread(_llm.chat, messages)
            except Exception as exc:
                full = f"[Arbiter Engine error] {exc}"

            # Stream word chunks to the client
            words = full.split()
            for i in range(0, len(words), _STREAM_CHUNK_WORDS):
                chunk = " ".join(words[i:i + _STREAM_CHUNK_WORDS])
                await websocket.send_json({"token": chunk, "done": False})
            await websocket.send_json({"token": "", "done": True, "full_response": full})

            history.append({"role": "user",      "content": message})
            history.append({"role": "assistant", "content": full})
            if len(history) > _MAX_CHAT_HISTORY_TURNS:
                history[:] = history[-_MAX_CHAT_HISTORY_TURNS:]

            _cache_set(project, message, full)
            _budget_record(project, message, full)

    except WebSocketDisconnect:
        logger.debug("WebSocket /ws/chat disconnected (project=%s)", _active_project)
    except Exception as exc:
        logger.error("WebSocket /ws/chat error: %s", exc)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  M14-1: Static code linting integration
# ───────────────────────────────────────────────────────────────────────────────

import ast as _ast
import re as _re
import textwrap as _textwrap

# M14 constants
_LINT_MAX_LINE_LENGTH: int = 120
_DUPLICATES_MAX_GROUPS: int = 50

# Ruff rule codes that map to "error" severity (compile/runtime errors)
_RUFF_ERROR_CODES: frozenset[str] = frozenset({
    "E999",  # SyntaxError
    "F821",  # Undefined name
    "F811",  # Redefinition of unused name
    "F401",  # Imported but unused (reported as error in strict mode)
})


class _LintReq(BaseModel):
    project: str
    file_path: str
    content: str | None = None


@app.post("/analysis/lint")
def analysis_lint(req: _LintReq) -> dict:
    """Run static code analysis on a file or inline content.

    For Python files: parse with ``ast`` to detect syntax errors, then run
    ``ruff`` or ``pyflakes`` if available, falling back to a simple AST-based
    heuristic analyser.  For other languages the subprocess-based linter is
    invoked when installed.

    Returns a list of *issues*: ``{line, col, severity, code, message}``.

    M14-1
    """
    path = Path(req.file_path)
    suffix = path.suffix.lower()
    issues: list[dict] = []

    # Resolve content
    content = req.content
    if content is None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"file": req.file_path, "issues": [], "error": str(exc)}

    # ── Python ──────────────────────────────────────────────────────────────
    if suffix == ".py":
        # 1. Syntax check via ast
        try:
            _ast.parse(content)
        except SyntaxError as e:
            issues.append({
                "line": e.lineno or 1, "col": e.offset or 1,
                "severity": "error", "code": "E999",
                "message": f"SyntaxError: {e.msg}",
            })
            return {"file": req.file_path, "language": "python", "issues": issues, "tool": "ast"}

        # 2. Try ruff first
        try:
            import tempfile as _tmpmod
            with _tmpmod.NamedTemporaryFile(suffix=".py", mode="w", delete=False,
                                            encoding="utf-8") as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            proc = subprocess.run(
                ["ruff", "check", "--output-format=json", tmp_path],
                capture_output=True, text=True, timeout=15,
            )
            Path(tmp_path).unlink(missing_ok=True)
            if proc.stdout.strip():
                for item in json.loads(proc.stdout):
                    loc = item.get("location", {})
                    issues.append({
                        "line":     loc.get("row", 1),
                        "col":      loc.get("column", 1),
                        "severity": "error" if item.get("code", "") in _RUFF_ERROR_CODES else "warning",
                        "code":     item.get("code", "?"),
                        "message":  item.get("message", ""),
                    })
            return {"file": req.file_path, "language": "python", "issues": issues, "tool": "ruff"}
        except (FileNotFoundError, Exception):
            pass

        # 3. Heuristic AST-based checks
        tree = _ast.parse(content)
        lines = content.splitlines()
        for node in _ast.walk(tree):
            # Bare except
            if isinstance(node, _ast.ExceptHandler) and node.type is None:
                issues.append({
                    "line": node.lineno, "col": node.col_offset + 1,
                    "severity": "warning", "code": "W001",
                    "message": "Bare 'except:' catches all exceptions including BaseException",
                })
            # Mutable default arguments
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                for default in node.args.defaults:
                    if isinstance(default, (_ast.List, _ast.Dict, _ast.Set)):
                        issues.append({
                            "line": default.lineno, "col": default.col_offset + 1,
                            "severity": "warning", "code": "W002",
                            "message": f"Mutable default argument in function '{node.name}'",
                        })
        # Long lines
        for i, line in enumerate(lines, 1):
            if len(line) > _LINT_MAX_LINE_LENGTH:
                issues.append({
                    "line": i, "col": _LINT_MAX_LINE_LENGTH + 1,
                    "severity": "info", "code": "E501",
                    "message": f"Line too long ({len(line)} > {_LINT_MAX_LINE_LENGTH} characters)",
                })
        return {"file": req.file_path, "language": "python", "issues": issues, "tool": "ast-heuristic"}

    # ── JavaScript / TypeScript ─────────────────────────────────────────────
    if suffix in (".js", ".ts", ".jsx", ".tsx"):
        try:
            proc = subprocess.run(
                ["node", "--check", req.file_path],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode != 0:
                for match in _re.finditer(
                    r"([^\n]+):(\d+)\n(.+)", proc.stderr
                ):
                    issues.append({
                        "line": int(match.group(2)), "col": 1,
                        "severity": "error", "code": "SyntaxError",
                        "message": match.group(3).strip(),
                    })
        except FileNotFoundError:
            pass
        return {"file": req.file_path, "language": "javascript", "issues": issues, "tool": "node-check"}

    # ── Generic: just return empty ───────────────────────────────────────────
    return {"file": req.file_path, "language": suffix.lstrip(".") or "unknown", "issues": [], "tool": "none"}


# ═══════════════════════════════════════════════════════════════════════════════
#  M14-2: Dependency vulnerability scanning
# ───────────────────────────────────────────────────────────────────────────────

class _DepScanReq(BaseModel):
    project: str
    project_dir: str


@app.post("/analysis/deps/security")
def analysis_deps_security(req: _DepScanReq) -> dict:
    """Scan project dependencies for known CVE vulnerabilities.

    Detection strategy (first match wins):
    1. ``pip-audit`` — Python requirements.txt / pyproject.toml
    2. ``safety check`` — Python fallback
    3. ``npm audit --json`` — Node.js package.json
    4. ``cargo audit --json`` — Rust Cargo.toml

    Returns a list of *vulnerabilities*:
    ``{package, installed_version, vuln_id, severity, description, fix_version}``.

    M14-2
    """
    project_path = Path(req.project_dir)
    vulnerabilities: list[dict] = []
    tool_used = "none"

    # ── pip-audit (Python) ──────────────────────────────────────────────────
    req_file = project_path / "requirements.txt"
    pyproject = project_path / "pyproject.toml"
    if req_file.exists() or pyproject.exists():
        try:
            cmd = ["pip-audit", "--format=json"]
            if req_file.exists():
                cmd += ["-r", str(req_file)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                  cwd=str(project_path))
            data = json.loads(proc.stdout or "[]")
            # pip-audit output: list of {name, version, vulns: [{id, fix_versions, description}]}
            if isinstance(data, list):
                for pkg in data:
                    for v in pkg.get("vulns", []):
                        # pip-audit 'aliases' contains alt IDs (e.g. "CVE-…"), not severity
                        vulnerabilities.append({
                            "package":           pkg.get("name", ""),
                            "installed_version": pkg.get("version", ""),
                            "vuln_id":           v.get("id", ""),
                            "severity":          "unknown",
                            "description":       v.get("description", ""),
                            "fix_version":       ", ".join(v.get("fix_versions", [])),
                            "aliases":           v.get("aliases", []),
                        })
            tool_used = "pip-audit"
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            # Fallback: safety
            try:
                proc = subprocess.run(
                    ["safety", "check", "--json"],
                    capture_output=True, text=True, timeout=60,
                    cwd=str(project_path),
                )
                items = json.loads(proc.stdout or "[]")
                for item in items:
                    vulnerabilities.append({
                        "package":           item[0] if len(item) > 0 else "",
                        "installed_version": item[2] if len(item) > 2 else "",
                        "vuln_id":           item[4] if len(item) > 4 else "",
                        "severity":          "high",
                        "description":       item[3] if len(item) > 3 else "",
                        "fix_version":       item[1] if len(item) > 1 else "",
                    })
                tool_used = "safety"
            except (FileNotFoundError, Exception):
                pass

    # ── npm audit (Node.js) ─────────────────────────────────────────────────
    elif (project_path / "package.json").exists():
        try:
            proc = subprocess.run(
                ["npm", "audit", "--json"],
                capture_output=True, text=True, timeout=60,
                cwd=str(project_path),
            )
            data = json.loads(proc.stdout or "{}")
            for name, adv in data.get("vulnerabilities", {}).items():
                vulnerabilities.append({
                    "package":           name,
                    "installed_version": adv.get("version", ""),
                    "vuln_id":           adv.get("via", [{}])[0].get("url", "") if adv.get("via") else "",
                    "severity":          adv.get("severity", "unknown"),
                    "description":       adv.get("via", [{}])[0].get("title", "") if adv.get("via") else "",
                    "fix_version":       adv.get("fixAvailable", {}).get("version", "") if isinstance(adv.get("fixAvailable"), dict) else "",
                })
            tool_used = "npm-audit"
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            pass

    # ── cargo audit (Rust) ──────────────────────────────────────────────────
    elif (project_path / "Cargo.toml").exists():
        try:
            proc = subprocess.run(
                ["cargo", "audit", "--json"],
                capture_output=True, text=True, timeout=60,
                cwd=str(project_path),
            )
            data = json.loads(proc.stdout or "{}")
            for vuln in data.get("vulnerabilities", {}).get("list", []):
                adv = vuln.get("advisory", {})
                pkg = vuln.get("package", {})
                vulnerabilities.append({
                    "package":           pkg.get("name", ""),
                    "installed_version": pkg.get("version", ""),
                    "vuln_id":           adv.get("id", ""),
                    "severity":          adv.get("cvss", "unknown"),
                    "description":       adv.get("title", ""),
                    "fix_version":       vuln.get("versions", {}).get("patched", [None])[0] or "",
                })
            tool_used = "cargo-audit"
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            pass

    return {
        "project":         req.project,
        "tool":            tool_used,
        "vulnerability_count": len(vulnerabilities),
        "vulnerabilities": vulnerabilities,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  M14-3: Code complexity metrics
# ───────────────────────────────────────────────────────────────────────────────

class _ComplexityReq(BaseModel):
    project: str
    file_path: str
    content: str | None = None


def _cyclomatic_complexity(tree: "_ast.AST") -> dict[str, int]:
    """Compute per-function cyclomatic complexity for a Python AST."""
    results: dict[str, int] = {}
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            complexity = 1
            for child in _ast.walk(node):
                if isinstance(child, (
                    _ast.If, _ast.While, _ast.For, _ast.AsyncFor,
                    _ast.ExceptHandler, _ast.With, _ast.AsyncWith,
                    _ast.Assert, _ast.comprehension,
                )):
                    complexity += 1
                elif isinstance(child, _ast.BoolOp):
                    complexity += len(child.values) - 1
            results[node.name] = complexity
    return results


@app.post("/analysis/complexity")
def analysis_complexity(req: _ComplexityReq) -> dict:
    """Compute cyclomatic complexity and basic maintainability metrics for a file.

    For Python files the analysis is performed directly via the ``ast`` module.
    Returns per-function complexity scores and an overall file-level summary:
    ``{function, complexity, risk}`` where risk is:
    - ``low`` (1–5), ``medium`` (6–10), ``high`` (11–20), ``very-high`` (>20).

    M14-3
    """
    path = Path(req.file_path)
    suffix = path.suffix.lower()
    content = req.content
    if content is None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"file": req.file_path, "error": str(exc), "functions": []}

    if suffix != ".py":
        # Non-Python: return line-count heuristics only
        lines = content.splitlines()
        code_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]
        return {
            "file":        req.file_path,
            "language":    suffix.lstrip(".") or "unknown",
            "total_lines": len(lines),
            "code_lines":  len(code_lines),
            "functions":   [],
            "note":        "Full complexity analysis only supported for Python",
        }

    try:
        tree = _ast.parse(content)
    except SyntaxError as e:
        return {"file": req.file_path, "error": f"SyntaxError: {e.msg}", "functions": []}

    scores = _cyclomatic_complexity(tree)
    lines = content.splitlines()
    code_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]

    def _risk(cc: int) -> str:
        if cc <= 5:   return "low"
        if cc <= 10:  return "medium"
        if cc <= 20:  return "high"
        return "very-high"

    functions = [
        {"function": name, "complexity": cc, "risk": _risk(cc)}
        for name, cc in sorted(scores.items(), key=lambda x: -x[1])
    ]

    avg_cc = sum(scores.values()) / len(scores) if scores else 0
    return {
        "file":              req.file_path,
        "language":          "python",
        "total_lines":       len(lines),
        "code_lines":        len(code_lines),
        "function_count":    len(scores),
        "avg_complexity":    round(avg_cc, 2),
        "max_complexity":    max(scores.values(), default=0),
        "overall_risk":      _risk(int(avg_cc + 0.5)),
        "functions":         functions,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  M14-4: Duplicate code detection
# ───────────────────────────────────────────────────────────────────────────────

class _DuplicatesReq(BaseModel):
    project: str
    project_dir: str
    min_lines: int = 6
    extensions: list[str] = [".py", ".js", ".ts", ".cs"]
    max_groups: int = _DUPLICATES_MAX_GROUPS


@app.post("/analysis/duplicates")
def analysis_duplicates(req: _DuplicatesReq) -> dict:
    """Detect duplicate or near-duplicate code blocks across the project.

    Uses a rolling-hash (Rabin–Karp style) fingerprint of normalised
    ``min_lines``-line windows.  Returns groups of duplicate spans:
    ``{hash, occurrences: [{file, start_line, end_line, snippet}]}``.

    M14-4
    """
    project_path = Path(req.project_dir)
    exts = set(req.extensions)
    min_lines = max(3, req.min_lines)

    # Collect all files
    files: list[Path] = []
    for ext in exts:
        files.extend(project_path.rglob(f"*{ext}"))
    # Exclude common noise directories
    files = [
        f for f in files
        if not any(part in (".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build")
                   for part in f.parts)
    ]

    # Build fingerprint map: normalised_chunk_text -> [(file, start, end)]
    fingerprints: dict[str, list[dict]] = {}

    for fpath in files:
        try:
            raw_lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        # Normalise: strip whitespace, skip blank/comment-only lines
        norm_lines = []
        for l in raw_lines:
            stripped = l.strip()
            if stripped and not stripped.startswith(("#", "//", "--", "*")):
                norm_lines.append(stripped)
        if len(norm_lines) < min_lines:
            continue
        for start in range(len(norm_lines) - min_lines + 1):
            chunk = "\n".join(norm_lines[start:start + min_lines])
            key = chunk  # direct text match (fast for typical file sizes)
            if key not in fingerprints:
                fingerprints[key] = []
            snippet = "\n".join(raw_lines[start:start + min_lines])[:200]
            fingerprints[key].append({
                "file":       str(fpath.relative_to(project_path)),
                "start_line": start + 1,
                "end_line":   start + min_lines,
                "snippet":    snippet,
            })

    duplicates = [
        {
            "occurrences": occurrences,
            "duplicate_count": len(occurrences),
        }
        for occurrences in fingerprints.values()
        if len(occurrences) > 1
    ]
    # Deduplicate overlapping windows: keep only groups where files differ or lines are far apart
    seen_pairs: set[frozenset] = set()
    deduped: list[dict] = []
    for group in duplicates:
        pair_key = frozenset(
            f"{o['file']}:{o['start_line']}" for o in group["occurrences"]
        )
        if pair_key not in seen_pairs:
            seen_pairs.add(pair_key)
            deduped.append(group)

    deduped.sort(key=lambda g: -g["duplicate_count"])
    return {
        "project":         req.project,
        "files_scanned":   len(files),
        "duplicate_groups": len(deduped),
        "duplicates":      deduped[:req.max_groups],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  M14-5: API documentation generator
# ───────────────────────────────────────────────────────────────────────────────

class _DocsGenReq(BaseModel):
    project: str
    file_path: str
    content: str | None = None
    format: str = "markdown"  # "markdown" | "rst" | "json"


@app.post("/docs/generate")
def docs_generate(req: _DocsGenReq) -> dict:
    """Auto-generate API / module documentation from source code.

    For Python files the ``ast`` module is used to extract modules, classes,
    functions, and docstrings.  The result is rendered as Markdown (default),
    reStructuredText, or a JSON schema.

    For non-Python files an AI-powered summary is generated via the LLM
    if one is available.

    M14-5
    """
    path = Path(req.file_path)
    suffix = path.suffix.lower()
    content = req.content
    if content is None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"file": req.file_path, "error": str(exc), "documentation": ""}

    # ── Python: AST extraction ──────────────────────────────────────────────
    if suffix == ".py":
        try:
            tree = _ast.parse(content)
        except SyntaxError as e:
            return {"file": req.file_path, "error": f"SyntaxError: {e.msg}", "documentation": ""}

        module_doc = _ast.get_docstring(tree) or ""
        sections: list[dict] = []

        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                doc = _ast.get_docstring(node) or ""
                returns = ""
                if node.returns:
                    returns = _ast.unparse(node.returns) if hasattr(_ast, "unparse") else ""
                sections.append({
                    "kind":      "function",
                    "name":      node.name,
                    "args":      args,
                    "returns":   returns,
                    "docstring": doc,
                    "line":      node.lineno,
                    "is_async":  isinstance(node, _ast.AsyncFunctionDef),
                })
            elif isinstance(node, _ast.ClassDef):
                doc = _ast.get_docstring(node) or ""
                methods = []
                for child in node.body:
                    if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                        margs = [a.arg for a in child.args.args if a.arg != "self"]
                        methods.append({
                            "name":      child.name,
                            "args":      margs,
                            "docstring": _ast.get_docstring(child) or "",
                        })
                sections.append({
                    "kind":      "class",
                    "name":      node.name,
                    "docstring": doc,
                    "methods":   methods,
                    "line":      node.lineno,
                })

        # Sort by line number
        sections.sort(key=lambda s: s["line"])

        if req.format == "json":
            return {
                "file": req.file_path, "format": "json",
                "documentation": {
                    "module_doc": module_doc,
                    "sections":   sections,
                },
            }

        # Build Markdown
        md_lines = [f"# {path.name}\n"]
        if module_doc:
            md_lines.append(f"{module_doc}\n")
        for sec in sections:
            if sec["kind"] == "class":
                md_lines.append(f"## class `{sec['name']}`\n")
                if sec["docstring"]:
                    md_lines.append(f"{sec['docstring']}\n")
                for m in sec["methods"]:
                    sig = f"{m['name']}({', '.join(m['args'])})"
                    md_lines.append(f"### `{sig}`\n")
                    if m["docstring"]:
                        md_lines.append(f"{m['docstring']}\n")
            else:
                async_prefix = "async " if sec.get("is_async") else ""
                sig = f"{async_prefix}{sec['name']}({', '.join(sec['args'])})"
                if sec.get("returns"):
                    sig += f" → {sec['returns']}"
                md_lines.append(f"## `{sig}`\n")
                if sec["docstring"]:
                    md_lines.append(f"{sec['docstring']}\n")

        if req.format == "rst":
            # Simple Markdown → RST conversion
            rst = "\n".join(md_lines)
            rst = _re.sub(r"^# (.+)$", lambda m: m.group(1) + "\n" + "=" * len(m.group(1)), rst, flags=_re.M)
            rst = _re.sub(r"^## (.+)$", lambda m: m.group(1) + "\n" + "-" * len(m.group(1)), rst, flags=_re.M)
            rst = _re.sub(r"^### (.+)$", lambda m: m.group(1) + "\n" + "~" * len(m.group(1)), rst, flags=_re.M)
            rst = _re.sub(r"`(.+?)`", r"``\1``", rst)
            return {"file": req.file_path, "format": "rst", "documentation": rst}

        return {"file": req.file_path, "format": "markdown", "documentation": "\n".join(md_lines)}

    # ── Non-Python: LLM summary ─────────────────────────────────────────────
    try:
        prompt = (
            f"Generate concise API/module documentation in {req.format.upper()} format "
            f"for the following {suffix.lstrip('.')} file:\n\n```\n{content[:4000]}\n```"
        )
        doc = _llm.chat([{"role": "user", "content": prompt}])
    except Exception as exc:
        doc = f"[Documentation generation error] {exc}"
    return {"file": req.file_path, "format": req.format, "documentation": doc}


# ═══════════════════════════════════════════════════════════════════════════════
#  M14-6: Code coverage report parser
# ───────────────────────────────────────────────────════════════════════════════

class _CoverageReq(BaseModel):
    project: str
    project_dir: str
    run_tests: bool = False


@app.post("/analysis/coverage")
def analysis_coverage(req: _CoverageReq) -> dict:
    """Parse or run coverage reports for the project.

    If ``run_tests=true`` (and the project has a pytest / coverage setup)
    the coverage run is executed in the project directory.  Otherwise the
    most recent ``.coverage`` / ``coverage.xml`` / ``lcov.info`` is parsed.

    Returns per-file line coverage percentages and an overall summary.

    M14-6
    """
    project_path = Path(req.project_dir)

    # ── Optionally run tests with coverage ──────────────────────────────────
    if req.run_tests:
        try:
            subprocess.run(
                ["python", "-m", "pytest", "--cov=.", "--cov-report=xml",
                 "--cov-report=term-missing", "-q"],
                cwd=str(project_path),
                capture_output=True, text=True, timeout=120,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # ── Parse coverage.xml (Cobertura format — pytest-cov default) ──────────
    xml_file = project_path / "coverage.xml"
    if xml_file.exists():
        try:
            import xml.etree.ElementTree as _ET
            tree = _ET.parse(xml_file)
            root = tree.getroot()
            overall = float(root.attrib.get("line-rate", 0)) * 100
            files_cov: list[dict] = []
            for cls in root.iter("class"):
                fname = cls.attrib.get("filename", "")
                rate  = float(cls.attrib.get("line-rate", 0)) * 100
                lines = cls.find("lines")
                total  = len(list(lines)) if lines is not None else 0
                missed = sum(1 for l in (lines or []) if l.attrib.get("hits", "1") == "0")
                files_cov.append({
                    "file":     fname,
                    "coverage": round(rate, 1),
                    "lines":    total,
                    "missed":   missed,
                })
            files_cov.sort(key=lambda x: x["coverage"])
            return {
                "project":          req.project,
                "overall_coverage": round(overall, 1),
                "format":           "cobertura-xml",
                "files":            files_cov,
            }
        except Exception as exc:
            return {"project": req.project, "error": str(exc), "files": []}

    # ── Parse lcov.info (used by many JS/TS projects) ───────────────────────
    lcov_file = project_path / "lcov.info"
    if not lcov_file.exists():
        lcov_file = project_path / "coverage" / "lcov.info"
    if lcov_file.exists():
        try:
            files_cov: list[dict] = []
            current_file = ""
            found = hit = 0
            for line in lcov_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("SF:"):
                    current_file = line[3:]
                    found = hit = 0
                elif line.startswith("LF:"):
                    found = int(line[3:])
                elif line.startswith("LH:"):
                    hit = int(line[3:])
                elif line == "end_of_record":
                    rate = (hit / found * 100) if found else 0
                    files_cov.append({
                        "file":     current_file,
                        "coverage": round(rate, 1),
                        "lines":    found,
                        "missed":   found - hit,
                    })
            overall = sum(f["coverage"] for f in files_cov) / len(files_cov) if files_cov else 0
            files_cov.sort(key=lambda x: x["coverage"])
            return {
                "project":          req.project,
                "overall_coverage": round(overall, 1),
                "format":           "lcov",
                "files":            files_cov,
            }
        except Exception as exc:
            return {"project": req.project, "error": str(exc), "files": []}

    return {
        "project": req.project,
        "overall_coverage": 0,
        "format": "none",
        "files": [],
        "note": "No coverage report found. Set run_tests=true to generate one.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  M14-7: Performance profiler integration
# ───────────────────────────────────────────────────────────────────────────────

import pstats as _pstats
import io as _io


class _ProfileReq(BaseModel):
    project: str
    script_path: str
    args: list[str] = []
    top_n: int = 20


@app.post("/analysis/profile")
def analysis_profile(req: _ProfileReq) -> dict:
    """Run cProfile on a Python script and return the top hotspots.

    The script is executed in a **subprocess** (``python -m cProfile``) so it
    is fully isolated from the server's process space.  Results are returned
    as a ranked list of ``{function, file, line, calls, total_time_s,
    cumulative_time_s}``.

    M14-7
    """
    script = Path(req.script_path)
    if not script.exists():
        return {"project": req.project, "error": f"Script not found: {req.script_path}", "hotspots": []}
    if script.suffix.lower() != ".py":
        return {"project": req.project, "error": "Only Python scripts are supported", "hotspots": []}

    try:
        import tempfile as _tmpmod
        with _tmpmod.NamedTemporaryFile(suffix=".prof", delete=False) as prof_file:
            prof_path = prof_file.name

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "cProfile", "-o", prof_path, str(script)]
                + list(req.args),
                capture_output=True, text=True, timeout=120,
                cwd=str(script.parent),
            )
        finally:
            pass  # always try to parse the profile even if script exited non-zero

        buf = _io.StringIO()
        try:
            ps = _pstats.Stats(prof_path, stream=buf)
            ps.sort_stats("cumulative")
            ps.print_stats(req.top_n)
        finally:
            Path(prof_path).unlink(missing_ok=True)

        raw_output = buf.getvalue()

        # Parse pstats text output
        hotspots: list[dict] = []
        for line in raw_output.splitlines():
            # Pattern: "  ncalls  tottime  percall  cumtime  percall filename:lineno(function)"
            m = _re.match(
                r"\s*(\d+(?:/\d+)?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+):(\d+)\((.+)\)",
                line,
            )
            if m:
                hotspots.append({
                    "calls":             m.group(1),
                    "total_time_s":      float(m.group(2)),
                    "per_call_s":        float(m.group(3)),
                    "cumulative_time_s": float(m.group(4)),
                    "cum_per_call_s":    float(m.group(5)),
                    "file":              m.group(6),
                    "line":              int(m.group(7)),
                    "function":          m.group(8),
                })

        return {
            "project":    req.project,
            "script":     req.script_path,
            "top_n":      req.top_n,
            "hotspots":   hotspots,
            "raw_output": raw_output,
            "stderr":     proc.stderr[:1000] if proc.returncode != 0 else "",
        }
    except Exception as exc:
        return {"project": req.project, "error": str(exc), "hotspots": []}


# ═══════════════════════════════════════════════════════════════════════════════
#  M14-8: AI-powered full code review workflow
# ───────────────────────────────────────────────────────────────────────────────

class _ReviewWorkflowReq(BaseModel):
    project: str
    file_path: str
    content: str | None = None
    checklist: list[str] = [
        "correctness", "security", "performance",
        "readability", "error-handling", "test-coverage",
    ]


@app.post("/review/workflow")
async def review_workflow(req: _ReviewWorkflowReq) -> dict:
    """Run a comprehensive AI-powered code review on a file.

    Combines static analysis (M14-1) + complexity (M14-3) with an LLM
    review pass.  The LLM is asked to evaluate the file against each item in
    *checklist* and return structured findings.

    Response: ``{summary, findings: [{category, severity, line, message, suggestion}], score}``

    M14-8
    """
    path = Path(req.file_path)
    content = req.content
    if content is None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"project": req.project, "file": req.file_path, "error": str(exc)}

    # 1. Static analysis
    lint_result = analysis_lint(_LintReq(
        project=req.project,
        file_path=req.file_path,
        content=content,
    ))
    complexity_result = analysis_complexity(_ComplexityReq(
        project=req.project,
        file_path=req.file_path,
        content=content,
    ))

    # 2. Build LLM prompt
    checklist_str = "\n".join(f"- {item}" for item in req.checklist)
    lint_summary  = f"{len(lint_result.get('issues', []))} lint issue(s)"
    cc_summary    = (
        f"avg cyclomatic complexity: {complexity_result.get('avg_complexity', 'N/A')}, "
        f"max: {complexity_result.get('max_complexity', 'N/A')}"
    )
    snippet = content[:3000]
    if len(content) > 3000:
        snippet += "\n... (truncated)"

    prompt = _textwrap.dedent(f"""
        You are an expert code reviewer. Review the following file and evaluate it against
        each item in the checklist. Return a JSON object with this exact structure:
        {{
          "summary": "<one-sentence overall assessment>",
          "score": <0-100 integer>,
          "findings": [
            {{"category": "<checklist item>", "severity": "error|warning|info",
              "line": <line number or null>, "message": "<issue>", "suggestion": "<fix>"}}
          ]
        }}

        Checklist:
        {checklist_str}

        Static analysis pre-results: {lint_summary}; {cc_summary}

        File: {req.file_path}
        ```
        {snippet}
        ```

        Reply with ONLY valid JSON.
    """).strip()

    try:
        raw = await _asyncio.to_thread(
            _llm.chat,
            [{"role": "user", "content": prompt}],
        )
        # Extract JSON from the response
        json_match = _re.search(r"\{[\s\S]+\}", raw)
        if json_match:
            review_data = json.loads(json_match.group())
        else:
            review_data = {"summary": raw, "score": None, "findings": []}
    except Exception as exc:
        review_data = {
            "summary": f"LLM review failed: {exc}",
            "score": None,
            "findings": [],
        }

    # Merge static findings into the AI findings
    for issue in lint_result.get("issues", []):
        review_data["findings"].append({
            "category":   "correctness",
            "severity":   issue.get("severity", "warning"),
            "line":       issue.get("line"),
            "message":    f"[{issue.get('code', '?')}] {issue.get('message', '')}",
            "suggestion": "Fix the reported lint issue.",
        })

    return {
        "project":     req.project,
        "file":        req.file_path,
        "checklist":   req.checklist,
        "lint":        lint_result,
        "complexity":  complexity_result,
        "review":      review_data,
    }


# ─────────────────────────────────────────────────────────────────────────────
# P1-7 — In-application Wiki panel: /wiki REST endpoints
# Serves markdown files from docs/wiki/ so the WPF IDE can display them.
# ─────────────────────────────────────────────────────────────────────────────

_WIKI_DIR = _BASE.parent.parent / "docs" / "wiki"


@app.get("/wiki")
async def wiki_list():
    """Return a list of all wiki documents (name + title extracted from first heading)."""
    if not _WIKI_DIR.is_dir():
        return {"pages": []}
    pages = []
    for md_file in sorted(_WIKI_DIR.glob("*.md")):
        title = md_file.stem.replace("_", " ").replace("-", " ").title()
        try:
            first_line = md_file.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            if first_line.startswith("#"):
                title = first_line.lstrip("#").strip()
        except Exception:
            pass
        pages.append({"name": md_file.stem, "filename": md_file.name, "title": title})
    return {"pages": pages}


@app.get("/wiki/{page}")
async def wiki_page(page: str):
    """Return the raw markdown content of a single wiki page.

    *page* is the filename stem (without ``.md``).  The endpoint also accepts
    the full filename with extension for convenience.
    """
    from fastapi import HTTPException as _HTTPEx
    # Strip .md extension if passed
    stem = page.removesuffix(".md")
    # Prevent path traversal
    if "/" in stem or "\\" in stem or ".." in stem:
        raise _HTTPEx(status_code=400, detail="invalid page name")
    md_path = _WIKI_DIR / f"{stem}.md"
    if not md_path.exists():
        raise _HTTPEx(status_code=404, detail=f"page '{stem}' not found")
    content = md_path.read_text(encoding="utf-8", errors="replace")
    return {"name": stem, "filename": md_path.name, "content": content}


# ─────────────────────────────────────────────────────────────────────────────
# P1-8 — Changelog automation: /changelog/generate
# Parses git log for [arbiter-self-build] commits and returns structured
# CHANGELOG entries.  Also writes docs/wiki/CHANGELOG.md.
# ─────────────────────────────────────────────────────────────────────────────

_SELF_BUILD_COMMIT_RE = _re.compile(
    r"\[arbiter-self-build\]\s*(?P<task_id>[\w-]+)?:?\s*(?P<title>.+)",
    _re.IGNORECASE,
)
_CHANGELOG_WIKI_PATH = _BASE.parent.parent / "docs" / "wiki" / "CHANGELOG.md"


def _git_log_self_build(repo_root: Path, max_commits: int = 500) -> list[dict]:
    """Return parsed [arbiter-self-build] commit metadata from the git log."""
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_root), "log",
                f"--max-count={max_commits}",
                "--pretty=format:%H%x1f%as%x1f%s",  # hash, date (YYYY-MM-DD), subject
                "--grep=[arbiter-self-build]",
                "--regexp-ignore-case",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
    except Exception:
        return []

    entries: list[dict] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) != 3:
            continue
        sha, date, subject = parts
        m = _SELF_BUILD_COMMIT_RE.search(subject)
        task_id = m.group("task_id") if m else None
        title = m.group("title").strip() if m else subject.strip()
        entries.append({"sha": sha[:12], "date": date, "task_id": task_id, "title": title})
    return entries


def _build_changelog_markdown(entries: list[dict]) -> str:
    """Convert parsed git entries into a CHANGELOG.md-style markdown string."""
    if not entries:
        return "# Changelog\n\nNo `[arbiter-self-build]` commits found.\n"

    # Group by date (YYYY-MM-DD)
    by_date: dict[str, list[dict]] = {}
    for e in entries:
        by_date.setdefault(e["date"], []).append(e)

    lines = ["# Changelog", "", "_Auto-generated from `[arbiter-self-build]` git commits._", ""]
    for date in sorted(by_date, reverse=True):
        lines.append(f"## {date}")
        lines.append("")
        for e in by_date[date]:
            prefix = f"[{e['task_id']}] " if e["task_id"] else ""
            lines.append(f"- {prefix}{e['title']} (`{e['sha']}`)")
        lines.append("")
    return "\n".join(lines)


@app.post("/changelog/generate")
async def changelog_generate(max_commits: int = 500, write_file: bool = True):
    """Generate CHANGELOG entries from ``[arbiter-self-build]`` git commits.

    Optionally writes the result to ``docs/wiki/CHANGELOG.md``.

    Returns the generated markdown and the list of parsed entries.
    """
    repo_root = _BASE.parent.parent
    entries = await _asyncio.to_thread(_git_log_self_build, repo_root, max_commits)
    markdown = _build_changelog_markdown(entries)

    written = False
    if write_file:
        try:
            _CHANGELOG_WIKI_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CHANGELOG_WIKI_PATH.write_text(markdown, encoding="utf-8")
            written = True
        except Exception as exc:
            logger.warning("Could not write CHANGELOG.md: %s", exc)

    return {
        "entries": entries,
        "total": len(entries),
        "markdown": markdown,
        "written_to": str(_CHANGELOG_WIKI_PATH) if written else None,
    }


@app.get("/changelog")
async def changelog_get():
    """Return the existing CHANGELOG.md content from docs/wiki/ (if present)."""
    if not _CHANGELOG_WIKI_PATH.exists():
        return {"content": None, "message": "No changelog found. POST /changelog/generate to create one."}
    content = _CHANGELOG_WIKI_PATH.read_text(encoding="utf-8", errors="replace")
    return {"content": content}


# ─────────────────────────────────────────────────────────────────────────────
# P2-3 — ArbiterAI Automation Agent
# Runs a multi-step AI agent loop that reads project context, generates a
# plan, and executes coding/asset/debug actions autonomously.
# ─────────────────────────────────────────────────────────────────────────────

class _AgentRunReq(BaseModel):
    project: str = "default"
    goal: str                          # natural-language task description
    max_steps: int = 5                 # hard cap on agent iterations
    persona: str = "senior_developer"  # which persona to adopt
    dry_run: bool = False              # if True, plan only — no file writes


class _AgentStep(BaseModel):
    step: int
    action: str
    result: str
    status: str  # success | error | skipped


@app.post("/agent/run")
async def agent_run(req: _AgentRunReq) -> dict:
    """Run the ArbiterAI automation agent for a natural-language goal.

    The agent executes up to *max_steps* iterations of a Plan → Act → Observe
    loop.  Each iteration:

    1. Reads current project context (files, recent chat history, workspace profile).
    2. Asks the LLM what to do next toward *goal* (returns JSON action).
    3. Executes the action (write file, call tool, run analysis).
    4. Feeds the observation back into the next iteration.

    P2-3
    """
    base = _ALLOWED_ROOTS.get("projects", _BASE / "workspace")
    p = Path(req.project)
    project_dir = p if (p.is_absolute() and p.exists()) else base / req.project

    persona_system = _SPECIALIST_PROMPTS.get(
        req.persona,
        _SPECIALIST_PROMPTS.get("backend", "You are a senior developer."),
    )

    system_prompt = (
        f"{persona_system}\n\n"
        "You are an autonomous coding agent. For each step return a JSON object:\n"
        '{"action": "write_file|run_analysis|answer|done", '
        '"path": "<relative path if write_file>", '
        '"content": "<file content or analysis request>", '
        '"reasoning": "<why this step>"}\n'
        "Output ONLY the JSON object, nothing else."
    )

    # Seed context: list top-level files in project dir
    try:
        if project_dir.is_dir():
            file_list = "\n".join(
                str(f.relative_to(project_dir))
                for f in sorted(project_dir.rglob("*"))
                if f.is_file() and not any(p in f.parts for p in (".git", "__pycache__", "node_modules"))
            )[:2000]
        else:
            file_list = "(project directory not found)"
    except Exception:
        file_list = "(could not list files)"

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content":
            f"Project: {req.project}\n"
            f"Goal: {req.goal}\n\n"
            f"Current project files:\n{file_list}\n\n"
            "Begin planning. Return your first action JSON."},
    ]

    steps: list[_AgentStep] = []
    final_answer: str = ""

    for step_num in range(1, req.max_steps + 1):
        try:
            raw = await _asyncio.to_thread(
                _llm.chat,
                messages,
            )
        except Exception as exc:
            steps.append(_AgentStep(step=step_num, action="error", result=str(exc), status="error"))
            break

        # Parse the JSON action
        json_match = _re.search(r"\{[\s\S]+?\}", raw)
        if not json_match:
            steps.append(_AgentStep(step=step_num, action="parse_error", result=raw[:200], status="error"))
            break

        try:
            action_data = json.loads(json_match.group())
        except Exception:
            steps.append(_AgentStep(step=step_num, action="parse_error", result=raw[:200], status="error"))
            break

        action_type = action_data.get("action", "answer")
        reasoning   = action_data.get("reasoning", "")

        # ── Execute the action ────────────────────────────────────────────────
        if action_type == "done" or action_type == "answer":
            final_answer = action_data.get("content", reasoning)
            steps.append(_AgentStep(step=step_num, action="done", result=final_answer[:500], status="success"))
            break

        elif action_type == "write_file":
            rel_path = action_data.get("path", "")
            content  = action_data.get("content", "")
            observation = "skipped (dry_run=True)"
            if not req.dry_run and rel_path and project_dir.is_dir():
                try:
                    target = (project_dir / rel_path).resolve()
                    # Guard: must stay inside project_dir
                    try:
                        target.relative_to(project_dir.resolve())
                    except ValueError:
                        observation = f"Write rejected: path '{rel_path}' escapes project directory"
                        steps.append(_AgentStep(step=step_num, action=f"write_file:{rel_path}", result=observation, status="error"))
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                    observation = f"Written {len(content)} chars to {rel_path}"
                except Exception as exc:
                    observation = f"Write failed: {exc}"
            steps.append(_AgentStep(step=step_num, action=f"write_file:{rel_path}", result=observation, status="success"))

        elif action_type == "run_analysis":
            # Delegate to the lint endpoint for a quick static check
            analysis_target = action_data.get("path", "")
            try:
                lint_r = analysis_lint(_LintReq(project=req.project, file_path=analysis_target))
                issue_count = len(lint_r.get("issues", []))
                observation = f"Lint: {issue_count} issue(s) in {analysis_target}"
            except Exception as exc:
                observation = f"Analysis error: {exc}"
            steps.append(_AgentStep(step=step_num, action=f"run_analysis:{analysis_target}", result=observation, status="success"))

        else:
            observation = f"Unknown action type '{action_type}' — skipped."
            steps.append(_AgentStep(step=step_num, action=action_type, result=observation, status="skipped"))

        # Feed observation back
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
            f"Observation from step {step_num}: {observation}\n"
            "Continue toward the goal. Return your next action JSON, or {{\"action\": \"done\", \"content\": \"<summary>\"}} when finished."
        })

    return {
        "project": req.project,
        "goal":    req.goal,
        "steps":   [s.model_dump() for s in steps],
        "total_steps": len(steps),
        "final_answer": final_answer,
        "dry_run": req.dry_run,
    }


# ─────────────────────────────────────────────────────────────────────────────
# P2-2 — Visual Studio / VS Code deeper integration helpers
# These endpoints are consumed by the Arbiter VSIX and VS Code extension to
# provide richer in-editor AI features beyond the basic chat/completion flow.
# ─────────────────────────────────────────────────────────────────────────────

class _InlineCompletionReq(BaseModel):
    project: str = "default"
    file_path: str = ""
    prefix: str              # code before the cursor
    suffix: str = ""         # code after the cursor (for FIM models)
    language: str = ""       # e.g. "csharp", "python"
    max_tokens: int = 256


@app.post("/vs/inline-completion")
async def vs_inline_completion(req: _InlineCompletionReq) -> dict:
    """Generate an inline code completion for the VS / VS Code cursor position.

    Designed for low-latency fill-in-the-middle (FIM) style requests from
    the VSIX / VS Code extension.  Returns a single best-completion string.

    P2-2
    """
    lang_hint = f" ({req.language})" if req.language else ""
    prompt = (
        f"Complete the following{lang_hint} code at the cursor position (marked <CURSOR>).\n"
        "Return ONLY the completion text — no markdown, no explanation.\n\n"
        f"```\n{req.prefix}<CURSOR>{req.suffix}\n```"
    )
    try:
        completion = await _asyncio.to_thread(
            _llm.chat,
            [{"role": "user", "content": prompt}],
        )
        # Trim common artefacts
        completion = completion.strip().removeprefix("```").removesuffix("```").strip()
    except Exception as exc:
        return {"completion": "", "error": str(exc)}

    return {
        "project":    req.project,
        "file":       req.file_path,
        "completion": completion,
    }


class _DiagnosticsReq(BaseModel):
    project: str = "default"
    file_path: str = ""
    content: str             # full file content
    language: str = ""
    diagnostics: list[dict] = []   # raw IDE diagnostics (errors/warnings)


@app.post("/vs/explain-diagnostic")
async def vs_explain_diagnostic(req: _DiagnosticsReq) -> dict:
    """Return AI explanations and fix suggestions for IDE diagnostics.

    Accepts the list of compiler/linter diagnostic objects that the IDE has
    already surfaced and returns a human-readable explanation + suggested fix
    for each one.

    P2-2
    """
    if not req.diagnostics:
        return {"project": req.project, "explanations": []}

    diag_text = "\n".join(
        f"  [{d.get('severity','?')}] Line {d.get('line','?')}: {d.get('message','')}"
        for d in req.diagnostics[:20]   # cap at 20 to stay within context window
    )
    snippet = req.content[:2000]
    prompt = (
        f"You are an expert {req.language or 'code'} debugger.\n"
        "Explain each diagnostic below and suggest the minimal fix. "
        "Return a JSON array:\n"
        '[{"line": <n>, "message": "<original msg>", "explanation": "...", "fix": "..."}]\n'
        "Output ONLY the JSON array.\n\n"
        f"Diagnostics:\n{diag_text}\n\n"
        f"File excerpt:\n```\n{snippet}\n```"
    )
    try:
        raw = await _asyncio.to_thread(
            _llm.chat,
            [{"role": "user", "content": prompt}],
        )
        arr_match = _re.search(r"\[[\s\S]+\]", raw)
        explanations = json.loads(arr_match.group()) if arr_match else []
    except Exception as exc:
        explanations = [{"error": str(exc)}]

    return {"project": req.project, "file": req.file_path, "explanations": explanations}


class _RefactorReq(BaseModel):
    project: str = "default"
    file_path: str = ""
    content: str              # full file content
    selection: str = ""       # selected code block (optional)
    instruction: str          # e.g. "extract method", "rename variable X to Y", "add null checks"
    language: str = ""


@app.post("/vs/refactor")
async def vs_refactor(req: _RefactorReq) -> dict:
    """Apply an AI refactoring instruction to a file or selection.

    Returns the rewritten code.  The caller (VSIX / VS Code extension)
    replaces the current selection or full file with the returned content.

    P2-2
    """
    target = req.selection or req.content
    lang_hint = f" {req.language}" if req.language else ""
    prompt = (
        f"Apply the following refactoring to this{lang_hint} code:\n"
        f"Instruction: {req.instruction}\n\n"
        "Return ONLY the refactored code with no explanation or markdown fences.\n\n"
        f"```\n{target[:4000]}\n```"
    )
    try:
        refactored = await _asyncio.to_thread(
            _llm.chat,
            [{"role": "user", "content": prompt}],
        )
        refactored = refactored.strip().removeprefix("```").removesuffix("```").strip()
        # Strip a leading language tag like "python" or "csharp" if present
        lines = refactored.splitlines()
        if lines and not lines[0].strip().startswith((" ", "\t")) and len(lines[0].strip()) < 20:
            refactored = "\n".join(lines[1:]).strip()
    except Exception as exc:
        return {"refactored": "", "error": str(exc)}

    return {
        "project":    req.project,
        "file":       req.file_path,
        "instruction": req.instruction,
        "refactored": refactored,
    }


@app.get("/vs/capabilities")
def vs_capabilities() -> dict:
    """Return the set of VS / VS Code integration features supported by this engine.

    The VSIX / VS Code extension queries this on startup to enable/disable
    feature flags.

    P2-2
    """
    return {
        "inline_completion":   True,
        "explain_diagnostic":  True,
        "refactor":            True,
        "chat":                True,
        "review":              True,
        "diff":                True,
        "diagram":             True,
        "test_generate":       True,
        "coverage_hints":      True,
        "lint":                True,
        "complexity":          True,
        "docs_generate":       True,
        "agent_run":           True,
        "version":             "2.0.0",
    }


# ─────────────────────────────────────────────────────────────────────────────
# P2-4 — Open-source model integration: list available backends + models
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/models/backends")
def models_backends() -> dict:
    """Return all configured LLM backends and their availability status.

    Allows the IDE and remote web UI to present a model-switcher with live
    status (reachable / not reachable) for each configured backend.

    P2-4
    """
    import importlib

    backends_config = {
        "ollama":    {"label": "Ollama",    "url": _config.get("llm.ollama.base_url",    "http://localhost:11434"), "model": _config.get("llm.ollama.model", "llama3")},
        "lmstudio":  {"label": "LM Studio", "url": _config.get("llm.lmstudio.base_url",  "http://localhost:1234"),  "model": _config.get("llm.lmstudio.model", "")},
        "localai":   {"label": "LocalAI",   "url": _config.get("llm.localai.base_url",   "http://localhost:8080"),  "model": _config.get("llm.localai.model", "codestral")},
        "llamacpp":  {"label": "llama.cpp", "url": _config.get("llm.llamacpp.base_url",  "http://localhost:8080"),  "model": _config.get("llm.llamacpp.model", "")},
        "tabby":     {"label": "Tabby",     "url": _config.get("llm.tabby.base_url",     "http://localhost:8080"),  "model": _config.get("llm.tabby.model", "")},
        "openwebui": {"label": "OpenWebUI", "url": _config.get("llm.openwebui.base_url", "http://localhost:3000"),  "model": _config.get("llm.openwebui.model", "")},
        "codegeex":  {"label": "CodeGeeX",  "url": _config.get("llm.codegeex.base_url",  "http://localhost:8082"),  "model": _config.get("llm.codegeex.model", "codegeex-4-all-9b")},
        "api":       {"label": "OpenAI API","url": _config.get("llm.api.base_url",       "https://api.openai.com"), "model": _config.get("llm.api.model", "gpt-4o")},
        "anthropic": {"label": "Anthropic", "url": "https://api.anthropic.com",                                     "model": _config.get("llm.anthropic.model", "claude-3-5-sonnet-20241022")},
        "gemini":    {"label": "Gemini",    "url": "https://generativelanguage.googleapis.com",                     "model": _config.get("llm.gemini.model", "gemini-2.0-flash")},
    }

    import requests as _req_mod
    result = []
    for key, info in backends_config.items():
        url = info["url"]
        reachable = False
        if url.startswith("http"):
            try:
                _req_mod.get(url, timeout=2)
                reachable = True
            except Exception:
                reachable = False
        result.append({
            "id":       key,
            "label":    info["label"],
            "url":      url,
            "model":    info["model"],
            "reachable": reachable,
            "active":   key == _config.get("agent.default_llm_backend", "ollama"),
        })

    return {"backends": result, "active_backend": _config.get("agent.default_llm_backend", "ollama")}


@app.post("/models/switch")
async def models_switch(backend: str, model: str = "") -> dict:
    """Hot-switch the active LLM backend without restarting the server.

    Updates the in-memory config and replaces the global ``_llm`` instance.
    The change is not persisted to disk — restart the server to make it permanent.

    P2-4
    """
    global _llm
    try:
        from llm.factory import create_llm as _create_llm
        # Temporarily override config keys for the new backend
        if model:
            _config._data[f"llm.{backend}.model"] = model
        _config._data["agent.default_llm_backend"] = backend
        new_llm = await _asyncio.to_thread(_create_llm, backend, _config)
        _llm = new_llm
        logger.info("Switched LLM backend to %s (model=%s)", backend, model or "default")
        return {"status": "ok", "backend": backend, "model": model or "default"}
    except Exception as exc:
        logger.error("Failed to switch LLM backend: %s", exc)
        return {"status": "error", "error": str(exc)}


# =============================================================================
# Arbiter Admin Infrastructure — Roles, Audit Log, Notifications, Dashboard
# =============================================================================
# /roles/*   — Arbiter API access control (Admin/Moderator/Operator/Player)
# /audit/*   — Arbiter operation audit log + change notifications
# /dashboard — Arbiter admin dashboard (health, AI backends, roles, audit)
# =============================================================================

import hashlib as _hashlib

# ─────────────────────────────────────────────────────────────────────────────
# Shared state
# ─────────────────────────────────────────────────────────────────────────────

# Audit log file — records all Arbiter role changes and notable API operations
_AUDIT_LOG_PATH = _BASE / ".arbiter" / "logs" / "audit.jsonl"
_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# Role definitions (ordered by privilege, highest first)
_ROLE_HIERARCHY: list[str] = ["admin", "moderator", "operator", "player"]

# User → role mapping (in-memory + persisted to JSON)
_ROLES_FILE = _BASE / ".arbiter" / "roles.json"
_user_roles: dict[str, str] = {}  # username → role

# Pending notifications queue (polled by /audit/notifications)
_pending_notifications: list[dict] = []
_notif_lock = threading.Lock()


def _load_roles() -> None:
    global _user_roles
    if _ROLES_FILE.exists():
        try:
            _user_roles = json.loads(_ROLES_FILE.read_text(encoding="utf-8"))
        except Exception:
            _user_roles = {}


def _save_roles() -> None:
    _ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ROLES_FILE.write_text(json.dumps(_user_roles, indent=2), encoding="utf-8")


_load_roles()


def _write_audit(event: str, actor: str, target: str, detail: dict) -> None:
    """Append a single audit event to the JSONL audit log."""
    entry = {
        "ts":     datetime.datetime.utcnow().isoformat(),
        "event":  event,
        "actor":  actor,
        "target": target,
        **detail,
    }
    try:
        with open(_AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    with _notif_lock:
        _pending_notifications.append(entry)
        if len(_pending_notifications) > 500:
            _pending_notifications.pop(0)


# ─────────────────────────────────────────────────────────────────────────────
# Role-Based Access Control for the Arbiter API
# ─────────────────────────────────────────────────────────────────────────────
# Roles (highest → lowest privilege):
#   admin      — full access (all operations, role management, audit log)
#   moderator  — can issue project/chat operations; cannot manage roles
#   operator   — read-only status + metrics access
#   player     — read-only status
# ─────────────────────────────────────────────────────────────────────────────

_ROLE_ACTIONS: dict[str, set[str]] = {
    "admin":     {"all", "roles.manage", "audit.read", "status", "metrics", "projects", "chat", "analysis"},
    "moderator": {"projects", "chat", "analysis", "audit.read", "status", "metrics"},
    "operator":  {"status", "metrics"},
    "player":    {"status"},
}


class _RoleAssignReq(BaseModel):
    username: str
    role: str
    actor: str = "admin"


class _RoleCheckReq(BaseModel):
    username: str
    action: str


@app.post("/roles/assign")
def roles_assign(req: _RoleAssignReq) -> dict:
    """Assign an Arbiter API role to a user.

    Roles: ``admin``, ``moderator``, ``operator``, ``player``.
    Every assignment is written to the audit log.
    """
    role = req.role.lower()
    if role not in _ROLE_HIERARCHY:
        raise HTTPException(status_code=400, detail=f"Unknown role '{role}'. Valid: {_ROLE_HIERARCHY}")

    previous = _user_roles.get(req.username, "none")
    _user_roles[req.username] = role
    _save_roles()
    _write_audit("role.assign", req.actor, req.username, {"role": role, "previous_role": previous})
    logger.info("[Roles] %s → %s (actor: %s)", req.username, role, req.actor)
    return {"status": "ok", "username": req.username, "role": role, "previous_role": previous}


@app.delete("/roles/{username}")
def roles_revoke(username: str, actor: str = "admin") -> dict:
    """Remove a user's role assignment."""
    if username not in _user_roles:
        raise HTTPException(status_code=404, detail=f"User '{username}' has no role assigned")
    removed_role = _user_roles.pop(username)
    _save_roles()
    _write_audit("role.revoke", actor, username, {"removed_role": removed_role})
    return {"status": "ok", "username": username, "removed_role": removed_role}


@app.get("/roles/{username}")
def roles_get(username: str) -> dict:
    """Return the role and permitted actions for a user."""
    role = _user_roles.get(username)
    if role is None:
        return {"username": username, "role": None, "actions": []}
    return {
        "username": username,
        "role":     role,
        "actions":  sorted(_ROLE_ACTIONS.get(role, set())),
    }


@app.get("/roles")
def roles_list() -> dict:
    """Return all role assignments and the role hierarchy."""
    return {
        "assignments": [{"username": u, "role": r} for u, r in _user_roles.items()],
        "hierarchy":   _ROLE_HIERARCHY,
        "actions_map": {r: sorted(a) for r, a in _ROLE_ACTIONS.items()},
    }


@app.post("/roles/check")
def roles_check(req: _RoleCheckReq) -> dict:
    """Check whether a user is permitted to perform a given action."""
    role = _user_roles.get(req.username)
    if role is None:
        return {"username": req.username, "action": req.action, "allowed": False, "reason": "no role assigned"}

    role_idx = _ROLE_HIERARCHY.index(role) if role in _ROLE_HIERARCHY else len(_ROLE_HIERARCHY)
    allowed_actions: set[str] = set()
    for r in _ROLE_HIERARCHY[:role_idx + 1]:
        allowed_actions |= _ROLE_ACTIONS.get(r, set())

    allowed = "all" in allowed_actions or req.action in allowed_actions
    return {"username": req.username, "role": role, "action": req.action, "allowed": allowed}


# ─────────────────────────────────────────────────────────────────────────────
# Arbiter Audit Log
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/audit/log")
def audit_log(limit: int = 100, event_type: str = "") -> dict:
    """Return the last *limit* entries from the Arbiter audit log.

    Filter by ``event_type`` prefix (e.g. ``role.assign``, ``chat``).
    """
    if not _AUDIT_LOG_PATH.exists():
        return {"entries": [], "total": 0}
    try:
        lines = _AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"entries": [], "total": 0}

    entries: list[dict] = []
    for line in lines:
        if line.strip():
            try:
                entry = json.loads(line)
                if not event_type or entry.get("event", "").startswith(event_type):
                    entries.append(entry)
            except Exception:
                pass
    return {"entries": entries[-limit:], "total": len(entries)}


@app.get("/audit/notifications")
def audit_notifications(clear: bool = True) -> dict:
    """Return pending audit change notifications (long-poll style).

    The Arbiter dashboard polls this endpoint to display real-time
    role/operation change notifications.  Set ``clear=true`` (default)
    to consume and remove the notifications from the queue.
    """
    with _notif_lock:
        notifs = list(_pending_notifications)
        if clear:
            _pending_notifications.clear()
    return {"notifications": notifs, "count": len(notifs)}


@app.get("/audit/stats")
def audit_stats() -> dict:
    """Return aggregate statistics from the Arbiter audit log."""
    if not _AUDIT_LOG_PATH.exists():
        return {"total": 0, "by_event": {}, "by_actor": {}}
    by_event: dict[str, int] = {}
    by_actor: dict[str, int] = {}
    total = 0
    try:
        for line in _AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                total += 1
                by_event[e.get("event", "?")] = by_event.get(e.get("event", "?"), 0) + 1
                by_actor[e.get("actor", "?")] = by_actor.get(e.get("actor", "?"), 0) + 1
            except Exception:
                pass
    except Exception:
        pass
    return {"total": total, "by_event": by_event, "by_actor": by_actor}


# ─────────────────────────────────────────────────────────────────────────────
# Arbiter Admin Dashboard
# ─────────────────────────────────────────────────────────────────────────────

_ARBITER_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Arbiter Admin Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:      #0d0f11;
    --panel:   #161a1e;
    --card:    #1f2429;
    --border:  #2c3540;
    --accent:  #00c896;
    --accent2: #007acc;
    --fg:      #dde3ec;
    --fg-dim:  #8b96a5;
    --danger:  #e05c5c;
    --warn:    #e0a84d;
    --ok:      #4dc98a;
    --font:    "Segoe UI", system-ui, sans-serif;
    --radius:  8px;
    --shadow:  0 2px 12px rgba(0,0,0,.45);
  }
  body { background: var(--bg); color: var(--fg); font-family: var(--font); min-height: 100vh; }
  header {
    background: var(--panel); border-bottom: 1px solid var(--border);
    padding: 14px 24px; display: flex; align-items: center; gap: 12px;
    position: sticky; top: 0; z-index: 100; box-shadow: var(--shadow);
  }
  header h1 { font-size: 1.15rem; font-weight: 600; letter-spacing: .03em; }
  .badge { font-size: .7rem; background: var(--accent); color: #000; border-radius: 4px; padding: 2px 7px; font-weight: 700; }
  .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; background: var(--fg-dim); }
  .dot.ok { background: var(--ok); } .dot.warn { background: var(--warn); } .dot.err { background: var(--danger); }
  main { max-width: 1280px; margin: 0 auto; padding: 24px 20px; }
  .grid2 { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 18px; margin-bottom: 24px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px; box-shadow: var(--shadow); }
  .card-title { font-size: .78rem; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; color: var(--fg-dim); margin-bottom: 12px; }
  .stat { font-size: 2rem; font-weight: 700; color: var(--accent); }
  .stat-label { font-size: .75rem; color: var(--fg-dim); margin-top: 2px; }
  .row { display: flex; align-items: center; gap: 8px; padding: 7px 0; border-bottom: 1px solid var(--border); font-size: .85rem; }
  .row:last-child { border-bottom: none; }
  .row .name { flex: 1; font-weight: 500; }
  .row .meta { font-size: .72rem; color: var(--fg-dim); }
  .btn { background: var(--card); border: 1px solid var(--border); color: var(--fg); border-radius: 5px; padding: 5px 12px; font-size: .78rem; cursor: pointer; transition: background .15s; }
  .btn:hover { background: var(--border); }
  .btn.primary { background: var(--accent2); border-color: var(--accent2); color: #fff; }
  .btn.primary:hover { background: #0069b3; }
  .btn.danger { background: var(--danger); border-color: var(--danger); color: #fff; }
  input, select { background: var(--bg); border: 1px solid var(--border); color: var(--fg); border-radius: 5px; padding: 6px 10px; font-size: .85rem; }
  input:focus, select:focus { outline: none; border-color: var(--accent2); }
  .form-row { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
  .section-hdr { font-size: 1rem; font-weight: 600; border-bottom: 1px solid var(--border); padding-bottom: 8px; margin: 24px 0 14px; }
  .audit-table { width: 100%; border-collapse: collapse; font-size: .78rem; }
  .audit-table th, .audit-table td { padding: 7px 10px; text-align: left; border-bottom: 1px solid var(--border); }
  .audit-table th { color: var(--fg-dim); font-weight: 600; }
  .role-chip { display: inline-flex; align-items: center; gap: 5px; background: var(--panel); border: 1px solid var(--border); border-radius: 20px; padding: 3px 11px; font-size: .75rem; margin: 3px; }
  .role-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--fg-dim); }
  [data-role="admin"]     .role-dot { background: var(--danger); }
  [data-role="moderator"] .role-dot { background: var(--warn); }
  [data-role="operator"]  .role-dot { background: var(--accent2); }
  [data-role="player"]    .role-dot { background: var(--ok); }
  .backend-chip { display: inline-flex; align-items: center; gap: 6px; background: var(--panel); border: 1px solid var(--border); border-radius: 5px; padding: 5px 12px; font-size: .78rem; margin: 3px; }
  #log-panel { background: var(--bg); border: 1px solid var(--border); border-radius: 5px; padding: 10px 12px; font-size: .72rem; font-family: monospace; height: 140px; overflow-y: auto; color: var(--accent); white-space: pre-wrap; margin-top: 10px; }
  #notif-bar { position: fixed; bottom: 20px; right: 20px; display: flex; flex-direction: column; gap: 8px; z-index: 9999; max-width: 340px; }
  .notif { background: var(--card); border: 1px solid var(--accent); border-radius: var(--radius); padding: 10px 14px; font-size: .8rem; box-shadow: var(--shadow); animation: slideIn .2s ease; }
  @keyframes slideIn { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:none; } }
  #clock { font-size: .8rem; color: var(--fg-dim); }
  .tag { font-size: .68rem; background: var(--border); border-radius: 3px; padding: 1px 5px; color: var(--fg-dim); }
</style>
</head>
<body>
<header>
  <span class="dot ok" id="engine-dot"></span>
  <h1>Arbiter Admin Dashboard</h1>
  <span class="badge">v1.5</span>
  <span style="flex:1"></span>
  <span id="clock"></span>
</header>
<main>

  <!-- ── Status cards ──────────────────────────────────────────────────────── -->
  <div class="grid2" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr))">
    <div class="card">
      <div class="card-title">Engine Status</div>
      <div class="stat" id="engine-status">—</div>
      <div class="stat-label">Arbiter AI Engine</div>
    </div>
    <div class="card">
      <div class="card-title">Active LLM Backend</div>
      <div class="stat" id="active-backend" style="font-size:1.2rem">—</div>
      <div class="stat-label" id="active-model">—</div>
    </div>
    <div class="card">
      <div class="card-title">Audit Events</div>
      <div class="stat" id="audit-total">—</div>
      <div class="stat-label">Total logged</div>
    </div>
    <div class="card">
      <div class="card-title">Role Assignments</div>
      <div class="stat" id="roles-total">—</div>
      <div class="stat-label">Users with roles</div>
    </div>
  </div>

  <!-- ── LLM Backends ──────────────────────────────────────────────────────── -->
  <div class="section-hdr">LLM Backends</div>
  <div class="card" style="margin-bottom:24px">
    <div class="card-title">Configured Backends</div>
    <div id="backends-list"><em style="color:var(--fg-dim)">Loading…</em></div>
    <div class="form-row" style="margin-top:14px">
      <select id="switch-backend">
        <option value="ollama">ollama</option>
        <option value="openai">openai</option>
        <option value="codegeex">codegeex</option>
        <option value="lmstudio">lmstudio</option>
      </select>
      <input id="switch-model" placeholder="model (optional)" style="width:180px">
      <button class="btn primary" onclick="switchBackend()">Switch Backend</button>
    </div>
  </div>

  <!-- ── Roles ──────────────────────────────────────────────────────────────── -->
  <div class="section-hdr">API Role Assignments</div>
  <div class="grid2">
    <div class="card">
      <div class="card-title">Current Assignments</div>
      <div id="roles-chips"><em style="color:var(--fg-dim)">Loading…</em></div>
      <div class="form-row">
        <input id="role-user"  placeholder="username"  style="width:130px">
        <select id="role-sel">
          <option value="admin">admin</option>
          <option value="moderator">moderator</option>
          <option value="operator" selected>operator</option>
          <option value="player">player</option>
        </select>
        <button class="btn primary" onclick="assignRole()">Assign</button>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Role Permissions</div>
      <div id="role-perms" style="font-size:.78rem; line-height:1.6"></div>
    </div>
  </div>

  <!-- ── Audit Log ─────────────────────────────────────────────────────────── -->
  <div class="section-hdr">Audit Log</div>
  <div class="card" style="margin-bottom:24px; overflow-x:auto">
    <div class="card-title">Recent Events
      <span id="audit-stats-inline" style="font-weight:400; color:var(--fg-dim); margin-left:8px"></span>
    </div>
    <table class="audit-table">
      <thead><tr><th>Time</th><th>Event</th><th>Actor</th><th>Target</th></tr></thead>
      <tbody id="audit-tbody"><tr><td colspan="4" style="color:var(--fg-dim)">Loading…</td></tr></tbody>
    </table>
  </div>

  <!-- ── Engine Log ────────────────────────────────────────────────────────── -->
  <div class="section-hdr">Engine Activity</div>
  <div id="log-panel">Waiting for notifications…</div>

</main>
<div id="notif-bar"></div>
<script>
const API = '';

async function api(method, path, body) {
  const opts = {method, headers: {'Content-Type':'application/json'}};
  if (body) opts.body = JSON.stringify(body);
  try { const r = await fetch(API + path, opts); return await r.json(); }
  catch(e) { return {error: e.toString()}; }
}

function log(msg) {
  const el = document.getElementById('log-panel');
  el.textContent += new Date().toISOString().slice(11,19) + '  ' + msg + '\n';
  el.scrollTop = el.scrollHeight;
}

function notify(msg) {
  const bar = document.getElementById('notif-bar');
  const n = document.createElement('div');
  n.className = 'notif'; n.textContent = msg; bar.appendChild(n);
  setTimeout(() => n.remove(), 5000);
}

function ts(s) { return s ? s.replace('T',' ').slice(0,19) : ''; }

function updateClock() {
  document.getElementById('clock').textContent = new Date().toUTCString().slice(5,25) + ' UTC';
}
setInterval(updateClock, 1000); updateClock();

// Health check
async function loadHealth() {
  const d = await api('GET', '/health');
  document.getElementById('engine-status').textContent = d.status === 'ok' ? 'Online' : 'Degraded';
  const dot = document.getElementById('engine-dot');
  dot.className = 'dot ' + (d.status === 'ok' ? 'ok' : 'err');
  const backends = d.backends || {};
  const primary = Object.entries(backends).find(([,v]) => v.reachable);
  document.getElementById('active-backend').textContent = primary ? primary[0] : (Object.keys(backends)[0] || '—');
  document.getElementById('active-model').textContent   = primary ? ((primary[1].models||[])[0]||'no model info') : 'unreachable';

  const el = document.getElementById('backends-list');
  el.innerHTML = Object.entries(backends).map(([name, info]) =>
    `<span class="backend-chip">
       <span class="dot ${info.reachable ? 'ok' : 'err'}"></span>
       <b>${name}</b>
       <span class="tag">${info.reachable ? info.latency_ms + 'ms' : 'unreachable'}</span>
       ${info.models && info.models.length ? '<span class="tag">' + info.models.slice(0,2).join(', ') + '</span>' : ''}
     </span>`
  ).join('');
}

// Switch backend
async function switchBackend() {
  const backend = document.getElementById('switch-backend').value;
  const model   = document.getElementById('switch-model').value.trim() || undefined;
  const d = await api('POST', '/models/switch', {backend, model});
  log('Switch backend: ' + JSON.stringify(d));
  notify('Backend → ' + (d.backend||'?'));
  loadHealth();
}

// Roles
async function loadRoles() {
  const d = await api('GET', '/roles');
  document.getElementById('roles-total').textContent = (d.assignments||[]).length;
  const chips = document.getElementById('roles-chips');
  chips.innerHTML = (d.assignments||[]).length === 0
    ? '<em style="color:var(--fg-dim)">No assignments.</em>'
    : (d.assignments||[]).map(a =>
        `<span class="role-chip" data-role="${a.role}"><span class="role-dot"></span>${a.username} <em style="color:var(--fg-dim)">(${a.role})</em></span>`
      ).join('');
  const permsEl = document.getElementById('role-perms');
  permsEl.innerHTML = Object.entries(d.actions_map||{}).map(([r, acts]) =>
    `<div style="margin-bottom:4px"><b>${r}</b>: <span style="color:var(--fg-dim)">${acts.join(', ')}</span></div>`
  ).join('');
}

async function assignRole() {
  const user = document.getElementById('role-user').value.trim();
  const role = document.getElementById('role-sel').value;
  if (!user) { notify('Enter a username'); return; }
  const d = await api('POST', '/roles/assign', {username:user, role, actor:'dashboard'});
  log('Assign role: ' + JSON.stringify(d));
  notify(user + ' → ' + role);
  loadRoles();
}

// Audit log
async function loadAudit() {
  const d = await api('GET', '/audit/log?limit=20');
  document.getElementById('audit-total').textContent = d.total || 0;
  const tbody = document.getElementById('audit-tbody');
  if (!d.entries || d.entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="color:var(--fg-dim)">No events yet.</td></tr>'; return;
  }
  tbody.innerHTML = [...d.entries].reverse().map(e =>
    `<tr><td>${ts(e.ts)}</td><td>${e.event}</td><td>${e.actor}</td><td>${e.target||''}</td></tr>`
  ).join('');
  const stats = await api('GET', '/audit/stats');
  document.getElementById('audit-stats-inline').textContent =
    'Total: ' + stats.total + '  |  By event: ' + Object.entries(stats.by_event||{}).map(([k,v])=>k+'='+v).join(', ');
}

// Notification polling
async function pollNotifications() {
  const d = await api('GET', '/audit/notifications?clear=true');
  if (d.notifications && d.notifications.length > 0) {
    d.notifications.forEach(n => {
      notify('[' + n.event + '] ' + (n.target||''));
      log('Notification: ' + JSON.stringify(n).slice(0,120));
    });
    loadAudit();
  }
}

async function refresh() {
  await Promise.all([loadHealth(), loadRoles(), loadAudit()]);
}

refresh();
setInterval(pollNotifications, 5000);
setInterval(refresh, 20000);
</script>
</body>
</html>"""


@app.get("/dashboard", response_class=_HTMLResponse)
def arbiter_dashboard() -> _HTMLResponse:
    """Serve the Arbiter Admin Dashboard.

    A self-contained dark-mode HTML page (no CDN dependencies) showing:
    - Arbiter Engine health and LLM backend status
    - Backend switcher (live hot-swap)
    - API role assignments and permissions reference
    - Audit log table with real-time notification polling
    - Engine activity panel

    This is an Arbiter-native admin tool.  Game server management
    (SSA) and game-engine tooling (Novaforge) are worked on as
    independent projects from within Arbiter, not integrated here.
    """
    return _HTMLResponse(content=_ARBITER_DASHBOARD_HTML, status_code=200)


# =============================================================================
# Phase 3 — Project-Aware Workspace Intelligence
# =============================================================================
# P3-1  POST /projects/{id}/activate   — prime AI context with project data
# P3-2  GET  /projects/{id}/health     — roadmap completion + git activity
# P3-3  GET  /git/status|log|diff      — live git introspection
# P3-4  GET/POST /workspace/state      — persist workspace preferences
# P3-5  POST /projects/scaffold        — AI-assisted new project scaffolding
# =============================================================================

import subprocess as _subprocess

# ─────────────────────────────────────────────────────────────────────────────
# Workspace state (P3-4) — in-memory + persisted to .arbiter/workspace_state.json
# ─────────────────────────────────────────────────────────────────────────────

_WORKSPACE_STATE_PATH = _BASE / ".arbiter" / "workspace_state.json"
_workspace_state: dict = {}
_workspace_state_lock = threading.Lock()


def _load_workspace_state() -> None:
    global _workspace_state
    if _WORKSPACE_STATE_PATH.exists():
        try:
            _workspace_state = json.loads(
                _WORKSPACE_STATE_PATH.read_text(encoding="utf-8")
            )
        except Exception:
            _workspace_state = {}


def _save_workspace_state() -> None:
    _WORKSPACE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _WORKSPACE_STATE_PATH.write_text(
        json.dumps(_workspace_state, indent=2), encoding="utf-8"
    )


_load_workspace_state()


# ─────────────────────────────────────────────────────────────────────────────
# P3-1 — Activate project: prime AI context
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/projects/{project_id}/activate")
async def project_activate(project_id: str) -> dict:
    """Prime the AI context with a project's roadmap, key files, and recent commits.

    Loads the project's ``roadmap.json``, lists top-level source files, and
    fetches the five most recent git commits.  All of this is injected as a
    system-level context message so subsequent ``/chat`` requests are
    automatically project-aware.

    P3-1
    """
    project_dir = _BASE.parent.parent / "Projects" / project_id
    if not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    context_parts: list[str] = [f"# Arbiter project context: {project_id}\n"]

    # Roadmap
    roadmap_path = project_dir / "roadmap.json"
    if roadmap_path.exists():
        try:
            roadmap_data = json.loads(roadmap_path.read_text(encoding="utf-8"))
            pending_tasks = [
                f"{ph.get('id','?')} / {t['id']}: {t['title']}"
                for ph in roadmap_data.get("phases", [])
                for t in ph.get("tasks", [])
                if t.get("status") == "pending"
            ]
            total_tasks = sum(
                len(ph.get("tasks", []))
                for ph in roadmap_data.get("phases", [])
            )
            done_tasks = total_tasks - len(pending_tasks)
            context_parts.append(
                f"## Roadmap: {roadmap_data.get('project', project_id)} "
                f"v{roadmap_data.get('version', '?')}\n"
                f"Progress: {done_tasks}/{total_tasks} tasks done.\n"
                "Pending tasks:\n" +
                "\n".join(f"  - {t}" for t in pending_tasks[:20])
            )
        except Exception as exc:
            context_parts.append(f"## Roadmap: (parse error: {exc})")

    # Key source files
    src_files: list[str] = []
    for ext in ("*.py", "*.cs", "*.json"):
        src_files.extend(
            str(p.relative_to(project_dir))
            for p in project_dir.rglob(ext)
            if ".git" not in p.parts and len(src_files) < 30
        )
    if src_files:
        context_parts.append("## Key files\n" + "\n".join(f"  {f}" for f in src_files[:30]))

    # Recent git commits
    try:
        git_log = _subprocess.check_output(
            ["git", "log", "--oneline", "-5",
             "--", str(project_dir)],
            cwd=str(_BASE.parent.parent),
            stderr=_subprocess.DEVNULL,
            timeout=5,
        ).decode(errors="replace").strip()
        if git_log:
            context_parts.append("## Recent commits\n" + git_log)
    except Exception:
        pass

    context_msg = "\n\n".join(context_parts)

    # Inject into conversation history cache under a reserved key
    with _workspace_state_lock:
        _workspace_state["active_project"] = project_id
        _workspace_state["active_project_context"] = context_msg
        _save_workspace_state()

    logger.info("[P3-1] Activated project context: %s (%d chars)", project_id, len(context_msg))
    return {
        "status":     "activated",
        "project_id": project_id,
        "context_length": len(context_msg),
        "summary":    context_parts[1][:200] if len(context_parts) > 1 else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# P3-2 — Project health
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/projects/{project_id}/health")
async def project_health(project_id: str) -> dict:
    """Return a health summary for a project: roadmap progress and git activity.

    P3-2
    """
    project_dir = _BASE.parent.parent / "Projects" / project_id
    if not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    result: dict = {"project_id": project_id}

    # Roadmap stats
    roadmap_path = project_dir / "roadmap.json"
    if roadmap_path.exists():
        try:
            rd = json.loads(roadmap_path.read_text(encoding="utf-8"))
            phases = rd.get("phases", [])
            total = sum(len(ph.get("tasks", [])) for ph in phases)
            done  = sum(
                1 for ph in phases
                for t in ph.get("tasks", [])
                if t.get("status") == "done"
            )
            active_phase = next(
                (ph for ph in phases if ph.get("status") == "active"), None
            )
            result["roadmap"] = {
                "version":       rd.get("version", "?"),
                "total_tasks":   total,
                "done_tasks":    done,
                "pending_tasks": total - done,
                "completion_pct": round(done / total * 100, 1) if total else 0,
                "active_phase":  active_phase.get("id") if active_phase else None,
                "active_phase_title": active_phase.get("name", "") if active_phase else "",
            }
        except Exception as exc:
            result["roadmap"] = {"error": str(exc)}

    # Recent git activity for this project path
    try:
        git_log = _subprocess.check_output(
            ["git", "log", "--oneline", "--format=%h %ad %s",
             "--date=short", "-10", "--", str(project_dir)],
            cwd=str(_BASE.parent.parent),
            stderr=_subprocess.DEVNULL,
            timeout=5,
        ).decode(errors="replace").strip()
        commits = [ln for ln in git_log.splitlines() if ln.strip()]
        result["git"] = {
            "recent_commits": commits,
            "last_commit": commits[0] if commits else None,
        }
    except Exception:
        result["git"] = {"error": "git unavailable"}

    return result


# ─────────────────────────────────────────────────────────────────────────────
# P3-3 — Git introspection
# The existing /git/status, /git/log, /git/diff endpoints (defined earlier in
# this file) already fulfil the workspace introspection requirement.  Phase 3
# adds the ``staged`` query parameter to /git/diff (patched at its definition)
# and documents these endpoints as P3-3 features.
# ─────────────────────────────────────────────────────────────────────────────
# P3-4 — Workspace state
# ─────────────────────────────────────────────────────────────────────────────

class _WorkspaceStateReq(BaseModel):
    active_project: str = ""
    recent_files: list[str] = []
    preferences: dict = {}


@app.get("/workspace/state")
def workspace_state_get() -> dict:
    """Return the persisted workspace state.

    P3-4
    """
    with _workspace_state_lock:
        # Omit the large context blob from the public response
        public = {k: v for k, v in _workspace_state.items()
                  if k != "active_project_context"}
    return {"state": public}


@app.post("/workspace/state")
def workspace_state_set(req: _WorkspaceStateReq) -> dict:
    """Update and persist workspace state.

    Merges the supplied fields into the existing state; unset fields are
    preserved.

    P3-4
    """
    with _workspace_state_lock:
        if req.active_project:
            _workspace_state["active_project"] = req.active_project
        if req.recent_files:
            existing = _workspace_state.get("recent_files", [])
            # Prepend new files, deduplicate, keep latest 20
            merged = req.recent_files + [f for f in existing if f not in req.recent_files]
            _workspace_state["recent_files"] = merged[:20]
        if req.preferences:
            _workspace_state.setdefault("preferences", {}).update(req.preferences)
        _save_workspace_state()
    return {"status": "ok", "state": {k: v for k, v in _workspace_state.items()
                                       if k != "active_project_context"}}


# ─────────────────────────────────────────────────────────────────────────────
# P3-5 — AI-assisted project scaffolding
# ─────────────────────────────────────────────────────────────────────────────

class _ScaffoldReq(BaseModel):
    project_id: str
    description: str
    tech_stack: list[str] = []
    phases: list[str] = []


@app.post("/projects/scaffold")
async def project_scaffold(req: _ScaffoldReq) -> dict:
    """Scaffold a new Arbiter-managed project via AI.

    Creates ``Projects/{project_id}/`` with a directory skeleton,
    ``roadmap.json``, and ``docs/.gitkeep``.  The AI generates an initial
    roadmap based on *description*.

    P3-5
    """
    project_id = req.project_id.strip()
    # Strict whitelist: alphanumeric, underscores, and hyphens only.
    # This prevents path traversal (e.g. '../', encoded variants) by construction.
    import re as _re
    if not project_id or not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
        raise HTTPException(
            status_code=422,
            detail="project_id must be 1–64 characters: letters, digits, _ or - only",
        )

    project_dir = _BASE.parent.parent / "Projects" / project_id
    # Belt-and-suspenders: resolve and confirm it stays inside Projects/
    projects_root = (_BASE.parent.parent / "Projects").resolve()
    if not project_dir.resolve().parent == projects_root:
        raise HTTPException(status_code=422, detail="Invalid project_id")
    if project_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Project '{project_id}' already exists at {project_dir}",
        )

    # ── Ask AI to draft an initial roadmap ───────────────────────────────────
    ai_prompt = (
        f"Draft a JSON roadmap for a software project called '{project_id}'.\n"
        f"Description: {req.description}\n"
        f"Tech stack: {', '.join(req.tech_stack) if req.tech_stack else 'not specified'}\n"
        f"Requested phases: {', '.join(req.phases) if req.phases else 'derive from description'}\n\n"
        "Return ONLY valid JSON matching this structure:\n"
        '{"project":"<id>","description":"<desc>","version":"0.1.0",'
        '"phases":[{"id":0,"name":"Phase 0 — Scaffold","status":"done","tasks":[]}]}'
    )

    roadmap_data: dict = {
        "project":     project_id,
        "description": req.description,
        "version":     "0.1.0",
        "last_updated": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
        "tech_stack":  req.tech_stack,
        "phases": [
            {
                "id": 0,
                "name": "Phase 0 — Scaffold & Setup",
                "status": "done",
                "description": "Initial project scaffold created by Arbiter.",
                "tasks": [
                    {"id": "S0-1", "title": "Project directory scaffold", "status": "done",
                     "notes": "Created by Arbiter /projects/scaffold"},
                ],
            },
            {
                "id": 1,
                "name": "Phase 1 — Core Implementation",
                "status": "pending",
                "description": "Core features as defined in the project description.",
                "tasks": [],
            },
        ],
    }

    # Try to enrich with AI if available
    if _llm is not None:
        try:
            ai_msgs = [
                {"role": "system", "content": "You are a technical project planner. Output only valid JSON."},
                {"role": "user",   "content": ai_prompt},
            ]
            ai_raw = await _asyncio.to_thread(_llm.chat, ai_msgs, max_tokens=1024)
            start = ai_raw.find("{")
            end   = ai_raw.rfind("}") + 1
            if start != -1 and end > start:
                parsed = json.loads(ai_raw[start:end])
                if "phases" in parsed:
                    roadmap_data.update(parsed)
        except Exception as exc:
            logger.warning("[P3-5] AI roadmap generation failed: %s", exc)

    # ── Create directory skeleton ─────────────────────────────────────────────
    dirs = ["src", "docs", "tests", "config", "scripts"]
    for d in dirs:
        (project_dir / d).mkdir(parents=True, exist_ok=True)
        (project_dir / d / ".gitkeep").touch()

    # roadmap.json
    (project_dir / "roadmap.json").write_text(
        json.dumps(roadmap_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # workspace_profile.json
    (project_dir / "workspace_profile.json").write_text(
        json.dumps({
            "project":     project_id,
            "description": req.description,
            "arbiter_managed": True,
        }, indent=2),
        encoding="utf-8",
    )

    logger.info("[P3-5] Scaffolded project '%s' at %s", project_id, project_dir)
    return {
        "status":      "created",
        "project_id":  project_id,
        "path":        str(project_dir),
        "files_created": [
            f"Projects/{project_id}/roadmap.json",
            f"Projects/{project_id}/workspace_profile.json",
        ] + [f"Projects/{project_id}/{d}/.gitkeep" for d in dirs],
    }


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = _config.get("server.host", "127.0.0.1")
    port = int(_config.get("server.port", 8001))
    logger.info("Starting Arbiter Engine at http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
