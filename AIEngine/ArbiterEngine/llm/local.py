"""Local (stub) LLM backend for offline/testing use."""
from __future__ import annotations
from typing import Any
from core.logger import get_logger
from llm.base import BaseLLM

logger = get_logger(__name__)


class LocalLLM(BaseLLM):
    """Stub local LLM. In production load a GGUF model via llama-cpp-python."""

    def __init__(self, model_path: str = "") -> None:
        self.model_path = model_path
        if model_path:
            logger.info("LocalLLM: would load model from %s", model_path)
        else:
            logger.warning("LocalLLM: no model path configured, using stub responses")

    _SETUP_MSG = (
        "⚠️ **No LLM backend is configured.**\n\n"
        "Arbiter needs a running LLM to answer questions. "
        "Set one up and select it in the model picker:\n\n"
        "| Backend | How to start |\n"
        "|---|---|\n"
        "| **Ollama** *(recommended)* | Install from https://ollama.ai, then `ollama pull llama3` |\n"
        "| **LM Studio** | Download from https://lmstudio.ai and start the local server |\n"
        "| **LocalAI** | See https://localai.io |\n"
        "| **llama.cpp** | Run `./llama-server -m model.gguf --port 8080` |\n\n"
        "Then pick the matching backend in the **model selector** at the bottom of the Chat panel."
    )

    def chat(self, messages: list[dict[str, str]]) -> str:
        return self._SETUP_MSG

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self._SETUP_MSG

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return []
