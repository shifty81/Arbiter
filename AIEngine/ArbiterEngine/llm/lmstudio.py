"""LM Studio LLM backend (OpenAI-compatible local server)."""
from __future__ import annotations
import json
from typing import Any, Iterator
import requests
from core.logger import get_logger
from llm.base import BaseLLM, _fmt_unavailable

logger = get_logger(__name__)


class LMStudioLLM(BaseLLM):
    def __init__(self, base_url: str = "http://localhost:1234", model: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {"messages": messages}
        if self.model:
            payload["model"] = self.model
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=self._headers(), timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except requests.exceptions.ConnectionError:
            logger.error("LM Studio is not reachable at %s", self.base_url)
            return _fmt_unavailable("LM Studio", self.base_url)
        except Exception as exc:
            logger.error("LMStudio chat error: %s", exc)
            return f"[ERROR] {exc}"

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        payload: dict[str, Any] = {"messages": messages, "stream": True}
        if self.model:
            payload["model"] = self.model
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=self._headers(), stream=True, timeout=120,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                text = line.decode("utf-8") if isinstance(line, bytes) else line
                if text.startswith("data:"):
                    text = text[5:].strip()
                if text == "[DONE]":
                    break
                try:
                    chunk = json.loads(text)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except Exception:
                    continue
        except requests.exceptions.ConnectionError:
            logger.error("LM Studio is not reachable at %s", self.base_url)
            yield _fmt_unavailable("LM Studio", self.base_url)
        except Exception as exc:
            logger.error("LMStudio stream_chat error: %s", exc)
            yield f"[ERROR] {exc}"

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
        payload: dict[str, Any] = {"messages": messages, "tools": api_tools}
        if self.model:
            payload["model"] = self.model
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
            logger.error("LMStudio tool_call error: %s", exc)
            return []

    def list_models(self) -> list[str]:
        """Return list of models available in LM Studio."""
        try:
            resp = requests.get(f"{self.base_url}/v1/models", timeout=10)
            resp.raise_for_status()
            return [m.get("id", "") for m in resp.json().get("data", [])]
        except Exception as exc:
            logger.warning("LMStudio list_models failed: %s", exc)
            return []
