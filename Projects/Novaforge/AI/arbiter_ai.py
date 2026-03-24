"""Novaforge — ArbiterAI integration hooks stub.

Defines the ArbiterAI singleton and workspace context manager that
connect Novaforge to the ArbiterEngine backend.

Full implementation tracked in roadmap.json → NF1-6 through NF1-13.
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
        # TODO NF1-9: call /ai/actions endpoint and parse response
        return []

    def execute_action(self, action: AIAction) -> Dict[str, Any]:
        """Apply an AIAction to the project.

        NF1-10
        """
        # TODO NF1-10: dispatch action to PrefabManager / ScriptManager
        return {"status": "stub", "action": action.type}
