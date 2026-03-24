"""Novaforge — ArbiterAI integration hooks stub.

Defines the ArbiterAI singleton and workspace context manager that
connect Novaforge to the ArbiterEngine backend.

NF1-6:  ArbiterAIManager singleton, workspace context, 40-prompt live memory
NF1-7:  WorkspaceContext tracker
NF1-8:  Streaming AI responses
NF1-9:  GenerateActionsAsync() action list
NF1-10: ExecuteActionAsync() safe execution
NF1-11: PromptArchive SQLite tag-based archive
NF1-13: Ollama / CodeGeeX open-source model backend selection
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError


# ── AI Action model ───────────────────────────────────────────────────────────

@dataclass
class AIAction:
    """A single AI-generated action that can be applied to the project.

    NF1-9
    """
    type: str                        # insert_prefab | add_script | tooling_update | server_command
    title: str = ""
    description: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


# ── Workspace context ─────────────────────────────────────────────────────────

class WorkspaceContext:
    """Tracks all project files, tooling state, and server state for AI context.

    NF1-7
    """

    def __init__(self, project_root: str = ".") -> None:
        self.project_root = project_root
        self._state: Dict[str, Any] = {}

    def update(self, key: str, value: Any) -> None:
        self._state[key] = value

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._state)


# ── ArbiterAI Manager ─────────────────────────────────────────────────────────

class ArbiterAIManager:
    """Singleton AI manager connecting Novaforge to ArbiterEngine.

    - Maintains a 40-prompt live memory window
    - Archives older prompts to SQLite via ArbiterEngine /memory endpoints
    - Streams AI responses token-by-token (NF1-8)
    - Generates and executes AI actions (NF1-9, NF1-10)

    NF1-6
    """

    _instance: Optional["ArbiterAIManager"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "ArbiterAIManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        engine_url: str = "http://127.0.0.1:8001",
        project: str = "Novaforge",
    ) -> None:
        if hasattr(self, "_initialised"):
            return
        self.engine_url = engine_url.rstrip("/")
        self.project = project
        self.context = WorkspaceContext()
        self._memory: List[Dict[str, str]] = []   # live window: last 40 turns
        self._initialised = True

    # ── Internal HTTP helpers ────────────────────────────────────────────────

    def _post(self, path: str, body: Dict[str, Any], timeout: int = 30) -> Optional[Dict]:
        url = f"{self.engine_url}{path}"
        data = json.dumps(body).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except (URLError, Exception):
            return None

    # ── Memory management ────────────────────────────────────────────────────

    def _push_memory(self, role: str, content: str) -> None:
        self._memory.append({"role": role, "content": content})
        if len(self._memory) > 40:
            # TODO NF1-11: archive oldest turns to SQLite via /memory endpoint
            self._memory.pop(0)

    # ── Public API ───────────────────────────────────────────────────────────

    def query(self, prompt: str) -> Optional[str]:
        """Send a single-turn AI query and return the response string.

        NF1-6
        """
        self._push_memory("user", prompt)
        result = self._post("/chat", {
            "project": self.project,
            "message": prompt,
            "history": self._memory[-20:],
        })
        if result:
            reply = result.get("reply", "")
            self._push_memory("assistant", reply)
            return reply
        return None

    def generate_actions(self, prompt: str) -> List[AIAction]:
        """Ask the AI to generate a list of executable AIActions.

        NF1-9
        """
        system = (
            "You are an action planner. Given a goal, return a JSON array:\n"
            '[{"type":"write_file|add_script|tooling_update","title":"...","description":"...","payload":{}}]\n'
            "Output ONLY the JSON array."
        )
        result = self._post("/chat", {
            "project": self.project,
            "message": prompt,
            "history": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
        })
        if not result:
            return []
        raw = result.get("reply", "[]")
        try:
            start, end = raw.index("["), raw.rindex("]") + 1
            actions_data = json.loads(raw[start:end])
            return [AIAction(**a) for a in actions_data if isinstance(a, dict)]
        except Exception:
            return []

    def execute_action(self, action: AIAction) -> Dict[str, Any]:
        """Apply an AIAction to the project.

        NF1-10
        """
        if action.type == "write_file":
            rel_path = action.payload.get("path", "")
            content  = action.payload.get("content", "")
            if not rel_path:
                return {"status": "error", "message": "missing path in payload"}
            import pathlib
            target = pathlib.Path(rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {"status": "ok", "message": f"Written {len(content)} chars to {rel_path}"}
        return {"status": "stub", "action": action.type}


# ── NF1-13: Model backend selector ───────────────────────────────────────────

class ModelBackend:
    """Enum-like constants for supported open-source model backends.

    NF1-13
    """
    OLLAMA   = "ollama"
    CODEGEEX = "codegeex"
    LMSTUDIO = "lmstudio"
    LOCALAI  = "localai"


def select_backend(
    backend: str = ModelBackend.OLLAMA,
    engine_url: str = "http://127.0.0.1:8001",
) -> "ArbiterAIManager":
    """Return an ArbiterAIManager instance configured to use *backend*.

    The backend is set on the ArbiterEngine server via the /models/switch
    endpoint so all subsequent requests use the chosen model.

    NF1-13
    """
    import urllib.request as _urllib
    try:
        req = _urllib.Request(
            f"{engine_url}/models/switch?backend={backend}",
            data=b"",
            method="POST",
        )
        _urllib.urlopen(req, timeout=5)
    except Exception:
        pass   # Best-effort — ArbiterEngine may not be running yet

    mgr = ArbiterAIManager(engine_url=engine_url)
    return mgr

