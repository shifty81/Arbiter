"""Novaforge — Standalone AI Client.

Provides the Novaforge AI layer: a self-contained module that talks directly
to a local OpenAI-compatible model server (Ollama, LM Studio, LocalAI, etc.)
with no runtime dependency on ArbiterEngine or any external Arbiter service.

Arbiter is used ONLY as the development tool (IDE / chat) while building
Novaforge — it is NOT imported or called at runtime.

NF1-6:  NovaforgeAI singleton: workspace-aware, 40-prompt live memory, SQLite archive
NF1-7:  WorkspaceContext tracker
NF1-8:  Streaming AI responses via async token iterator
NF1-9:  generate_actions() → list of AIAction
NF1-10: execute_action() → safe file/script execution
NF1-11: PromptArchive SQLite tag-based archive
NF1-13: Configurable OpenAI-compat backend (Ollama / LM Studio / LocalAI)

Default endpoint: http://localhost:11434/v1  (Ollama OpenAI-compat API)
Override:         NOVAFORGE_AI_URL env var
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen


# ── Default AI endpoint ───────────────────────────────────────────────────────

_DEFAULT_AI_URL = "http://localhost:11434/v1"   # Ollama OpenAI-compat API
_DEFAULT_MODEL  = os.environ.get("NOVAFORGE_AI_MODEL", "llama3")


# ── AI Action model ───────────────────────────────────────────────────────────

@dataclass
class AIAction:
    """A single AI-generated action that can be applied to the Novaforge project."""
    type: str                        # write_file | add_script | insert_prefab | server_command
    title: str = ""
    description: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


# ── Workspace context (NF1-7) ─────────────────────────────────────────────────

class WorkspaceContext:
    """Tracks project files, tooling state, and server state for AI context.

    State is injected as a system message into every AI prompt so the model
    is always aware of the current project environment.
    """

    def __init__(self, project_root: str = ".") -> None:
        self.project_root = project_root
        self._state: Dict[str, Any] = {}

    def update(self, key: str, value: Any) -> None:
        self._state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._state)

    def build_context_string(self, max_files: int = 30) -> str:
        lines = ["=== Novaforge Workspace Context ==="]
        for k, v in self._state.items():
            lines.append(f"{k}: {v}")
        root = Path(self.project_root)
        if root.exists():
            lines.append("\nProject files (excerpt):")
            files = sorted(root.rglob("*"))
            shown = 0
            for f in files:
                if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts:
                    lines.append(f"  {f.relative_to(root)}")
                    shown += 1
                    if shown >= max_files:
                        break
        return "\n".join(lines)


# ── Prompt archive (NF1-11) ───────────────────────────────────────────────────

_NF_ROOT   = Path(__file__).resolve().parent.parent
_ARCHIVE_DB = _NF_ROOT / "data" / "prompt_archive.sqlite"


class PromptArchive:
    """SQLite-backed prompt archive with tag-based retrieval.

    NF1-11
    """

    def __init__(self, db_path: Path = _ARCHIVE_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            self._conn.commit()

    def archive(self, role: str, content: str, tags: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO prompts (role, content, tags) VALUES (?, ?, ?)",
                (role, content, tags),
            )
            self._conn.commit()

    def retrieve(self, query: str = "", limit: int = 5) -> List[Dict[str, str]]:
        """Return up to *limit* archived entries.  Simple LIKE search on content."""
        with self._lock:
            if query:
                rows = self._conn.execute(
                    "SELECT role, content FROM prompts WHERE content LIKE ? "
                    "ORDER BY id DESC LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT role, content FROM prompts ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{"role": r, "content": c} for r, c in rows]

    def close(self) -> None:
        self._conn.close()


# ── OpenAI-compat HTTP helpers ────────────────────────────────────────────────

def _openai_post(
    base_url: str,
    messages: List[Dict[str, str]],
    model: str,
    stream: bool = False,
    timeout: int = 60,
) -> Optional[Any]:
    """POST to /v1/chat/completions on an OpenAI-compatible server.

    Returns:
        - stream=False: the response content string or None on error.
        - stream=True:  the raw urllib response object (caller must read + close).
    """
    url  = f"{base_url.rstrip('/')}/chat/completions"
    body = json.dumps({
        "model":    model,
        "messages": messages,
        "stream":   stream,
    }).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=timeout)
        if stream:
            return resp
        raw = resp.read().decode()
        data = json.loads(raw)
        return data["choices"][0]["message"]["content"]
    except (URLError, KeyError, json.JSONDecodeError, IndexError, Exception):
        return None


# ── NovaforgeAI singleton (NF1-6) ─────────────────────────────────────────────

class NovaforgeAI:
    """Standalone AI manager for the Novaforge game project.

    Talks directly to a local OpenAI-compatible server (Ollama by default).
    No runtime dependency on ArbiterEngine or any external Arbiter service.
    Arbiter is only used as the developer IDE/chat while building Novaforge.

    NF1-6
    """

    _instance: Optional["NovaforgeAI"] = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "NovaforgeAI":
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialised = False
                cls._instance = inst
        return cls._instance

    def __init__(
        self,
        ai_url: str = "",
        model: str = "",
        project: str = "Novaforge",
        workspace_context: Optional[WorkspaceContext] = None,
    ) -> None:
        if self._initialised:
            return
        self.ai_url  = (ai_url or os.environ.get("NOVAFORGE_AI_URL", _DEFAULT_AI_URL)).rstrip("/")
        self.model   = model or _DEFAULT_MODEL
        self.project = project
        self.context = workspace_context or WorkspaceContext(str(_NF_ROOT))
        self._memory: List[Dict[str, str]] = []   # last 40 turns
        self._archive = PromptArchive()
        self._initialised = True

    # ── Memory helpers ────────────────────────────────────────────────────────

    def _push(self, role: str, content: str) -> None:
        self._memory.append({"role": role, "content": content})
        if len(self._memory) > 40:
            evicted = self._memory.pop(0)
            self._archive.archive(evicted["role"], evicted["content"])

    def _build_messages(self, prompt: str) -> List[Dict[str, str]]:
        msgs: List[Dict[str, str]] = []
        # System message: workspace context
        ctx = self.context.build_context_string()
        msgs.append({"role": "system", "content": ctx})
        # Relevant archive entries
        for entry in self._archive.retrieve(prompt, limit=3):
            msgs.append({"role": entry["role"], "content": f"[archived] {entry['content']}"})
        # Live memory window
        msgs.extend(self._memory)
        # Current user turn
        msgs.append({"role": "user", "content": prompt})
        return msgs

    # ── NF1-6: Single-turn query ──────────────────────────────────────────────

    def query(self, prompt: str) -> str:
        """Send a single-turn query and return the full response string."""
        self._push("user", prompt)
        msgs = self._build_messages(prompt)
        result = _openai_post(self.ai_url, msgs, self.model)
        reply  = result or "[AI unavailable — check NOVAFORGE_AI_URL and Ollama status]"
        self._push("assistant", reply)
        return reply

    # ── NF1-8: Streaming query ────────────────────────────────────────────────

    async def stream(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> AsyncIterator[str]:
        """Async token-by-token stream.  Yields each text token as a string.

        NF1-8
        """
        import asyncio
        loop = asyncio.get_event_loop()

        if context:
            for k, v in context.items():
                self.context.update(k, v)

        self._push("user", prompt)
        msgs = self._build_messages(prompt)

        def _blocking_stream() -> List[str]:
            tokens: List[str] = []
            resp = _openai_post(self.ai_url, msgs, self.model, stream=True)
            if resp is None:
                return ["[AI unavailable — check NOVAFORGE_AI_URL and Ollama status]"]
            try:
                full_reply: List[str] = []
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = (
                            chunk.get("choices", [{}])[0]
                                 .get("delta", {})
                                 .get("content", "")
                        )
                        if delta:
                            tokens.append(delta)
                            full_reply.append(delta)
                    except (json.JSONDecodeError, IndexError):
                        continue
                self._push("assistant", "".join(full_reply))
            finally:
                resp.close()
            return tokens

        tokens = await loop.run_in_executor(None, _blocking_stream)
        for token in tokens:
            yield token

    # ── NF1-9: Generate AI actions ────────────────────────────────────────────

    async def generate_actions(self, response_text: str) -> List[AIAction]:
        """Parse AI-generated action list from *response_text*.

        The model is prompted to produce a JSON array of AIActions.  Falls
        back to an empty list if parsing fails.

        NF1-9
        """
        import asyncio
        loop   = asyncio.get_event_loop()
        system = (
            "You are an action planner for the Novaforge game project.\n"
            "Given a goal or AI response, return a JSON array:\n"
            '[{"type":"write_file|add_script|insert_prefab|server_command",'
            '"title":"...","description":"...","payload":{}}]\n'
            "Output ONLY the JSON array, nothing else."
        )
        msgs = [
            {"role": "system", "content": system},
            {"role": "user",   "content": f"Goal / response:\n{response_text}"},
        ]

        def _blocking_call() -> List[AIAction]:
            result = _openai_post(self.ai_url, msgs, self.model)
            if not result:
                return []
            raw = result if isinstance(result, str) else str(result)
            try:
                start = raw.index("[")
                end   = raw.rindex("]") + 1
                data  = json.loads(raw[start:end])
                return [
                    AIAction(
                        type=a.get("type", "tooling_update"),
                        title=a.get("title", ""),
                        description=a.get("description", ""),
                        payload=a.get("payload", {}),
                    )
                    for a in data if isinstance(a, dict)
                ]
            except (ValueError, json.JSONDecodeError):
                return []

        return await loop.run_in_executor(None, _blocking_call)

    # ── NF1-10: Execute AI action ─────────────────────────────────────────────

    async def execute_action(self, action: AIAction) -> str:
        """Apply an AIAction to the Novaforge project.

        write_file: creates/overwrites a file within the project root.
        add_script: same as write_file but targets Scripts/.
        All other types return a stub message for future implementation.

        NF1-10
        """
        if action.type in ("write_file", "add_script"):
            rel_path = action.payload.get("path", "")
            content  = action.payload.get("content", "")
            if not rel_path:
                return "execute_action error: missing 'path' in payload"
            target = (Path(self.context.project_root) / rel_path).resolve()
            # Safety: must stay inside project root
            root = Path(self.context.project_root).resolve()
            if not str(target).startswith(str(root)):
                return f"execute_action error: path '{rel_path}' escapes project root"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Written {len(content)} chars to {rel_path}"
        if action.type == "server_command":
            return f"server_command '{action.payload.get('command', '')}' — pending SSA integration (NF3)"
        return f"Action type '{action.type}' — pending implementation"


# ── Backward-compatible alias ─────────────────────────────────────────────────
# ArbiterAIManager was the old name when Novaforge had a runtime dependency on
# ArbiterEngine.  Novaforge is now fully standalone.  New code should use
# NovaforgeAI directly.  This alias is kept only for source compatibility.
ArbiterAIManager = NovaforgeAI


# ── NF1-13: Backend constants ─────────────────────────────────────────────────

class ModelBackend:
    """Named constants for supported local model backends.

    All backends expose an OpenAI-compatible /v1/chat/completions API.
    """
    OLLAMA   = "http://localhost:11434/v1"     # default
    LMSTUDIO = "http://localhost:1234/v1"
    LOCALAI  = "http://localhost:8080/v1"


def get_ai(
    ai_url: str = "",
    model: str = "",
    project: str = "Novaforge",
) -> NovaforgeAI:
    """Return (or create) the NovaforgeAI singleton.

    NF1-13
    """
    return NovaforgeAI(ai_url=ai_url, model=model, project=project)
