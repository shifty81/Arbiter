"""Anthropic Claude API backend."""
from __future__ import annotations
import json
from typing import Any, Iterator
import requests
from core.logger import get_logger
from llm.base import BaseLLM

logger = get_logger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicLLM(BaseLLM):
    def __init__(
        self,
        api_key: str = "",
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 4096,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _build_payload(self, messages: list[dict[str, str]], stream: bool = False) -> dict[str, Any]:
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": non_system,
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)
        if stream:
            payload["stream"] = True
        return payload

    def chat(self, messages: list[dict[str, str]]) -> str:
        try:
            resp = requests.post(
                _API_URL,
                json=self._build_payload(messages),
                headers=self._headers(),
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
        except Exception as exc:
            logger.error("Anthropic chat error: %s", exc)
            return f"[ERROR] {exc}"

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        try:
            resp = requests.post(
                _API_URL,
                json=self._build_payload(messages, stream=True),
                headers=self._headers(),
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                text = line.decode("utf-8") if isinstance(line, bytes) else line
                if text.startswith("data:"):
                    text = text[5:].strip()
                if not text or text == "[DONE]":
                    continue
                try:
                    event = json.loads(text)
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        content = delta.get("text", "")
                        if content:
                            yield content
                except Exception:
                    continue
        except Exception as exc:
            logger.error("Anthropic stream_chat error: %s", exc)
            yield f"[ERROR] {exc}"

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self.chat(messages)

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        anthropic_tools = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("arguments", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]
        payload = {**self._build_payload(messages), "tools": anthropic_tools}
        try:
            resp = requests.post(
                _API_URL,
                json=payload,
                headers=self._headers(),
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            result = []
            for block in data.get("content", []):
                if block.get("type") == "tool_use":
                    result.append({"name": block.get("name"), "arguments": block.get("input", {})})
            return result
        except Exception as exc:
            logger.error("Anthropic tool_call error: %s", exc)
            return []
