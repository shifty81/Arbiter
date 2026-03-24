"""Novaforge — Remote Web Interface API Server.

NF2-1  FastAPI server: /ai/query, /ai/stream (SSE), /ai/actions,
       /ai/execute, /ai/theme, /ws/ai
NF2-2  Frontend served at GET / — self-contained dark-mode HTML/JS client
NF2-3  AI action buttons execute via /ai/execute (same pipeline as local)
NF2-4  /ai/theme → current palette JSON; frontend applies theme live
NF2-5  Token-based auth: Bearer token required when NOVAFORGE_API_KEY is set
NF2-6  Configurable bind host (default 0.0.0.0) for LAN access
NF2-7  Resource monitoring via psutil; throttle when RAM/CPU above threshold
NF2-8  Crash-protection supervisor thread; rotating log for this service

Run standalone:
    python -m src.remote_api                   # defaults: 0.0.0.0:8010
    NOVAFORGE_PORT=8010 NOVAFORGE_API_KEY=secret python -m src.remote_api
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

# ── Logging setup (NF2-8) ─────────────────────────────────────────────────────
_NF_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR  = _NF_ROOT / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _setup_logging() -> None:
    root = logging.getLogger("novaforge")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(
        _LOG_DIR / "novaforge_remote.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(_log_formatter)
    root.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(_log_formatter)
    root.addHandler(ch)


_setup_logging()
logger = logging.getLogger("novaforge.remote_api")

# ── Configuration from environment ───────────────────────────────────────────
_BIND_HOST  = os.environ.get("NOVAFORGE_HOST",    "0.0.0.0")
_BIND_PORT  = int(os.environ.get("NOVAFORGE_PORT", "8010"))
_API_KEY    = os.environ.get("NOVAFORGE_API_KEY", "")   # empty = no auth
_ARBITER_URL = os.environ.get("ARBITER_ENGINE_URL", "http://127.0.0.1:8001")

# Resource monitoring thresholds (NF2-7)
_CPU_THROTTLE_PCT  = float(os.environ.get("NOVAFORGE_CPU_THROTTLE", "90"))
_RAM_THROTTLE_PCT  = float(os.environ.get("NOVAFORGE_RAM_THROTTLE", "90"))

# ── Theme palette (dark mode default, NF2-4) ─────────────────────────────────
_THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "bg":          "#202123",
        "panel":       "#2A2B2F",
        "text":        "#ECECEC",
        "ai_text":     "#00FFAB",
        "accent":      "#10A37F",
        "border":      "#444654",
        "user_bubble": "#343541",
        "ai_bubble":   "#444654",
    },
    "day": {
        "bg":          "#F5F5F5",
        "panel":       "#E6E6E6",
        "text":        "#1A1A2E",
        "ai_text":     "#007864",
        "accent":      "#007864",
        "border":      "#CCCCCC",
        "user_bubble": "#FFFFFF",
        "ai_bubble":   "#EAF7F3",
    },
}
_active_theme: str = "dark"
_theme_lock = asyncio.Lock()

# ── Import AI layer ───────────────────────────────────────────────────────────
try:
    from AI.arbiter_ai import ArbiterAIManager, AIAction, WorkspaceContext
    _workspace = WorkspaceContext(str(_NF_ROOT))
    _ai = ArbiterAIManager(
        arbiter_url=_ARBITER_URL,
        project_name="Novaforge",
        workspace_context=_workspace,
    )
    _ai_available = True
except Exception as _exc:
    logger.warning("ArbiterAI unavailable: %s — responses will be stubbed", _exc)
    _ai_available = False
    _ai = None  # type: ignore[assignment]

# ── FastAPI ───────────────────────────────────────────────────────────────────
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Novaforge Remote AI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth (NF2-5) ──────────────────────────────────────────────────────────────

def _check_auth(request: Request) -> None:
    if not _API_KEY:
        return  # auth disabled
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if token != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing Bearer token")


def _auth_dep(request: Request) -> None:
    return _check_auth(request)


# ── Resource monitoring (NF2-7) ───────────────────────────────────────────────

def _get_resources() -> Dict[str, Any]:
    try:
        import psutil  # type: ignore[import]
        return {
            "cpu_percent":    psutil.cpu_percent(interval=0.1),
            "ram_percent":    psutil.virtual_memory().percent,
            "ram_used_mb":    round(psutil.virtual_memory().used / 1_048_576, 1),
            "ram_total_mb":   round(psutil.virtual_memory().total / 1_048_576, 1),
            "available":      True,
        }
    except ImportError:
        return {"available": False, "note": "psutil not installed"}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _is_throttled() -> bool:
    res = _get_resources()
    if not res.get("available"):
        return False
    return (
        res.get("cpu_percent", 0) >= _CPU_THROTTLE_PCT
        or res.get("ram_percent", 0) >= _RAM_THROTTLE_PCT
    )


# ── Pydantic request models ───────────────────────────────────────────────────

class _QueryReq(BaseModel):
    message: str
    project: str = "Novaforge"
    context: Dict[str, Any] = {}


class _ExecuteReq(BaseModel):
    action_index: int = 0
    action_type: str = ""
    action_payload: Dict[str, Any] = {}
    project: str = "Novaforge"


class _ThemeReq(BaseModel):
    theme: str = "dark"   # "dark" | "day" | "custom"
    custom: Dict[str, str] = {}


# ── WebSocket connection manager ──────────────────────────────────────────────

class _WSManager:
    def __init__(self) -> None:
        self._active: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._active.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._active = [c for c in self._active if c is not ws]

    async def broadcast(self, message: Dict[str, Any]) -> None:
        text = json.dumps(message)
        async with self._lock:
            dead = []
            for ws in self._active:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            self._active = [c for c in self._active if c not in dead]


_ws_manager = _WSManager()

# ── Cached last AI actions (shared between /ai/stream and /ai/execute) ─────────
_last_actions: List[Dict[str, Any]] = []
_actions_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root() -> HTMLResponse:
    """Serve the self-contained browser client (NF2-2)."""
    html = _build_frontend()
    return HTMLResponse(html)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status":       "ok",
        "ai_available": _ai_available,
        "theme":        _active_theme,
        "resources":    _get_resources(),
        "ts":           datetime.datetime.utcnow().isoformat(),
    }


@app.get("/ai/theme")
async def get_theme() -> Dict[str, Any]:
    """Return the current colour palette (NF2-4)."""
    palette = _THEMES.get(_active_theme, _THEMES["dark"])
    return {"theme": _active_theme, "palette": palette}


@app.post("/ai/theme")
async def set_theme(req: _ThemeReq, _: None = Depends(_auth_dep)) -> Dict[str, Any]:
    """Switch theme (NF2-4).  Admin-only when API key is set."""
    global _active_theme
    async with _theme_lock:
        if req.theme == "custom" and req.custom:
            _THEMES["custom"] = req.custom
            _active_theme = "custom"
        elif req.theme in _THEMES:
            _active_theme = req.theme
        else:
            raise HTTPException(status_code=400, detail=f"Unknown theme '{req.theme}'")
        active = _active_theme
        palette = dict(_THEMES[active])
    # Broadcast theme change to all WebSocket clients
    asyncio.create_task(_ws_manager.broadcast({"type": "theme", "theme": active, "palette": palette}))
    return {"theme": active, "palette": palette}


@app.post("/ai/query")
async def ai_query(req: _QueryReq, _: None = Depends(_auth_dep)) -> Dict[str, Any]:
    """Single-shot AI query — returns the full response text (NF2-1)."""
    if _is_throttled():
        raise HTTPException(status_code=503, detail="Server under resource pressure; retry later.")
    if not _ai_available or _ai is None:
        return {"response": f"[AI stub] You asked: {req.message}", "actions": []}

    try:
        full_text: List[str] = []
        async for token in _ai.stream(req.message, context=req.context):
            full_text.append(token)
        response = "".join(full_text)
        actions = await _ai.generate_actions(response)
        actions_dicts = [{"type": a.type, "title": a.title, "description": a.description, "payload": a.payload} for a in actions]
        with _actions_lock:
            global _last_actions
            _last_actions = actions_dicts
        return {"response": response, "actions": actions_dicts}
    except Exception as exc:
        logger.error("ai_query error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/ai/stream")
async def ai_stream(
    message: str,
    project: str = "Novaforge",
    request: Request = None,  # type: ignore[assignment]
    _: None = Depends(_auth_dep),
) -> StreamingResponse:
    """SSE token stream for a chat message (NF2-1).

    Client receives ``data: <token>\\n\\n`` events followed by a final
    ``data: [DONE]\\n\\n`` event and an ``event: actions`` event carrying the
    generated AIAction list as JSON.
    """
    if _is_throttled():
        raise HTTPException(status_code=503, detail="Server under resource pressure.")

    async def _event_stream() -> AsyncIterator[str]:
        full_text: List[str] = []
        try:
            if not _ai_available or _ai is None:
                # Stub stream
                stub = f"[AI stub] You asked: {message}"
                for char in stub:
                    yield f"data: {char}\n\n"
                    await asyncio.sleep(0.02)
            else:
                async for token in _ai.stream(message):
                    full_text.append(token)
                    yield f"data: {json.dumps({'token': token})}\n\n"
        except asyncio.CancelledError:
            return

        yield "data: [DONE]\n\n"

        # Generate and emit actions after stream completes
        if _ai_available and _ai is not None:
            try:
                actions = await _ai.generate_actions("".join(full_text))
                actions_dicts = [
                    {"type": a.type, "title": a.title, "description": a.description, "payload": a.payload}
                    for a in actions
                ]
                with _actions_lock:
                    global _last_actions
                    _last_actions = actions_dicts
                yield f"event: actions\ndata: {json.dumps(actions_dicts)}\n\n"
            except Exception as exc:
                logger.warning("Action generation failed: %s", exc)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/ai/actions")
async def ai_actions(_: None = Depends(_auth_dep)) -> Dict[str, Any]:
    """Return the most recently generated AI action list (NF2-3)."""
    with _actions_lock:
        actions = list(_last_actions)
    return {"actions": actions, "count": len(actions)}


@app.post("/ai/execute")
async def ai_execute(req: _ExecuteReq, _: None = Depends(_auth_dep)) -> Dict[str, Any]:
    """Execute an AI action by index from the last action list (NF2-3).

    Alternatively, pass ``action_type`` + ``action_payload`` to execute a
    custom action inline without selecting from the cached list.
    """
    if not _ai_available or _ai is None:
        return {"status": "stub", "detail": "AI not available; action not executed"}

    with _actions_lock:
        actions = list(_last_actions)

    if req.action_type:
        # Inline execution (NF2-3)
        from AI.arbiter_ai import AIAction
        action = AIAction(
            type=req.action_type,
            title=req.action_type,
            description="",
            payload=req.action_payload,
        )
    elif 0 <= req.action_index < len(actions):
        raw = actions[req.action_index]
        from AI.arbiter_ai import AIAction
        action = AIAction(
            type=raw["type"],
            title=raw.get("title", ""),
            description=raw.get("description", ""),
            payload=raw.get("payload", {}),
        )
    else:
        raise HTTPException(
            status_code=404,
            detail=f"No action at index {req.action_index}. Available: {len(actions)}"
        )

    try:
        result = await _ai.execute_action(action)
        return {"status": "executed", "action": action.type, "result": result}
    except Exception as exc:
        logger.error("ai_execute error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/resources")
async def resources() -> Dict[str, Any]:
    """Return current CPU/RAM usage (NF2-7)."""
    return _get_resources()


@app.websocket("/ws/ai")
async def ws_ai(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time bi-directional AI chat (NF2-1).

    Client sends: ``{"message": "..."}``
    Server sends back streamed tokens + a final actions payload.
    """
    # Auth via query param when API key is set (NF2-5)
    if _API_KEY:
        token = websocket.query_params.get("token", "")
        if token != _API_KEY:
            await websocket.close(code=4001, reason="Unauthorized")
            return

    await _ws_manager.connect(websocket)
    logger.info("WebSocket client connected")
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=120)
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = {"message": raw}

            message = msg.get("message", "").strip()
            if not message:
                continue

            if _is_throttled():
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "detail": "Server under resource pressure; please retry.",
                }))
                continue

            # Stream tokens back
            full_text: List[str] = []
            if not _ai_available or _ai is None:
                stub = f"[AI stub] You asked: {message}"
                for char in stub:
                    await websocket.send_text(json.dumps({"type": "token", "token": char}))
                    await asyncio.sleep(0.01)
            else:
                try:
                    async for token in _ai.stream(message):
                        full_text.append(token)
                        await websocket.send_text(json.dumps({"type": "token", "token": token}))
                except Exception as exc:
                    await websocket.send_text(json.dumps({"type": "error", "detail": str(exc)}))
                    continue

            await websocket.send_text(json.dumps({"type": "done"}))

            # Generate and send actions
            if _ai_available and _ai is not None and full_text:
                try:
                    actions = await _ai.generate_actions("".join(full_text))
                    actions_dicts = [
                        {"type": a.type, "title": a.title, "description": a.description}
                        for a in actions
                    ]
                    await websocket.send_text(json.dumps({"type": "actions", "actions": actions_dicts}))
                except Exception:
                    pass

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        await _ws_manager.disconnect(websocket)


# ── Self-contained browser frontend (NF2-2) ───────────────────────────────────

def _build_frontend() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Novaforge — AI Remote Interface</title>
  <style>
    :root {
      --bg:          #202123;
      --panel:       #2A2B2F;
      --text:        #ECECEC;
      --ai-text:     #00FFAB;
      --accent:      #10A37F;
      --border:      #444654;
      --user-bubble: #343541;
      --ai-bubble:   #444654;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; }
    header { background: var(--panel); border-bottom: 1px solid var(--border); padding: 10px 20px; display: flex; align-items: center; gap: 16px; }
    header h1 { font-size: 1.1rem; color: var(--ai-text); }
    #theme-btn { background: var(--accent); border: none; color: #fff; border-radius: 6px; padding: 5px 14px; cursor: pointer; font-size: 0.85rem; }
    #status-dot { width: 10px; height: 10px; border-radius: 50%; background: #666; margin-left: auto; }
    #status-dot.online { background: var(--accent); }
    main { flex: 1; display: flex; overflow: hidden; }
    #chat-panel { flex: 1; display: flex; flex-direction: column; }
    #messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
    .msg { padding: 10px 14px; border-radius: 10px; max-width: 80%; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
    .msg.user { background: var(--user-bubble); align-self: flex-end; }
    .msg.ai   { background: var(--ai-bubble); color: var(--ai-text); align-self: flex-start; }
    #actions-panel { width: 260px; background: var(--panel); border-left: 1px solid var(--border); padding: 12px; overflow-y: auto; }
    #actions-panel h2 { font-size: 0.9rem; margin-bottom: 10px; color: var(--ai-text); }
    .action-btn { width: 100%; background: var(--user-bubble); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; cursor: pointer; text-align: left; font-size: 0.82rem; transition: background 0.15s; }
    .action-btn:hover { background: var(--accent); color: #fff; }
    #input-row { padding: 12px 16px; background: var(--panel); border-top: 1px solid var(--border); display: flex; gap: 8px; }
    #msg-input { flex: 1; background: var(--user-bubble); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; font-size: 0.95rem; resize: none; outline: none; }
    #send-btn { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 10px 20px; cursor: pointer; font-size: 0.95rem; }
    #send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    #resources-bar { background: var(--panel); border-top: 1px solid var(--border); padding: 4px 16px; font-size: 0.75rem; color: #888; display: flex; gap: 20px; }
  </style>
</head>
<body>
  <header>
    <h1>⚙ Novaforge AI</h1>
    <button id="theme-btn" onclick="toggleTheme()">☀ Day</button>
    <span id="status-dot" title="Connecting…"></span>
  </header>
  <main>
    <section id="chat-panel">
      <div id="messages"></div>
      <div id="input-row">
        <textarea id="msg-input" rows="2" placeholder="Ask the AI…" onkeydown="handleKey(event)"></textarea>
        <button id="send-btn" onclick="sendMessage()">Send</button>
      </div>
    </section>
    <aside id="actions-panel">
      <h2>AI Actions</h2>
      <div id="action-list"></div>
    </aside>
  </main>
  <div id="resources-bar">
    <span id="res-cpu">CPU: —</span>
    <span id="res-ram">RAM: —</span>
  </div>

<script>
const API  = '';
const KEY  = '';   // set via NOVAFORGE_API_KEY env (injected server-side if needed)
let ws = null;
let streaming = false;
let currentAIBubble = null;

function headers() {
  const h = {'Content-Type': 'application/json'};
  if (KEY) h['Authorization'] = 'Bearer ' + KEY;
  return h;
}

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = proto + '://' + location.host + '/ws/ai' + (KEY ? '?token=' + encodeURIComponent(KEY) : '');
  ws = new WebSocket(url);
  ws.onopen  = () => { document.getElementById('status-dot').className = 'online'; };
  ws.onclose = () => { document.getElementById('status-dot').className = ''; setTimeout(connectWS, 3000); };
  ws.onerror = () => { ws.close(); };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'token') appendAIToken(msg.token);
    else if (msg.type === 'done') { finaliseAI(); streaming = false; setBtn(true); }
    else if (msg.type === 'actions') renderActions(msg.actions);
    else if (msg.type === 'ping') {}
    else if (msg.type === 'error') appendMsg('ai', '[Error] ' + msg.detail);
  };
}

function sendMessage() {
  const input = document.getElementById('msg-input');
  const text = input.value.trim();
  if (!text || streaming) return;
  appendMsg('user', text);
  input.value = '';
  streaming = true;
  setBtn(false);
  currentAIBubble = null;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({message: text}));
  } else {
    // Fallback to SSE stream
    streamSSE(text);
  }
}

function streamSSE(text) {
  const url = API + '/ai/stream?message=' + encodeURIComponent(text);
  const es = new EventSource(url);
  es.onmessage = (e) => {
    if (e.data === '[DONE]') { finaliseAI(); streaming = false; setBtn(true); es.close(); return; }
    try { const d = JSON.parse(e.data); appendAIToken(d.token || e.data); }
    catch { appendAIToken(e.data); }
  };
  es.addEventListener('actions', (e) => { renderActions(JSON.parse(e.data)); });
  es.onerror = () => { es.close(); streaming = false; setBtn(true); };
}

function appendMsg(role, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  document.getElementById('messages').appendChild(div);
  div.scrollIntoView({behavior: 'smooth'});
  return div;
}

function appendAIToken(token) {
  if (!currentAIBubble) { currentAIBubble = appendMsg('ai', ''); }
  currentAIBubble.textContent += token;
  currentAIBubble.scrollIntoView({behavior: 'smooth'});
}

function finaliseAI() { currentAIBubble = null; }

function renderActions(actions) {
  const list = document.getElementById('action-list');
  list.innerHTML = '';
  actions.forEach((a, i) => {
    const btn = document.createElement('button');
    btn.className = 'action-btn';
    btn.title = a.description || '';
    btn.textContent = (a.title || a.type || 'Action ' + i);
    btn.onclick = () => executeAction(i);
    list.appendChild(btn);
  });
}

async function executeAction(idx) {
  const res = await fetch(API + '/ai/execute', {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({action_index: idx})
  });
  const data = await res.json();
  appendMsg('ai', '[Action] ' + (data.result || data.status || JSON.stringify(data)));
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function setBtn(enabled) { document.getElementById('send-btn').disabled = !enabled; }

// ── Theme toggle (NF2-4) ───────────────────────────────────────────────────
let currentTheme = 'dark';
async function toggleTheme() {
  currentTheme = currentTheme === 'dark' ? 'day' : 'dark';
  await fetch(API + '/ai/theme', {method:'POST', headers:headers(), body: JSON.stringify({theme:currentTheme})});
  applyTheme();
}
async function applyTheme() {
  const res = await fetch(API + '/ai/theme');
  const data = await res.json();
  const p = data.palette;
  const root = document.documentElement;
  root.style.setProperty('--bg',          p.bg);
  root.style.setProperty('--panel',       p.panel);
  root.style.setProperty('--text',        p.text);
  root.style.setProperty('--ai-text',     p.ai_text);
  root.style.setProperty('--accent',      p.accent);
  root.style.setProperty('--border',      p.border);
  root.style.setProperty('--user-bubble', p.user_bubble);
  root.style.setProperty('--ai-bubble',   p.ai_bubble);
  document.getElementById('theme-btn').textContent = currentTheme === 'dark' ? '☀ Day' : '🌙 Dark';
}

// ── Resource monitor (NF2-7) ──────────────────────────────────────────────
async function pollResources() {
  try {
    const res = await fetch(API + '/resources');
    const d = await res.json();
    if (d.available) {
      document.getElementById('res-cpu').textContent = 'CPU: ' + d.cpu_percent.toFixed(1) + '%';
      document.getElementById('res-ram').textContent = 'RAM: ' + d.ram_used_mb + ' / ' + d.ram_total_mb + ' MB (' + d.ram_percent.toFixed(1) + '%)';
    }
  } catch {}
}

// ── Init ──────────────────────────────────────────────────────────────────
connectWS();
setInterval(pollResources, 5000);
pollResources();
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Crash-protection supervisor (NF2-8)
# ─────────────────────────────────────────────────────────────────────────────

def _run_server() -> None:
    """Start the uvicorn server (blocking)."""
    uvicorn.run(
        app,
        host=_BIND_HOST,
        port=_BIND_PORT,
        log_level="warning",
        access_log=False,
    )


def run_with_supervisor(max_restarts: int = 10, restart_delay: float = 3.0) -> None:
    """Run the API server in a supervised loop; auto-restarts on crash (NF2-8)."""
    restarts = 0
    while restarts <= max_restarts:
        logger.info(
            "Starting Novaforge Remote API on %s:%d (attempt %d)",
            _BIND_HOST, _BIND_PORT, restarts + 1,
        )
        t = threading.Thread(target=_run_server, daemon=False)
        t.start()
        t.join()
        restarts += 1
        if restarts > max_restarts:
            logger.error("Max restarts reached (%d). Giving up.", max_restarts)
            break
        logger.warning("Server exited unexpectedly. Restarting in %.1fs …", restart_delay)
        time.sleep(restart_delay)


if __name__ == "__main__":
    logger.info(
        "Novaforge Remote API — host=%s port=%d auth=%s",
        _BIND_HOST, _BIND_PORT, "enabled" if _API_KEY else "disabled",
    )
    run_with_supervisor()
