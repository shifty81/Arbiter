"""Tabby code completion backend (TabbyML)."""
from __future__ import annotations
from typing import Any
import requests
from core.logger import get_logger
from llm.base import BaseLLM

logger = get_logger(__name__)


class TabbyLLM(BaseLLM):
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str = "",
        model: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def complete(self, prefix: str, suffix: str = "", language: str = "python") -> str:
        """Native Tabby code-completion endpoint."""
        payload: dict[str, Any] = {
            "language": language,
            "segments": {"prefix": prefix, "suffix": suffix},
        }
        if self.model:
            payload["model"] = self.model
        try:
            resp = requests.post(
                f"{self.base_url}/v1/completions",
                json=payload, headers=self._headers(), timeout=60,
            )
            resp.raise_for_status()
            choices = resp.json().get("choices", [])
            return choices[0].get("text", "") if choices else ""
        except Exception as exc:
            logger.error("Tabby complete error: %s", exc)
            return f"[ERROR] {exc}"

    def chat(self, messages: list[dict[str, str]]) -> str:
        """Attempt OpenAI-compatible chat; fall back to wrapping last user message as completion."""
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={"messages": messages, **({"model": self.model} if self.model else {})},
                headers=self._headers(),
                timeout=120,
            )
            if resp.status_code not in (404, 405):
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except requests.HTTPError:
            pass
        except Exception as exc:
            logger.debug("Tabby chat/completions failed: %s", exc)

        # Fall back to native completion using the last user message as prefix
        user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
        prefix = user_msgs[-1] if user_msgs else ""
        return self.complete(prefix)

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self.chat(messages)

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Tabby is primarily a code completion engine; best-effort via chat
        return []
