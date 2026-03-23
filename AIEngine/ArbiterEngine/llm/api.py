"""API-based LLM backend (OpenAI-compatible)."""
from __future__ import annotations
import json
from typing import Any
import requests
from core.logger import get_logger
from llm.base import BaseLLM, _fmt_unavailable

logger = get_logger(__name__)


class APILlm(BaseLLM):
    def __init__(self, base_url: str, api_key: str = "", model: str = "gpt-3.5-turbo") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {"model": self.model, "messages": messages}
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=self._headers(), timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except requests.exceptions.ConnectionError:
            logger.error("API backend is not reachable at %s", self.base_url)
            return _fmt_unavailable("API backend", self.base_url)
        except Exception as exc:
            logger.error("API chat error: %s", exc)
            return f"[ERROR] {exc}"

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self.chat(messages)

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        api_tools = [
            {"type": "function", "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("arguments", {}),
            }}
            for t in tools
        ]
        payload = {"model": self.model, "messages": messages, "tools": api_tools}
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=self._headers(), timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            calls = data["choices"][0]["message"].get("tool_calls", [])
            result = []
            for c in calls:
                fn = c.get("function", {})
                args = json.loads(fn.get("arguments", "{}"))
                result.append({"name": fn.get("name"), "arguments": args})
            return result
        except Exception as exc:
            logger.error("API tool_call error: %s", exc)
            return []
