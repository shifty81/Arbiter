"""llama.cpp server backend (native /completion endpoint)."""
from __future__ import annotations
import json
from typing import Any, Iterator
import requests
from core.logger import get_logger
from llm.base import BaseLLM, _fmt_unavailable

logger = get_logger(__name__)

_ROLE_PREFIX = {"system": "System", "user": "User", "assistant": "Assistant"}


def _format_prompt(messages: list[dict[str, str]]) -> str:
    parts = []
    for m in messages:
        role = _ROLE_PREFIX.get(m.get("role", "user"), "User")
        parts.append(f"{role}: {m['content']}")
    parts.append("Assistant:")
    return "\n".join(parts)


class LlamaCppLLM(BaseLLM):
    def __init__(self, base_url: str = "http://localhost:8080", model: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _openai_chat(self, messages: list[dict[str, str]]) -> str | None:
        """Try the OpenAI-compatible endpoint first (newer llama.cpp builds)."""
        payload: dict[str, Any] = {"messages": messages}
        if self.model:
            payload["model"] = self.model
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=self._headers(), timeout=120,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except requests.HTTPError:
            return None
        except Exception as exc:
            logger.debug("LlamaCpp OpenAI-compat chat failed: %s", exc)
            return None

    def _native_chat(self, messages: list[dict[str, str]]) -> str:
        """Fall back to the native /completion endpoint."""
        prompt = _format_prompt(messages)
        payload = {"prompt": prompt, "n_predict": 512}
        try:
            resp = requests.post(
                f"{self.base_url}/completion",
                json=payload, headers=self._headers(), timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("content", "")
        except requests.exceptions.ConnectionError:
            logger.error("llama.cpp is not reachable at %s", self.base_url)
            return _fmt_unavailable("llama.cpp", self.base_url)
        except Exception as exc:
            logger.error("LlamaCpp native chat error: %s", exc)
            return f"[ERROR] {exc}"

    def chat(self, messages: list[dict[str, str]]) -> str:
        result = self._openai_chat(messages)
        if result is not None:
            return result
        return self._native_chat(messages)

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        payload: dict[str, Any] = {"messages": messages, "stream": True}
        if self.model:
            payload["model"] = self.model
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=self._headers(), stream=True, timeout=120,
            )
            if resp.status_code == 404:
                # Fall back to native streaming
                yield from self._native_stream(messages)
                return
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
            logger.error("llama.cpp is not reachable at %s", self.base_url)
            yield _fmt_unavailable("llama.cpp", self.base_url)
        except Exception as exc:
            logger.error("LlamaCpp stream_chat error: %s", exc)
            yield f"[ERROR] {exc}"

    def _native_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        prompt = _format_prompt(messages)
        payload = {"prompt": prompt, "n_predict": 512, "stream": True}
        try:
            resp = requests.post(
                f"{self.base_url}/completion",
                json=payload, headers=self._headers(), stream=True, timeout=120,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    content = data.get("content", "")
                    if content:
                        yield content
                    if data.get("stop"):
                        break
                except Exception:
                    continue
        except requests.exceptions.ConnectionError:
            logger.error("llama.cpp is not reachable at %s", self.base_url)
            yield _fmt_unavailable("llama.cpp", self.base_url)
        except Exception as exc:
            logger.error("LlamaCpp native stream error: %s", exc)
            yield f"[ERROR] {exc}"

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self.chat(messages)

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # llama.cpp doesn't natively support tool-calling; delegate to chat-based approach
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
            logger.debug("Failed to parse tool-call response: %s", exc)
        return []
