"""CodeGeeX LLM backend.

CodeGeeX exposes an OpenAI-compatible REST API, so this backend uses
the same /v1/chat/completions path as the generic API backend but is
pre-configured for CodeGeeX's default local port (8082) and provides
CodeGeeX-specific model defaults.

Typical local server startup:
    codegeex-server --model codegeex-4-all-9b --port 8082

Or via the official CLI:
    codegeex --port 8082
"""
from __future__ import annotations

import json
from typing import Any, Iterator

import requests

from core.logger import get_logger
from llm.base import BaseLLM, _fmt_unavailable

logger = get_logger(__name__)

_DEFAULT_MODEL = "codegeex-4-all-9b"


class CodeGeeXLLM(BaseLLM):
    """LLM backend for the CodeGeeX local inference server.

    The server speaks the OpenAI-compatible ``/v1/chat/completions`` protocol.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8082",
        model: str = _DEFAULT_MODEL,
        api_key: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model or _DEFAULT_MODEL
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _chat_completions_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def _build_payload(self, messages: list[dict[str, str]], stream: bool = False) -> dict:
        return {"model": self.model, "messages": messages, "stream": stream}

    # ── BaseLLM implementation ────────────────────────────────────────────────

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = self._build_payload(messages, stream=False)
        try:
            resp = requests.post(
                self._chat_completions_url(),
                json=payload,
                headers=self._headers,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.ConnectionError:
            logger.error("CodeGeeX is not reachable at %s", self.base_url)
            return _fmt_unavailable("CodeGeeX", self.base_url)
        except Exception as exc:
            logger.error("CodeGeeX chat error: %s", exc)
            return f"[ERROR] {exc}"

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        """Stream chat response token by token via SSE."""
        payload = self._build_payload(messages, stream=True)
        try:
            resp = requests.post(
                self._chat_completions_url(),
                json=payload,
                headers=self._headers,
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                text = line.decode("utf-8") if isinstance(line, bytes) else line
                if text.startswith("data: "):
                    text = text[6:]
                if text == "[DONE]":
                    break
                try:
                    data = json.loads(text)
                    delta = data["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except Exception:
                    continue
        except requests.exceptions.ConnectionError:
            logger.error("CodeGeeX is not reachable at %s", self.base_url)
            yield _fmt_unavailable("CodeGeeX", self.base_url)
        except Exception as exc:
            logger.error("CodeGeeX stream_chat error: %s", exc)
            yield f"[ERROR] {exc}"

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self.chat(messages)

    def tool_call(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tool_lines = []
        for t in tools:
            props = t.get("arguments", {}).get("properties", {})
            required = set(t.get("arguments", {}).get("required", []))
            params = ", ".join(
                f"{k}: {v.get('type', 'any')}{'*' if k in required else ''}"
                for k, v in props.items()
            )
            tool_lines.append(f"- {t['name']}({params}): {t.get('description', '')}")
        tools_text = "\n".join(tool_lines)

        system_content = (
            "You are a tool-calling assistant. "
            "Respond ONLY with a valid JSON array of tool calls — no explanation, no markdown.\n"
            "Format: [{\"name\": \"tool_name\", \"arguments\": {\"arg\": \"value\"}}]\n"
            "If no tool is needed respond with exactly: []\n\n"
            f"Available tools (* = required arg):\n{tools_text}"
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
            logger.debug("Failed to parse CodeGeeX tool-call response: %s", exc)
        return []

    def list_models(self) -> list[str]:
        """Return available models from the CodeGeeX server."""
        try:
            resp = requests.get(
                f"{self.base_url}/v1/models",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return [m.get("id", "") for m in data.get("data", [])]
        except Exception as exc:
            logger.warning("CodeGeeX list_models failed: %s", exc)
            return [_DEFAULT_MODEL]
