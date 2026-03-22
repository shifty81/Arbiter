"""
Arbiter AI — FastAPI Python Bridge
Handles chat requests, LLM inference, TTS voice output, model management, STT, and build/run/test.
"""

# ── Dependency bootstrap ──────────────────────────────────────────────────────
# Must run before any third-party imports so the server can self-heal when the
# user hasn't yet installed the requirements.
import subprocess as _subprocess
import sys as _sys
import os as _os

def _ensure_dependencies() -> None:
    """Install requirements.txt dependencies if they are not already present."""
    try:
        import fastapi  # noqa: F401 — presence check only
        return  # already installed
    except ImportError:
        pass

    _req = _os.path.join(_os.path.dirname(__file__), "requirements.txt")
    if not _os.path.exists(_req):
        print(
            f"[Arbiter] requirements.txt not found at: {_req}\n"
            "Cannot auto-install dependencies. "
            "Run: pip install fastapi uvicorn pydantic",
            flush=True,
        )
        _sys.exit(1)
    print(
        "[Arbiter] Required Python packages are missing. "
        "Installing from requirements.txt — please wait...",
        flush=True,
    )
    result = _subprocess.run(
        [_sys.executable, "-m", "pip", "install", "-r", _req],
        capture_output=False,  # stream pip output so the C# console tab shows progress
    )
    if result.returncode != 0:
        print(
            "[Arbiter] pip install failed (see output above). "
            "Run manually:  pip install -r AIEngine/PythonBridge/requirements.txt",
            flush=True,
        )
        _sys.exit(1)
    print("[Arbiter] Dependencies installed successfully.", flush=True)

_ensure_dependencies()
# ─────────────────────────────────────────────────────────────────────────────

import re
import subprocess
import tempfile
import os
from contextlib import asynccontextmanager
from pathlib import Path


def _load_env_file() -> None:
    """
    Load variables from the repository-root ``.env`` file into the process
    environment *without* overriding values that were already set externally.

    This lets ``setup_arbiter.py`` write ``ARBITER_MODEL_PATH`` once and have
    it picked up automatically on every subsequent server start.
    """
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                # Strip optional surrounding quotes from the value
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


# Load .env before importing llm_interface so ARBITER_MODEL_PATH / OLLAMA_HOST
# are in the environment when those modules evaluate their module-level constants.
_load_env_file()

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3
from llm_interface import generate_response, get_model_status, preload_model
from VoiceManager import speak
from persona_manager import (
    get_active_persona,
    set_active_persona,
    get_system_prompt,
    list_personas,
)
from model_downloader import (
    detect_vram_gb,
    recommend_model,
    list_downloaded_models,
    start_background_download,
    get_download_status,
    DEFAULT_MODEL_DIR,
)

# Resolve paths relative to this script's location
SCRIPT_DIR = Path(__file__).parent
MEMORY_ROOT = SCRIPT_DIR.parent.parent / "Memory" / "ConversationLogs"
PROJECTS_ROOT = SCRIPT_DIR.parent.parent / "Projects"

# Valid project name pattern: alphanumeric, spaces, dashes, underscores,
# and parentheses — covers names such as "Arbiter (Self)".
# Dots and path-separators are intentionally excluded to prevent traversal.
_PROJECT_NAME_RE = re.compile(r"^[\w ()\-]+$")

# Build/run/test constants
_BUILD_ERROR_MAX_CHARS = 1000
_RUN_TIMEOUT_SECONDS = 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-load the LLM in a background thread so the first chat request is fast."""
    import threading
    threading.Thread(target=preload_model, daemon=True, name="llm-preload").start()
    yield


app = FastAPI(title="Arbiter AI Bridge", version="0.1.0", lifespan=lifespan)


class UserMessage(BaseModel):
    message: str
    project: str
    use_voice: bool = False
    voice: str = "British_Female"


class PersonaRequest(BaseModel):
    persona: str


class StatusResponse(BaseModel):
    status: str
    model: str
    gpu: str
    vram_gb: float
    max_tokens: int


class DownloadRequest(BaseModel):
    repo_id: str = ""
    filename: str = ""
    auto: bool = True


class BuildRequest(BaseModel):
    project: str
    command: str = ""   # if empty, auto-detected from project files


def _validate_project_name(project_name: str) -> None:
    """Raise HTTPException if project_name contains path traversal or invalid chars."""
    if not _PROJECT_NAME_RE.match(project_name):
        raise HTTPException(status_code=400, detail="Invalid project name.")


def _resolve_project_dir(project_name: str) -> Path:
    """Return the project directory path, raising 404 if it does not exist."""
    _validate_project_name(project_name)
    project_dir = PROJECTS_ROOT / project_name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found.")
    return project_dir


def _auto_detect_command(project_dir: Path, action: str) -> str:
    """
    Infer a build / run / test command from the project directory contents.
    Returns an empty string when the project type cannot be determined.
    """
    # .NET / C#
    if list(project_dir.glob("*.csproj")) or list(project_dir.glob("*.sln")):
        return {"build": "dotnet build", "run": "dotnet run", "test": "dotnet test"}.get(action, "")
    # Node.js
    if (project_dir / "package.json").exists():
        return {"build": "npm run build", "run": "npm start", "test": "npm test"}.get(action, "")
    # Python
    if any((project_dir / f).exists() for f in ("pyproject.toml", "setup.py", "requirements.txt")):
        build_cmd = (
            "pip install -r requirements.txt"
            if (project_dir / "requirements.txt").exists()
            else "pip install -e ."
        )
        return {"build": build_cmd, "run": "python main.py", "test": "pytest"}.get(action, "")
    # Makefile
    if (project_dir / "Makefile").exists():
        return {"build": "make", "run": "make run", "test": "make test"}.get(action, "")
    return ""


def _run_command(command: str, cwd: Path, timeout: int = 120) -> dict:
    """Run a shell command in *cwd* and return stdout, stderr, exit_code."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
            "success": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s.",
            "exit_code": -1,
            "success": False,
        }


def get_db(project_name: str) -> sqlite3.Connection:
    _validate_project_name(project_name)
    db_path = MEMORY_ROOT / project_name
    db_path.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path / "session.db")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS conversation (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            role      TEXT,
            message   TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.commit()
    return conn


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def web_ui():
    """Serve the Arbiter AI ChatGPT-style web interface."""
    html_path = SCRIPT_DIR / "static" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>Arbiter AI</h1><p>Web UI not found — ensure static/index.html exists.</p>",
        status_code=200,
    )


@app.get("/projects")
def list_projects():
    """Return a sorted list of all project directories."""
    if not PROJECTS_ROOT.exists():
        return {"projects": []}
    return {
        "projects": [d.name for d in sorted(PROJECTS_ROOT.iterdir()) if d.is_dir()]
    }


@app.get("/status", response_model=StatusResponse)
def status():
    try:
        import torch
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
        vram = (
            torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            if torch.cuda.is_available()
            else 0.0
        )
    except ImportError:
        gpu = "CPU (torch not installed)"
        vram = 0.0

    # Adaptive model selection based on available VRAM
    if vram >= 20:
        model, max_tokens = "13B-fp16", 2048
    elif vram >= 12:
        model, max_tokens = "13B-8bit", 1024
    elif vram >= 6:
        model, max_tokens = "7B-8bit", 512
    elif vram >= 4:
        model, max_tokens = "7B-4bit", 256
    else:
        model, max_tokens = "CPU-fallback", 128

    return StatusResponse(
        status="ok",
        model=model,
        gpu=gpu,
        vram_gb=round(vram, 2),
        max_tokens=max_tokens,
    )


@app.get("/llm/status")
def llm_status():
    """
    Return the current LLM backend status.

    Possible ``backend`` values:
    - ``"gguf"``       — a local GGUF model is loaded via llama-cpp-python
    - ``"ollama"``     — a local Ollama instance is providing inference
    - ``"stub"``       — no model configured; responses are placeholders
    - ``"not_loaded"`` — model load not yet attempted (server just started)
    """
    return get_model_status()


# ── Persona endpoints ─────────────────────────────────────────────────────────

@app.get("/personas")
def get_personas():
    """Return the list of all available personas."""
    return {"personas": list_personas()}


@app.get("/persona/{project_name}")
def get_project_persona(project_name: str):
    """Return the active persona for *project_name*."""
    conn = get_db(project_name)
    persona = get_active_persona(conn)
    conn.close()
    return {"persona": persona}


@app.post("/persona/{project_name}")
def set_project_persona(project_name: str, req: PersonaRequest):
    """Set the active persona for *project_name*.

    The persona name must be one of the built-in personas returned by
    ``GET /personas``.  Returns ``{"persona": "<new_name>"}`` on success.
    """
    conn = get_db(project_name)
    try:
        set_active_persona(conn, req.persona)
    except ValueError as exc:
        conn.close()
        raise HTTPException(status_code=400, detail=str(exc))
    conn.close()
    return {"persona": req.persona}


# ─────────────────────────────────────────────────────────────────────────────

@app.post("/chat")
def chat(msg: UserMessage):
    conn = get_db(msg.project)
    c = conn.cursor()
    c.execute(
        "INSERT INTO conversation (role, message) VALUES (?, ?)",
        ("User", msg.message),
    )
    conn.commit()

    persona = get_active_persona(conn)
    system_prompt = get_system_prompt(persona, msg.project)
    response = generate_response(msg.message, msg.project, system_prompt=system_prompt)

    c.execute(
        "INSERT INTO conversation (role, message) VALUES (?, ?)",
        ("Arbiter", response),
    )
    conn.commit()
    conn.close()

    if msg.use_voice:
        speak(response, msg.voice)

    return {"response": response, "persona": persona}


@app.get("/history/{project_name}")
def history(project_name: str):
    conn = get_db(project_name)
    rows = conn.execute(
        "SELECT role, message, timestamp FROM conversation ORDER BY id"
    ).fetchall()
    conn.close()
    return [{"role": r, "message": m, "timestamp": t} for r, m, t in rows]


@app.get("/models")
def list_models():
    """Return recommended model for detected hardware and list of already-downloaded models."""
    vram = detect_vram_gb()
    return {
        "vram_gb": round(vram, 2),
        "recommended": recommend_model(vram),
        "downloaded": list_downloaded_models(DEFAULT_MODEL_DIR),
    }


@app.post("/models/download")
def download_model_endpoint(req: DownloadRequest):
    """
    Start an async model download in the background.

    - If ``auto`` is ``true`` (default) the best model for the current hardware
      is selected automatically.
    - Otherwise supply ``repo_id`` and ``filename`` explicitly.

    Poll ``GET /models/download/status`` for progress.
    """
    started = start_background_download(
        repo_id=req.repo_id,
        filename=req.filename,
        auto=req.auto,
        destination_dir=DEFAULT_MODEL_DIR,
    )
    if not started:
        return {"status": "already_running", "detail": get_download_status()}
    return {"status": "started"}


@app.get("/models/download/status")
def download_status_endpoint():
    """Return the current model download progress and status."""
    return get_download_status()


@app.post("/build")
def build_project(req: BuildRequest):
    """
    Run the build command for a project.

    Auto-detects the command from the project's files (.csproj → ``dotnet build``,
    ``package.json`` → ``npm run build``, etc.) unless ``command`` is provided.
    On failure, the LLM is asked to suggest a fix — included as ``"suggestion"``.
    """
    project_dir = _resolve_project_dir(req.project)
    command = req.command or _auto_detect_command(project_dir, "build")
    if not command:
        raise HTTPException(
            status_code=400,
            detail="Cannot auto-detect build command. Provide one explicitly via the 'command' field.",
        )
    result = _run_command(command, project_dir)
    if not result["success"]:
        error_text = (result["stderr"] or result["stdout"])[:_BUILD_ERROR_MAX_CHARS]
        result["suggestion"] = generate_response(
            f"The build failed with this error:\n{error_text}\nSuggest a concise fix.",
            req.project,
        )
    return result


@app.post("/run")
def run_project(req: BuildRequest):
    """
    Run the project's main entry point.

    Auto-detects the command unless ``command`` is provided.
    The process is killed after 60 seconds to prevent indefinite blocking.
    """
    project_dir = _resolve_project_dir(req.project)
    command = req.command or _auto_detect_command(project_dir, "run")
    if not command:
        raise HTTPException(
            status_code=400,
            detail="Cannot auto-detect run command. Provide one explicitly via the 'command' field.",
        )
    return _run_command(command, project_dir, timeout=_RUN_TIMEOUT_SECONDS)


@app.post("/test")
def test_project(req: BuildRequest):
    """
    Run the project's test suite.

    Auto-detects the command unless ``command`` is provided.
    On failure, the LLM is asked to suggest a fix — included as ``"suggestion"``.
    """
    project_dir = _resolve_project_dir(req.project)
    command = req.command or _auto_detect_command(project_dir, "test")
    if not command:
        raise HTTPException(
            status_code=400,
            detail="Cannot auto-detect test command. Provide one explicitly via the 'command' field.",
        )
    result = _run_command(command, project_dir)
    if not result["success"]:
        error_text = (result["stderr"] or result["stdout"])[:_BUILD_ERROR_MAX_CHARS]
        result["suggestion"] = generate_response(
            f"The test run failed with this output:\n{error_text}\nSuggest a concise fix.",
            req.project,
        )
    return result


_whisper_model = None


def _get_whisper_model():
    """Load and cache the Whisper base model."""
    global _whisper_model
    if _whisper_model is None:
        import whisper  # type: ignore
        _whisper_model = whisper.load_model("base")
    return _whisper_model


# The /stt route requires python-multipart (for UploadFile / File).
# FastAPI 0.115+ validates this dependency at route-registration time, so if the
# package is missing the entire server would crash on startup.  We wrap the
# registration in a try/except so the server still starts and returns a clear
# 503 error when /stt is called without the optional dependency installed.
try:
    @app.post("/stt")
    async def speech_to_text(file: UploadFile = File(...)):
        """
        Transcribe uploaded audio to text using OpenAI Whisper.

        Accepts any audio format supported by Whisper (wav, mp3, m4a, ogg, etc.).
        Returns ``{"text": "<transcription>"}`` on success.
        Requires ``openai-whisper`` to be installed (see requirements.txt).
        """
        try:
            import whisper  # type: ignore  # noqa: F401
        except ImportError:
            raise HTTPException(
                status_code=501,
                detail=(
                    "openai-whisper is not installed. "
                    "Install it with: pip install openai-whisper"
                ),
            )

        suffix = Path(file.filename or "audio.wav").suffix or ".wav"
        audio_bytes = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            model = _get_whisper_model()
            result = model.transcribe(tmp_path)
            text: str = result.get("text", "").strip()
        finally:
            os.unlink(tmp_path)

        return {"text": text}

except RuntimeError as _stt_reg_err:
    # python-multipart (or another required package) is missing.
    # Register a stub that explains what to install instead of crashing.
    _stt_detail = (
        f"Speech-to-text unavailable: {_stt_reg_err}. "
        "Run: pip install python-multipart"
    )
    print(f"[Bridge] /stt route registration failed — {_stt_detail}")

    @app.post("/stt")
    async def speech_to_text():  # type: ignore[misc]
        raise HTTPException(status_code=503, detail=_stt_detail)


# ═════════════════════════════════════════════════════════════════════════════
#  GUI (Monaco IDE) — serve the gui/ directory
# ═════════════════════════════════════════════════════════════════════════════

from fastapi.staticfiles import StaticFiles as _StaticFiles

_GUI_DIR = SCRIPT_DIR / "gui"
if _GUI_DIR.is_dir():
    app.mount("/gui", _StaticFiles(directory=str(_GUI_DIR), html=True), name="gui")


@app.get("/ide", response_class=HTMLResponse)
def ide_redirect():
    """Convenience redirect: GET /ide → serve the Monaco IDE."""
    return HTMLResponse(
        content='<meta http-equiv="refresh" content="0;url=/gui/index.html">',
        status_code=200,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  FILE MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════

import json as _json
import shutil as _shutil
import uuid as _uuid_mod

_WORKSPACE_ROOT = SCRIPT_DIR.parent.parent / "workspace"
_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

_ALLOWED_ROOTS = {
    "workspace": SCRIPT_DIR.parent.parent / "workspace",
    "projects":  SCRIPT_DIR.parent.parent / "Projects",
}


def _resolve_safe(rel_path: str) -> Path:
    """Return an absolute Path for *rel_path*, rejecting path traversal."""
    p = Path(rel_path)
    parts = p.parts
    root_name = parts[0].lower() if parts else ""
    root = _ALLOWED_ROOTS.get(root_name)
    if root is None:
        # Try workspace as default root
        root = _ALLOWED_ROOTS["workspace"]
        resolved = (root / rel_path).resolve()
    else:
        rest = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        resolved = (root / rest).resolve()
    if not str(resolved).startswith(str(root.resolve())):
        raise HTTPException(status_code=400, detail=f"Unsafe path: {rel_path}")
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


@app.get("/files")
def files_tree(path: str = "workspace"):
    root_name = Path(path).parts[0].lower() if Path(path).parts else "workspace"
    root = _ALLOWED_ROOTS.get(root_name, _ALLOWED_ROOTS["workspace"])
    root.mkdir(parents=True, exist_ok=True)
    return {"tree": _build_tree(root, root), "root": path}


@app.get("/files/read")
def files_read(path: str):
    fp = _resolve_safe(path)
    if not fp.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    content = fp.read_text(encoding="utf-8", errors="replace")
    return {"path": path, "content": content}


class _FileWriteReq(BaseModel):
    path: str
    content: str


@app.post("/files/write")
def files_write(req: _FileWriteReq):
    fp = _resolve_safe(req.path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(req.content, encoding="utf-8")
    return {"path": req.path, "ok": True}


class _FileDeleteReq(BaseModel):
    path: str


@app.post("/files/delete")
def files_delete(req: _FileDeleteReq):
    fp = _resolve_safe(req.path)
    if fp.is_file():
        fp.unlink()
    elif fp.is_dir():
        _shutil.rmtree(fp)
    else:
        raise HTTPException(status_code=404, detail=f"Not found: {req.path}")
    return {"path": req.path, "ok": True}


class _FileRenameReq(BaseModel):
    path: str
    new_path: str


@app.post("/files/rename")
def files_rename(req: _FileRenameReq):
    src = _resolve_safe(req.path)
    dst = _resolve_safe(req.new_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Source not found: {req.path}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"path": req.new_path, "ok": True}


@app.get("/files/scan")
def files_scan(path: str = "workspace"):
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
def files_import(req: _FileImportReq):
    src = Path(req.source)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Source not found: {req.source}")
    root_name = Path(req.dest).parts[0].lower() if Path(req.dest).parts else "workspace"
    dest_root = _ALLOWED_ROOTS.get(root_name, _ALLOWED_ROOTS["workspace"])
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / src.name
    if src.is_dir():
        _shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        _shutil.copy2(src, dest)
    return {"dest": str(dest.relative_to(SCRIPT_DIR.parent.parent)), "ok": True}


# ═════════════════════════════════════════════════════════════════════════════
#  BUILD DETECTION
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/build/detect")
def build_detect(path: str = "workspace"):
    root_name = Path(path).parts[0].lower() if Path(path).parts else "workspace"
    root = _ALLOWED_ROOTS.get(root_name, _ALLOWED_ROOTS["workspace"])
    return {
        "build": _auto_detect_command(root, "build") or None,
        "run":   _auto_detect_command(root, "run")   or None,
        "test":  _auto_detect_command(root, "test")  or None,
    }


# ═════════════════════════════════════════════════════════════════════════════
#  ASSISTANT / AI ENDPOINTS  (IDE chat panel, code actions, agentic)
# ═════════════════════════════════════════════════════════════════════════════

class _AssistantMsg(BaseModel):
    prompt: str
    project: str = "default"
    backend: str = ""
    context: str = ""   # current open-file content injected by the IDE
    mode: str = "chat"  # "chat" | "agentic"


@app.post("/assistant/chat")
def assistant_chat(msg: _AssistantMsg):
    """Primary chat endpoint used by the Monaco IDE chat panel."""
    system = get_system_prompt(get_active_persona(get_db(msg.project)), msg.project)
    if msg.context:
        system += f"\n\nCurrently open file:\n```\n{msg.context[:3000]}\n```"
    response = generate_response(msg.prompt, msg.project, system_prompt=system)
    return {"response": response}


@app.post("/assistant/chat/agentic")
def assistant_chat_agentic(msg: _AssistantMsg):
    """Agentic chat: plan → propose file edits → apply → summarise."""
    try:
        import sys as _sys2
        _engine_path = str(SCRIPT_DIR.parent / "ArbiterEngine")
        if _engine_path not in _sys2.path:
            _sys2.path.insert(0, _engine_path)
        from core.agentic_agent import AgenticChatEngine  # type: ignore
        from llm.factory import create_llm as _create_llm  # type: ignore
        from core.config_loader import ConfigLoader as _CL  # type: ignore
        _cfg = _CL(SCRIPT_DIR.parent / "ArbiterEngine" / "configs")
        _cfg.load()
        _llm = _create_llm(_cfg.get("agent.default_llm_backend", "ollama"), _cfg)
        _engine = AgenticChatEngine(llm=_llm, base_dir=SCRIPT_DIR.parent.parent,
                                    project_path=msg.project)
        result = _engine.run(msg.prompt)
        return {
            "response": result.reply,
            "todos": [{"id": t.id, "text": t.text, "done": t.done} for t in result.todos],
            "file_changes": [
                {"path": c.path, "additions": c.additions,
                 "deletions": c.deletions, "diff": c.diff}
                for c in result.file_changes
            ],
        }
    except Exception as _exc:
        response = generate_response(msg.prompt, msg.project)
        return {"response": response, "todos": [], "file_changes": [],
                "_fallback": str(_exc)}


class _AiCompleteReq(BaseModel):
    code: str
    language: str = ""
    cursor_offset: int = 0
    project: str = "default"


@app.post("/ai/complete")
def ai_complete(req: _AiCompleteReq):
    prompt = (
        f"Complete the following {req.language} code. "
        "Return ONLY the completion text — no explanation, no markdown fences:\n"
        f"{req.code}"
    )
    completion = generate_response(prompt, req.project)
    return {"completion": completion}


class _AiActionReq(BaseModel):
    action: str   # "explain" | "fix" | "refactor" | "docstring" | "tests" | "simplify"
    code: str
    language: str = ""
    project: str = "default"
    extra: str = ""


_AI_ACTION_PROMPTS = {
    "explain":   "Explain what this code does in plain English:",
    "fix":       "Find and fix all bugs in this code. Return only the corrected code:",
    "refactor":  "Refactor this code for clarity and performance. Return only the improved code:",
    "docstring": "Add docstrings/comments to this code. Return the fully commented code:",
    "tests":     "Write unit tests for this code:",
    "simplify":  "Simplify this code. Return only the simplified version:",
}


@app.post("/ai/action")
def ai_action(req: _AiActionReq):
    instruction = _AI_ACTION_PROMPTS.get(req.action, f"Apply '{req.action}' to this code:")
    prompt = f"{instruction}\n\n```{req.language}\n{req.code}\n```\n{req.extra}"
    result = generate_response(prompt, req.project)
    return {"result": result}


class _AiProposeReq(BaseModel):
    task: str
    files: list = []
    project: str = "default"


@app.post("/ai/propose")
def ai_propose(req: _AiProposeReq):
    files_ctx = "\n".join(
        f"File: {f.get('path','')}\n```\n{str(f.get('content',''))[:500]}\n```"
        for f in req.files[:5]
    )
    prompt = f"Task: {req.task}\n\nRelevant files:\n{files_ctx}\n\nPropose specific file changes."
    return {"proposal": generate_response(prompt, req.project)}


@app.get("/ai/persona/active")
def ai_persona_active():
    return {"name": "Arbiter", "description": "AI assistant for Arbiter IDE"}


@app.get("/ai/backends")
def ai_backends():
    return {
        "backends": [
            {"id": "ollama",    "name": "Ollama",    "status": "available"},
            {"id": "api",       "name": "OpenAI API","status": "available"},
            {"id": "anthropic", "name": "Anthropic", "status": "available"},
            {"id": "gemini",    "name": "Gemini",    "status": "available"},
            {"id": "lmstudio",  "name": "LM Studio", "status": "available"},
            {"id": "llamacpp",  "name": "llama.cpp", "status": "available"},
        ]
    }


@app.post("/ai/backends/switch")
@app.post("/ai/backends/configure")
@app.post("/ai/backends/test")
def ai_backends_modify(req: dict = {}):
    return {"status": "ok"}


@app.get("/ai/timeline")
def ai_timeline(limit: int = 100):
    return {"events": []}


@app.post("/ai/timeline/clear")
def ai_timeline_clear():
    return {"status": "ok"}


# ═════════════════════════════════════════════════════════════════════════════
#  WEBSOCKET STREAMING  (run output, terminal, PTY)
# ═════════════════════════════════════════════════════════════════════════════

from fastapi import WebSocket, WebSocketDisconnect
import asyncio as _asyncio


@app.websocket("/ws/run")
async def ws_run(ws: WebSocket):
    """Stream build/run command output to the IDE terminal panel."""
    await ws.accept()
    try:
        data = await ws.receive_json()
        cmd = data.get("command", "echo hello")
        cwd_rel = data.get("cwd", "workspace")
        cwd = (_ALLOWED_ROOTS.get(Path(cwd_rel).parts[0].lower() if Path(cwd_rel).parts else "workspace",
                                  _ALLOWED_ROOTS["workspace"])).resolve()
        proc = await _asyncio.create_subprocess_shell(
            cmd, cwd=str(cwd),
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for line in proc.stdout:
            await ws.send_text(line.decode("utf-8", errors="replace"))
        await proc.wait()
        await ws.send_json({"type": "exit", "code": proc.returncode})
    except (WebSocketDisconnect, Exception):
        pass


@app.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket):
    """Simple line-by-line WebSocket terminal."""
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_text()
            proc = await _asyncio.create_subprocess_shell(
                msg,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            await ws.send_text(out.decode("utf-8", errors="replace") or "(no output)")
    except (WebSocketDisconnect, Exception):
        pass


@app.websocket("/ws/pty")
async def ws_pty(ws: WebSocket):
    """PTY session — reuses the line-based terminal implementation."""
    await ws_terminal(ws)


# ═════════════════════════════════════════════════════════════════════════════
#  NATIVE TOOL-CALL QUEUE  (WPF ↔ Monaco IDE bridge)
# ═════════════════════════════════════════════════════════════════════════════
#
#  The Monaco IDE JS posts to POST /api/ide/command when it needs the WPF host
#  to perform a native Windows action (file picker, notification, etc.).
#  The WPF host polls GET /api/ide/pending, executes the action, then posts the
#  result to POST /api/ide/complete.
# ─────────────────────────────────────────────────────────────────────────────

import threading as _threading

_ide_queue: list = []
_ide_queue_lock = _threading.Lock()
_ide_results: dict = {}


@app.get("/api/ide/pending")
def ide_pending():
    """Return and clear all pending native tool calls for the WPF host."""
    with _ide_queue_lock:
        items = list(_ide_queue)
        _ide_queue.clear()
    return {"calls": items}


class _IdeCommandReq(BaseModel):
    type: str        # "open_file_picker" | "show_notification" | "open_external" | ...
    payload: dict = {}


@app.post("/api/ide/command")
def ide_command(req: _IdeCommandReq):
    """Queue a native command for the WPF host to execute."""
    call_id = str(_uuid_mod.uuid4())[:8]
    with _ide_queue_lock:
        _ide_queue.append({"id": call_id, "type": req.type, "payload": req.payload})
    return {"status": "queued", "call_id": call_id}


class _IdeResultReq(BaseModel):
    call_id: str
    result: dict = {}


@app.post("/api/ide/complete")
def ide_complete(req: _IdeResultReq):
    """Receive the result of a native tool call from the WPF host."""
    _ide_results[req.call_id] = req.result
    return {"status": "ok", "call_id": req.call_id}


@app.get("/api/ide/result/{call_id}")
def ide_result(call_id: str):
    """Poll for the result of a specific native call."""
    result = _ide_results.pop(call_id, None)
    if result is None:
        return {"status": "pending"}
    return {"status": "ready", "result": result}


# ═════════════════════════════════════════════════════════════════════════════
#  GIT ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

class _GitCloneReq(BaseModel):
    url: str
    dest: str = "workspace"
    branch: str = ""


@app.post("/git/clone")
def git_clone(req: _GitCloneReq):
    dest_root = _ALLOWED_ROOTS.get(
        Path(req.dest).parts[0].lower() if Path(req.dest).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    dest_root.mkdir(parents=True, exist_ok=True)
    branch_flag = f"--branch {req.branch}" if req.branch else ""
    return _run_command(f'git clone {branch_flag} "{req.url}"', dest_root)


@app.get("/git/status")
def git_status_ep(path: str = "workspace"):
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    r = _run_command("git status --short", root, timeout=10)
    lines = (r.get("stdout") or "").splitlines()
    staged    = [l[3:] for l in lines if l[:2] in ("A ", "M ", "D ")]
    unstaged  = [l[3:] for l in lines if l[:1] == " " and l[1:2] in ("M", "D")]
    untracked = [l[3:] for l in lines if l[:2] == "??"]
    branch_r  = _run_command("git branch --show-current", root, timeout=5)
    branch    = (branch_r.get("stdout") or "").strip() or "unknown"
    return {"branch": branch, "staged": staged, "unstaged": unstaged, "untracked": untracked}


class _GitStageReq(BaseModel):
    files: list
    project: str = "workspace"


@app.post("/git/stage")
def git_stage(req: _GitStageReq):
    root = _ALLOWED_ROOTS.get(
        Path(req.project).parts[0].lower() if Path(req.project).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    files_str = " ".join(f'"{f}"' for f in req.files[:50])
    return _run_command(f"git add {files_str}", root, timeout=15)


class _GitCommitReq(BaseModel):
    message: str
    project: str = "workspace"


@app.post("/git/commit")
def git_commit_ep(req: _GitCommitReq):
    root = _ALLOWED_ROOTS.get(
        Path(req.project).parts[0].lower() if Path(req.project).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    return _run_command(f'git commit -m "{req.message}"', root, timeout=15)


@app.get("/git/log")
def git_log(path: str = "workspace", limit: int = 20):
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    r = _run_command(f"git log --oneline -n {min(limit, 100)}", root, timeout=10)
    commits = []
    for line in (r.get("stdout") or "").splitlines():
        if " " in line:
            sha, _, msg = line.partition(" ")
            commits.append({"sha": sha, "message": msg})
    return {"commits": commits}


@app.get("/git/diff")
def git_diff(path: str = "workspace", file: str = ""):
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    cmd = f'git diff -- "{file}"' if file else "git diff"
    r = _run_command(cmd, root, timeout=10)
    return {"diff": r.get("stdout", "")}


# ═════════════════════════════════════════════════════════════════════════════
#  PROJECT INIT / PROFILE
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/project/init/detect")
def project_init_detect(path: str = "workspace"):
    root = _ALLOWED_ROOTS.get(
        Path(path).parts[0].lower() if Path(path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    return {
        "build": _auto_detect_command(root, "build"),
        "run":   _auto_detect_command(root, "run"),
        "test":  _auto_detect_command(root, "test"),
        "path": path,
    }


@app.get("/project/init/scan")
def project_init_scan(path: str = "workspace"):
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
def project_init(req: dict = {}):
    return {"status": "ok"}


@app.get("/project/health")
def project_health(path: str = "workspace"):
    return {"status": "ok", "path": path}


# ═════════════════════════════════════════════════════════════════════════════
#  DIFF / PATCH / FORMAT / LINT
# ═════════════════════════════════════════════════════════════════════════════

class _DiffReq(BaseModel):
    original: str
    modified: str


@app.post("/diff")
def compute_diff(req: _DiffReq):
    import difflib as _dl
    diff = list(_dl.unified_diff(
        req.original.splitlines(keepends=True),
        req.modified.splitlines(keepends=True),
        fromfile="original", tofile="modified",
    ))
    return {"diff": "".join(diff)}


class _PatchReq(BaseModel):
    patch: str
    path: str = "workspace"


@app.post("/patch")
def apply_patch(req: _PatchReq):
    root = _ALLOWED_ROOTS.get(
        Path(req.path).parts[0].lower() if Path(req.path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tf:
        tf.write(req.patch)
        pf = tf.name
    result = _run_command(f'patch -p1 --input="{pf}"', root, timeout=30)
    Path(pf).unlink(missing_ok=True)
    return result


class _FormatReq(BaseModel):
    code: str
    language: str = "python"


@app.post("/format")
def format_code(req: _FormatReq):
    prompt = (
        f"Format this {req.language} code properly. "
        "Return ONLY the formatted code, no explanation, no markdown fences:\n"
        f"{req.code}"
    )
    result = generate_response(prompt, "default")
    result = re.sub(r"^```\w*\n?", "", result).rstrip("` \n")
    return {"formatted": result}


class _LintReq(BaseModel):
    code: str
    language: str = "python"
    path: str = ""


@app.post("/lint")
def lint_code(req: _LintReq):
    prompt = (
        f"Find any bugs, errors, or style issues in this {req.language} code. "
        "List them concisely. If there are none, say 'No issues found.':\n"
        f"```{req.language}\n{req.code}\n```"
    )
    return {"issues": generate_response(prompt, "default")}


# ═════════════════════════════════════════════════════════════════════════════
#  SCAFFOLD / TEMPLATES
# ═════════════════════════════════════════════════════════════════════════════

class _ScaffoldReq(BaseModel):
    type: str = "module"
    name: str
    description: str = ""
    project: str = "workspace"


@app.post("/scaffold/module")
@app.post("/scaffold/plugin")
@app.post("/scaffold/tests")
def scaffold(req: _ScaffoldReq):
    prompt = (
        f"Generate a complete {req.type} called '{req.name}'. "
        f"Description: {req.description}. "
        "Return only well-structured code with comments."
    )
    return {"code": generate_response(prompt, req.project), "name": req.name}


@app.get("/templates")
def list_templates():
    return {"templates": [
        {"id": "python-module",   "name": "Python Module",   "language": "python"},
        {"id": "fastapi-app",     "name": "FastAPI App",     "language": "python"},
        {"id": "react-component", "name": "React Component", "language": "javascript"},
        {"id": "dotnet-app",      "name": ".NET Console App","language": "csharp"},
        {"id": "go-service",      "name": "Go Service",      "language": "go"},
    ]}


class _TemplateApplyReq(BaseModel):
    template_id: str
    name: str
    dest: str = "workspace"


@app.post("/templates/apply")
def apply_template(req: _TemplateApplyReq):
    prompt = (
        f"Generate a complete {req.template_id} project called '{req.name}'. "
        "Return a JSON list of file objects: [{\"path\":\"...\",\"content\":\"...\"}]"
    )
    return {"result": generate_response(prompt, "default"), "template": req.template_id}


# ═════════════════════════════════════════════════════════════════════════════
#  REFACTOR
# ═════════════════════════════════════════════════════════════════════════════

class _RefactorReq(BaseModel):
    code: str
    find: str = ""
    replace: str = ""
    language: str = "python"
    project: str = "default"


@app.post("/refactor/find-replace")
def refactor_find_replace(req: _RefactorReq):
    result = req.code.replace(req.find, req.replace) if req.find else req.code
    return {"result": result}


@app.post("/refactor/rename")
def refactor_rename(req: _RefactorReq):
    prompt = (
        f"Rename '{req.find}' to '{req.replace}' throughout this {req.language} code. "
        "Return only the updated code:\n"
        f"```{req.language}\n{req.code}\n```"
    )
    return {"result": generate_response(prompt, req.project)}


# ═════════════════════════════════════════════════════════════════════════════
#  BRAINSTORM / DOC GENERATION
# ═════════════════════════════════════════════════════════════════════════════

class _BrainstormReq(BaseModel):
    topic: str
    context: str = ""
    project: str = "default"


@app.post("/brainstorm/session")
def brainstorm(req: _BrainstormReq):
    prompt = (
        f"Brainstorm ideas for: {req.topic}\n"
        f"Context: {req.context}\n"
        "Provide a well-structured list of creative ideas."
    )
    return {"ideas": generate_response(prompt, req.project), "topic": req.topic}


@app.get("/brainstorm/sessions")
def brainstorm_sessions():
    return {"sessions": []}


class _DocgenReq(BaseModel):
    code: str
    language: str = "python"
    project: str = "default"


@app.post("/docgen/generate")
def docgen_generate(req: _DocgenReq):
    prompt = (
        f"Generate comprehensive documentation for this {req.language} code. "
        "Include description, parameters, return values, and examples:\n"
        f"```{req.language}\n{req.code}\n```"
    )
    return {"docs": generate_response(prompt, req.project)}


@app.get("/docgen/history")
def docgen_history(limit: int = 20):
    return {"items": []}


# ═════════════════════════════════════════════════════════════════════════════
#  SNIPPETS
# ═════════════════════════════════════════════════════════════════════════════

_SNIPPETS_FILE = SCRIPT_DIR.parent.parent / "Memory" / "snippets.json"


def _load_snippets() -> list:
    if _SNIPPETS_FILE.is_file():
        try:
            return _json.loads(_SNIPPETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_snippets(data: list) -> None:
    _SNIPPETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SNIPPETS_FILE.write_text(_json.dumps(data, indent=2), encoding="utf-8")


@app.get("/snippets")
def list_snippets():
    return {"snippets": _load_snippets()}


class _SnippetReq(BaseModel):
    title: str
    code: str
    language: str = ""
    tags: list = []


@app.post("/snippet")
def save_snippet(req: _SnippetReq):
    snips = _load_snippets()
    snip = {
        "id": str(_uuid_mod.uuid4())[:8], "title": req.title,
        "code": req.code, "language": req.language, "tags": req.tags,
    }
    snips.append(snip)
    _save_snippets(snips)
    return snip


class _SnippetRunReq(BaseModel):
    code: str
    language: str = "python"


@app.post("/snippet/run")
def run_snippet(req: _SnippetRunReq):
    import sys as _sys3
    if req.language != "python":
        return {"output": f"[Run not supported for {req.language}]"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
        tf.write(req.code)
        tmp = tf.name
    result = _run_command(f'"{_sys3.executable}" "{tmp}"', SCRIPT_DIR, timeout=10)
    Path(tmp).unlink(missing_ok=True)
    return {"output": result.get("stdout", "") + result.get("stderr", "")}


# ═════════════════════════════════════════════════════════════════════════════
#  NOTES / PROFILE / TOOLCHAIN / STATS
# ═════════════════════════════════════════════════════════════════════════════

_NOTES_FILE = SCRIPT_DIR.parent.parent / "Memory" / "notes.json"


@app.get("/notes")
def get_notes(project: str = "default"):
    if _NOTES_FILE.is_file():
        try:
            data = _json.loads(_NOTES_FILE.read_text())
            return {"notes": data.get(project, "")}
        except Exception:
            pass
    return {"notes": ""}


class _NotesReq(BaseModel):
    project: str = "default"
    notes: str


@app.post("/notes")
def save_notes(req: _NotesReq):
    data: dict = {}
    if _NOTES_FILE.is_file():
        try:
            data = _json.loads(_NOTES_FILE.read_text())
        except Exception:
            pass
    data[req.project] = req.notes
    _NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _NOTES_FILE.write_text(_json.dumps(data, indent=2))
    return {"status": "ok"}


@app.get("/profile")
def get_profile():
    return {"name": "Arbiter User", "theme": "dark", "font_size": 14}


@app.get("/config/active")
@app.get("/config/profile")
def get_config():
    return {"profile": "default", "theme": "vs-dark", "font_size": 14}


@app.get("/config/profiles")
def list_config_profiles():
    return {"profiles": ["default"]}


@app.post("/config/profile")
def set_config_profile(req: dict = {}):
    return {"status": "ok"}


@app.get("/toolchain")
def get_toolchain():
    import shutil as _sh
    tools = {}
    for t in ("python", "node", "npm", "git", "dotnet", "cargo", "go", "docker"):
        tools[t] = {"available": bool(_sh.which(t)), "path": _sh.which(t) or ""}
    return {"tools": tools}


@app.get("/stats")
def get_stats():
    return {
        "projects": len(list(PROJECTS_ROOT.iterdir())) if PROJECTS_ROOT.exists() else 0,
        "engine": "arbiter-bridge",
    }


@app.get("/metrics")
def get_metrics():
    return {"metrics": {"requests": 0, "errors": 0}}


# ═════════════════════════════════════════════════════════════════════════════
#  SEARCH IN FILES
# ═════════════════════════════════════════════════════════════════════════════

class _SearchReq(BaseModel):
    query: str
    path: str = "workspace"
    case_sensitive: bool = False


@app.post("/search")
def search_in_files(req: _SearchReq):
    root = _ALLOWED_ROOTS.get(
        Path(req.path).parts[0].lower() if Path(req.path).parts else "workspace",
        _ALLOWED_ROOTS["workspace"],
    )
    flags = 0 if req.case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(req.query), flags)
    results = []
    for f in root.rglob("*"):
        if f.is_file() and not f.name.startswith("."):
            try:
                for i, line in enumerate(
                    f.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                ):
                    if pattern.search(line):
                        results.append({
                            "file": str(f.relative_to(root)),
                            "line": i, "text": line.strip()[:200],
                        })
                        if len(results) >= 200:
                            return {"results": results}
            except Exception:
                pass
    return {"results": results}


# ═════════════════════════════════════════════════════════════════════════════
#  STUB ENDPOINTS  (advanced features — modules loaded via setup_modules.py)
# ═════════════════════════════════════════════════════════════════════════════

from fastapi import Request as _Request


def _stub_handler(feature: str):
    async def _h(_req: _Request):
        return {
            "status": "not_implemented",
            "feature": feature,
            "detail": f"{feature} requires additional modules. Run AIEngine/ArbiterEngine/setup_modules.py.",
        }
    return _h


for _stub_path, _stub_tag in [
    ("/agents", "multi-agent"), ("/agents/spawn", "multi-agent"),
    ("/ci/run", "ci"), ("/ci/runs", "ci"),
    ("/deploy/run", "deploy"), ("/deploy/configs", "deploy"),
    ("/deploy/config", "deploy"), ("/deploy/history", "deploy"),
    ("/docker/containers", "docker"), ("/docker/build", "docker"), ("/docker/run", "docker"),
    ("/db/connect", "database"), ("/db/connections", "database"), ("/db/query", "database"),
    ("/vault/keys", "vault"), ("/vault/set", "vault"), ("/vault/export", "vault"),
    ("/webhooks", "webhooks"), ("/webhook/register", "webhooks"),
    ("/webhook/deliveries", "webhooks"),
    ("/cron/jobs", "cron"), ("/cron/job", "cron"), ("/cron/history", "cron"),
    ("/events/subscribe", "events"), ("/events/subscriptions", "events"),
    ("/events/publish", "events"), ("/events/history", "events"),
    ("/queue/tasks", "task-queue"), ("/queue/task", "task-queue"),
    ("/queue/stats", "task-queue"),
    ("/flags", "feature-flags"), ("/flags/flag", "feature-flags"),
    ("/notifications", "notifications"), ("/notifications/mark-read", "notifications"),
    ("/notifications/clear", "notifications"), ("/notify", "notifications"),
    ("/audit/log", "audit"), ("/audit/stats", "audit"), ("/audit/log/clear", "audit"),
    ("/ratelimit/rules", "ratelimit"), ("/ratelimit/rule", "ratelimit"),
    ("/ratelimit/status", "ratelimit"),
    ("/apiclient/collections", "api-client"), ("/apiclient/collection", "api-client"),
    ("/apiclient/send", "api-client"),
    ("/deps/analyze", "deps"), ("/deps/reports", "deps"),
    ("/roadmap/next", "roadmap"),
    ("/testrunner/run", "testrunner"), ("/testrunner/reports", "testrunner"),
    ("/knowledge/fetch", "knowledge"), ("/knowledge/remove", "knowledge"),
    ("/rules", "rules"), ("/tasks", "tasks"),
    ("/env/files", "env"), ("/env/import", "env"), ("/env/var", "env"),
    ("/plugins", "plugins"), ("/plugins/install", "plugins"),
    ("/plugins/reload", "plugins"), ("/plugins/generate", "plugins"),
    ("/terminal/session", "terminal"), ("/terminal/sessions", "terminal"),
]:
    app.add_api_route(
        _stub_path, _stub_handler(_stub_tag),
        methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
