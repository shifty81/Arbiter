"""Ollama LLM backend."""
from __future__ import annotations
import json
from typing import Any, Iterator
import requests
from core.logger import get_logger
from llm.base import BaseLLM, _fmt_unavailable

logger = get_logger(__name__)


class OllamaLLM(BaseLLM):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False}
        try:
            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
        except requests.exceptions.ConnectionError:
            logger.error("Ollama is not reachable at %s", self.base_url)
            return _fmt_unavailable("Ollama", self.base_url)
        except Exception as exc:
            logger.error("Ollama chat error: %s", exc)
            return f"[ERROR] {exc}"

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        """Stream chat response token by token using Ollama's streaming API."""
        payload = {"model": self.model, "messages": messages, "stream": True}
        try:
            resp = requests.post(
                f"{self.base_url}/api/chat", json=payload, stream=True, timeout=120
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done"):
                        break
        except requests.exceptions.ConnectionError:
            logger.error("Ollama is not reachable at %s", self.base_url)
            yield _fmt_unavailable("Ollama", self.base_url)
        except Exception as exc:
            logger.error("Ollama stream_chat error: %s", exc)
            yield f"[ERROR] {exc}"

    def generate(self, messages: list[dict[str, str]]) -> str:
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        try:
            resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except requests.exceptions.ConnectionError:
            logger.error("Ollama is not reachable at %s", self.base_url)
            return _fmt_unavailable("Ollama", self.base_url)
        except Exception as exc:
            logger.error("Ollama generate error: %s", exc)
            return f"[ERROR] {exc}"

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Build a compact per-tool signature so the model knows argument names/types.
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

        # Drop any existing system message so we don't send two conflicting ones.
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

    def list_models(self) -> list[str]:
        """Return list of locally available model names from Ollama."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", [])]
        except Exception as exc:
            logger.warning("Ollama list_models failed: %s", exc)
            return []
