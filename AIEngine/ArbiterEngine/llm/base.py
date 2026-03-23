"""Base LLM interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Iterator


def _fmt_unavailable(backend_name: str, url: str) -> str:
    return (
        f"⚠️ **{backend_name} is not reachable** at `{url}`.\n\n"
        "The service appears to be offline or the URL is incorrect. "
        "Please start the backend and try again, or switch to a different LLM in the model selector.\n\n"
        "| Backend | How to start |\n"
        "|---|---|\n"
        "| **Ollama** *(recommended)* | Install from https://ollama.ai, then `ollama pull llama3` |\n"
        "| **LM Studio** | Download from https://lmstudio.ai and start the local server |\n"
        "| **LocalAI** | See https://localai.io |\n"
        "| **llama.cpp** | Run `./llama-server -m model.gguf --port 8080` |\n"
    )


class BaseLLM(ABC):
    @abstractmethod
    def chat(self, messages: list[dict[str, str]]) -> str: ...

    @abstractmethod
    def generate(self, messages: list[dict[str, str]]) -> str: ...

    @abstractmethod
    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        yield self.chat(messages)
