"""Google Gemini API backend."""
from __future__ import annotations
from typing import Any
import requests
from core.logger import get_logger
from llm.base import BaseLLM

logger = get_logger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _to_gemini_role(role: str) -> str:
    return "model" if role == "assistant" else "user"


def _build_contents(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Convert OpenAI-style messages to Gemini contents, merging system into first user turn."""
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    contents: list[dict[str, Any]] = []
    for i, m in enumerate(non_system):
        parts = []
        if i == 0 and system_parts:
            parts.append({"text": "\n".join(system_parts) + "\n\n" + m["content"]})
        else:
            parts.append({"text": m["content"]})
        contents.append({"role": _to_gemini_role(m.get("role", "user")), "parts": parts})
    return contents


class GeminiLLM(BaseLLM):
    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-2.0-flash",
    ) -> None:
        self.api_key = api_key
        self.model = model

    def _url(self, action: str = "generateContent") -> str:
        return f"{_BASE_URL}/{self.model}:{action}?key={self.api_key}"

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {"contents": _build_contents(messages)}
        try:
            resp = requests.post(self._url(), json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as exc:
            logger.error("Gemini chat error: %s", exc)
            return f"[ERROR] {exc}"

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self.chat(messages)

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Build Gemini function declarations
        function_declarations = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("arguments", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]
        payload = {
            "contents": _build_contents(messages),
            "tools": [{"function_declarations": function_declarations}],
        }
        try:
            resp = requests.post(self._url(), json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            result = []
            for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                fn_call = part.get("functionCall")
                if fn_call:
                    result.append({
                        "name": fn_call.get("name"),
                        "arguments": fn_call.get("args", {}),
                    })
            return result
        except Exception as exc:
            logger.error("Gemini tool_call error: %s", exc)
            return []
