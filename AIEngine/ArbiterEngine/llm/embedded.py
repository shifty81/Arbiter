"""Embedded LLM backend — runs a GGUF model in-process via llama-cpp-python.

No external server (Ollama / LM Studio / llama.cpp) is required.  The model
is loaded once into RAM/VRAM and kept resident for the lifetime of the server
(or until explicitly unloaded via POST /ai/embedded/unload).

Requirements (optional — install separately):
    pip install llama-cpp-python

GPU acceleration:
    • CUDA   : pip install llama-cpp-python --extra-index-url \\
                  https://abetlen.github.io/llama-cpp-python/whl/cu124
    • Metal  : already bundled on macOS Apple Silicon
    • CPU    : default pip install (no extra flags)

Config keys (config.toml → [llm.embedded]):
    model_path   = "models/model.gguf"
    n_ctx        = 4096
    n_gpu_layers = -1        # -1 = offload all layers to GPU, 0 = CPU only
    n_threads    = 0         # 0 = auto-detect
    verbose      = false
"""
from __future__ import annotations

import json as _json
import threading
from pathlib import Path
from typing import Any, Iterator

from core.logger import get_logger
from llm.base import BaseLLM

logger = get_logger(__name__)

# ── Human-readable error strings ─────────────────────────────────────────────

_NOT_INSTALLED = (
    "⚠️ **llama-cpp-python is not installed.**\n\n"
    "To use Arbiter's embedded AI (no external server required) run:\n\n"
    "```\npip install llama-cpp-python\n```\n\n"
    "For GPU acceleration:\n"
    "- **CUDA** : `pip install llama-cpp-python "
    "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124`\n"
    "- **Metal** (macOS) : already bundled\n\n"
    "After installing, restart Arbiter Engine and call `POST /ai/embedded/load`."
)

_NO_MODEL = (
    "⚠️ **No model is loaded in the embedded backend.**\n\n"
    "Call `POST /ai/embedded/load` with a `model_path` pointing to a `.gguf` file, "
    "or set `llm.embedded.model_path` in `configs/config.toml` and restart."
)


# ── Thread-safe singleton state ───────────────────────────────────────────────

class _ModelState:
    """Thread-safe container for the live ``llama_cpp.Llama`` instance."""

    def __init__(self) -> None:
        self._llm: Any = None
        self._lock = threading.Lock()
        self.model_path: str = ""
        self.n_ctx: int = 4096
        self.n_gpu_layers: int = -1
        self.n_threads: int = 0

    @property
    def is_loaded(self) -> bool:
        return self._llm is not None

    def load(
        self,
        model_path: str,
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,
        n_threads: int = 0,
        verbose: bool = False,
    ) -> None:
        """Load a GGUF model file into memory.  Thread-safe; blocks until done."""
        try:
            from llama_cpp import Llama  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(_NOT_INSTALLED) from exc

        # Resolve relative paths from the ArbiterEngine directory
        path = Path(model_path)
        if not path.is_absolute():
            base = Path(__file__).resolve().parent.parent
            path = base / model_path

        if not path.is_file():
            raise FileNotFoundError(f"GGUF model file not found: {path}")

        with self._lock:
            # Unload any existing model first to free memory
            if self._llm is not None:
                try:
                    del self._llm
                except Exception:
                    pass
                self._llm = None

            logger.info(
                "Loading embedded model: %s  ctx=%d  gpu_layers=%d",
                path, n_ctx, n_gpu_layers,
            )
            kwargs: dict[str, Any] = {
                "model_path":   str(path),
                "n_ctx":        n_ctx,
                "n_gpu_layers": n_gpu_layers,
                "verbose":      verbose,
                "chat_format":  "chatml",
            }
            if n_threads > 0:
                kwargs["n_threads"] = n_threads

            self._llm = Llama(**kwargs)
            self.model_path   = str(path)
            self.n_ctx        = n_ctx
            self.n_gpu_layers = n_gpu_layers
            self.n_threads    = n_threads
            logger.info("Embedded model loaded successfully: %s", path.name)

    def unload(self) -> None:
        """Unload the model and free RAM/VRAM."""
        with self._lock:
            if self._llm is not None:
                try:
                    del self._llm
                except Exception:
                    pass
                self._llm = None
                logger.info("Embedded model unloaded")

    def chat(self, messages: list[dict[str, str]], max_tokens: int = 1024) -> str:
        if self._llm is None:
            return _NO_MODEL
        with self._lock:
            try:
                resp = self._llm.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    stream=False,
                )
                choices = resp.get("choices", []) if isinstance(resp, dict) else []
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return ""
            except Exception as exc:
                logger.error("EmbeddedLLM chat error: %s", exc)
                return f"[ERROR] {exc}"

    def stream_chat(
        self, messages: list[dict[str, str]], max_tokens: int = 1024
    ) -> Iterator[str]:
        if self._llm is None:
            yield _NO_MODEL
            return
        # llama.cpp streaming is not thread-safe; hold the lock for the entire stream
        with self._lock:
            try:
                for chunk in self._llm.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    stream=True,
                ):
                    choices = chunk.get("choices", []) if isinstance(chunk, dict) else []
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
            except Exception as exc:
                logger.error("EmbeddedLLM stream_chat error: %s", exc)
                yield f"[ERROR] {exc}"


# Module-level singleton — shared across all EmbeddedLLM instances
_STATE = _ModelState()


def get_state() -> _ModelState:
    """Return the global embedded model state (used by server.py endpoints)."""
    return _STATE


# ── Backend class ─────────────────────────────────────────────────────────────

class EmbeddedLLM(BaseLLM):
    """In-process GGUF inference via llama-cpp-python.

    Shares the global ``_STATE`` singleton so that hot-switching backends in
    server.py always uses the already-loaded model without reloading it.
    """

    def __init__(
        self,
        model_path: str = "",
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,
        n_threads: int = 0,
        verbose: bool = False,
        auto_load: bool = True,
    ) -> None:
        self._model_path   = model_path
        self._n_ctx        = n_ctx
        self._n_gpu_layers = n_gpu_layers
        self._n_threads    = n_threads
        self._verbose      = verbose

        # Auto-load only if a path was given and no model is already resident
        if auto_load and model_path and not _STATE.is_loaded:
            try:
                _STATE.load(model_path, n_ctx, n_gpu_layers, n_threads, verbose)
            except Exception as exc:
                logger.warning("EmbeddedLLM auto-load failed: %s", exc)

    # ── BaseLLM interface ────────────────────────────────────────────────────

    def chat(self, messages: list[dict[str, str]]) -> str:
        return _STATE.chat(messages)

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        yield from _STATE.stream_chat(messages)

    def generate(self, messages: list[dict[str, str]]) -> str:
        return _STATE.chat(messages)

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
            "Respond ONLY with a valid JSON array — no explanation, no markdown.\n"
            "Format: [{\"name\": \"tool_name\", \"arguments\": {\"arg\": \"value\"}}]\n"
            "If no tool is needed respond with exactly: []\n\n"
            f"Available tools (* = required arg):\n{tools_text}"
        )
        non_system = [m for m in messages if m.get("role") != "system"]
        augmented = [{"role": "system", "content": system_content}] + non_system
        response = self.chat(augmented)
        try:
            start = response.find("[")
            end   = response.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = _json.loads(response[start:end])
                if isinstance(parsed, list):
                    return parsed
        except Exception as exc:
            logger.debug("Failed to parse embedded tool-call response: %s", exc)
        return []
