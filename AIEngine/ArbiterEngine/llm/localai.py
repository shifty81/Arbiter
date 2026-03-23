"""LocalAI LLM backend.

LocalAI (https://github.com/mudler/LocalAI) is a free, open-source,
OpenAI-compatible API server that runs models locally using CPU/GPU.
It supports GGUF, GGML, GPTQ and many other formats.

Quick start (Docker):
    docker run -d -p 8080:8080 \\
        -v $(pwd)/models:/models \\
        ghcr.io/mudler/localai:latest

    # Download a model (e.g. codestral):
    curl http://localhost:8080/models/apply -d '{"id": "huggingface://bartowski/Codestral-22B-v0.1-GGUF/Codestral-22B-v0.1-Q4_K_M.gguf"}'

LocalAI provides a fully OpenAI-compatible /v1 endpoint so this backend
is a thin wrapper around the existing APILlm class.

See configs/config.toml [llm.localai] for URL and model configuration.
"""
from __future__ import annotations
from typing import Any
from llm.api import APILlm
from core.logger import get_logger

logger = get_logger(__name__)


class LocalAILlm(APILlm):
    """LLM backend that forwards requests to a local LocalAI instance.

    LocalAI is fully OpenAI-API-compatible, so this class only needs to
    set the correct base URL and suppress the Authorization header when no
    API key is configured.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        model: str = "codestral",
        api_key: str = "",
    ) -> None:
        # LocalAI does not require an API key when run locally
        super().__init__(base_url=base_url, api_key=api_key, model=model)
        logger.info(
            "LocalAI backend: %s  model=%s", self.base_url, self.model
        )

    def list_models(self) -> list[str]:
        """Return the IDs of all models available in this LocalAI instance."""
        import requests
        try:
            resp = requests.get(
                f"{self.base_url}/v1/models",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return [m.get("id", "") for m in resp.json().get("data", [])]
        except Exception as exc:
            logger.warning("LocalAI list_models failed: %s", exc)
            return []
