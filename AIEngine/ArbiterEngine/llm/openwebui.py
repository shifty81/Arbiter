"""Open WebUI LLM backend.

Connects to a running Open WebUI instance (https://github.com/open-webui/open-webui)
via its OpenAI-compatible REST API.  The default base URL is ``http://localhost:3000``.

Open WebUI setup (one-time):
    docker run -d -p 3000:8080 \\
        -v open-webui:/app/backend/data \\
        --add-host=host.docker.internal:host-gateway \\
        ghcr.io/open-webui/open-webui:main

Then open http://localhost:3000, create an account, and copy your API key from
Settings → Account → API Keys into ``configs/config.toml`` under ``[llm.openwebui]``.
"""
from __future__ import annotations
import json
from typing import Any
import requests
from core.logger import get_logger
from llm.base import BaseLLM, _fmt_unavailable

logger = get_logger(__name__)


class OpenWebUILLM(BaseLLM):
    """LLM backend that forwards requests to a local Open WebUI instance."""

    def __init__(
        self,
        base_url: str = "http://localhost:3000",
        api_key: str = "",
        model: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # If no model specified, discover the first available one at runtime.
        self._model = model

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _model_name(self) -> str:
        """Return the configured model, or auto-discover the first available one."""
        if self._model:
            return self._model
        try:
            resp = requests.get(
                f"{self.base_url}/api/models",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            if models:
                self._model = models[0].get("id", "")
                logger.info("Open WebUI: auto-selected model %r", self._model)
                return self._model
        except Exception as exc:
            logger.warning("Open WebUI model discovery failed: %s", exc)
        return "llama3"  # sensible last-resort default

    def _chat_completions(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model_name(),
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        resp = requests.post(
            f"{self.base_url}/api/chat/completions",
            json=payload,
            headers=self._headers(),
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    # ── BaseLLM interface ──────────────────────────────────────────────────────

    def chat(self, messages: list[dict[str, str]]) -> str:
        try:
            data = self._chat_completions(messages)
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.ConnectionError:
            logger.error("Open WebUI is not reachable at %s", self.base_url)
            return _fmt_unavailable("Open WebUI", self.base_url)
        except Exception as exc:
            logger.error("Open WebUI chat error: %s", exc)
            return f"[ERROR] {exc}"

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self.chat(messages)

    def tool_call(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        # Build per-tool signature lines for the system prompt
        tool_lines = []
        for t in tools:
            props = t.get("arguments", {}).get("properties", {})
            required = set(t.get("arguments", {}).get("required", []))
            params = ", ".join(
                f"{k}: {v.get('type', 'any')}{'*' if k in required else ''}"
                for k, v in props.items()
            )
            tool_lines.append(f"- {t['name']}({params}): {t.get('description', '')}")

        system_content = (
            "You are a tool-calling assistant. "
            "Respond ONLY with a valid JSON array of tool calls — no explanation, no markdown.\n"
            "Format: [{\"name\": \"tool_name\", \"arguments\": {\"arg\": \"value\"}}]\n"
            "If no tool is needed respond with exactly: []\n\n"
            "Available tools (* = required arg):\n" + "\n".join(tool_lines)
        )

        non_system = [m for m in messages if m.get("role") != "system"]
        augmented = [{"role": "system", "content": system_content}] + non_system

        response = self.chat(augmented)
        try:
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(response[start:end])
                if isinstance(parsed, list):
                    return parsed
        except Exception as exc:
            logger.debug("Open WebUI tool-call response parse failed: %s", exc)
        return []

    # ── Extra helpers ──────────────────────────────────────────────────────────

    def list_models(self) -> list[str]:
        """Return the IDs of all models available in this Open WebUI instance."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/models",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return [m.get("id", "") for m in resp.json().get("data", [])]
        except Exception as exc:
            logger.warning("Open WebUI list_models failed: %s", exc)
            return []
