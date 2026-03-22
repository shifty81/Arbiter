"""LLM factory — creates the appropriate backend from config."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config_loader import ConfigLoader
    from llm.base import BaseLLM


def create_llm(backend: str, config: "ConfigLoader") -> "BaseLLM":
    backend = backend.lower()
    if backend == "ollama":
        from llm.ollama import OllamaLLM
        return OllamaLLM(
            base_url=config.get("llm.ollama.base_url", "http://localhost:11434"),
            model=config.get("llm.ollama.model", "llama3"),
        )
    if backend == "api":
        from llm.api import APILlm
        return APILlm(
            base_url=config.get("llm.api.base_url", "https://api.openai.com"),
            api_key=config.get("llm.api.key", ""),
            model=config.get("llm.api.model", "gpt-3.5-turbo"),
        )
    if backend == "openwebui":
        from llm.openwebui import OpenWebUILLM
        return OpenWebUILLM(
            base_url=config.get("llm.openwebui.base_url", "http://localhost:3000"),
            api_key=config.get("llm.openwebui.key", ""),
            model=config.get("llm.openwebui.model", ""),
        )
    if backend == "localai":
        from llm.localai import LocalAILlm
        return LocalAILlm(
            base_url=config.get("llm.localai.base_url", "http://localhost:8080"),
            model=config.get("llm.localai.model", "codestral"),
            api_key=config.get("llm.localai.key", ""),
        )
    if backend == "lmstudio":
        from llm.lmstudio import LMStudioLLM
        return LMStudioLLM(
            base_url=config.get("llm.lmstudio.base_url", "http://localhost:1234"),
            model=config.get("llm.lmstudio.model", ""),
        )
    if backend == "llamacpp":
        from llm.llamacpp import LlamaCppLLM
        return LlamaCppLLM(
            base_url=config.get("llm.llamacpp.base_url", "http://localhost:8080"),
            model=config.get("llm.llamacpp.model", ""),
        )
    if backend == "tabby":
        from llm.tabby import TabbyLLM
        return TabbyLLM(
            base_url=config.get("llm.tabby.base_url", "http://localhost:8080"),
            api_key=config.get("llm.tabby.key", ""),
            model=config.get("llm.tabby.model", ""),
        )
    if backend == "anthropic":
        from llm.anthropic import AnthropicLLM
        return AnthropicLLM(
            api_key=config.get("llm.anthropic.key", ""),
            model=config.get("llm.anthropic.model", "claude-3-5-sonnet-20241022"),
        )
    if backend == "gemini":
        from llm.gemini import GeminiLLM
        return GeminiLLM(
            api_key=config.get("llm.gemini.key", ""),
            model=config.get("llm.gemini.model", "gemini-2.0-flash"),
        )
    from llm.local import LocalLLM
    return LocalLLM(model_path=config.get("llm.local.model_path", ""))
