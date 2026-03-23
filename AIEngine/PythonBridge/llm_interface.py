"""
Arbiter AI — LLM Interface
Handles hardware-aware model loading and response generation.
Supports local LLaMA-style models via llama-cpp-python, Ollama, or a stub fallback.
"""

import json
import os
import subprocess
import urllib.error
import urllib.request

_model = None
_tokenizer = None
_ollama_model_name: str = ""

# VRAM threshold (GB) for enabling GPU acceleration in llama-cpp-python
MIN_VRAM_FOR_GPU_GB = 6.0

# Ollama REST API base URL (default local installation)
OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _detect_vram_gb() -> float:
    """Return the total VRAM (GB) of the first CUDA device, or 0.0 if unavailable.

    Detection order:
    1. PyTorch CUDA (most accurate when a CUDA-enabled build is installed).
    2. ``nvidia-smi`` subprocess (works even with a CPU-only PyTorch build as
       long as NVIDIA drivers are present).
    """
    # ── 1. Try PyTorch first ──────────────────────────────────────────────
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except ImportError:
        pass

    # ── 2. Fallback: query nvidia-smi directly ────────────────────────────
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            first_line = result.stdout.strip().splitlines()[0]
            vram_mib = float(first_line.strip())
            return vram_mib / 1024.0
    except (FileNotFoundError, IndexError, ValueError, subprocess.TimeoutExpired):
        pass

    return 0.0


def _find_model_in_default_dir() -> str:
    """
    Scan the default model directory for .gguf files.
    Prefers the file that matches the hardware-recommended model name;
    falls back to the first .gguf found.
    Returns an empty string if none exist.
    """
    try:
        from model_downloader import DEFAULT_MODEL_DIR, recommend_model, detect_vram_gb
    except ImportError:
        return ""

    if not DEFAULT_MODEL_DIR.exists():
        return ""

    gguf_files = sorted(DEFAULT_MODEL_DIR.glob("*.gguf"))
    if not gguf_files:
        return ""

    # Prefer the hardware-recommended model if it is present
    vram = detect_vram_gb()
    preferred = recommend_model(vram)["filename"]
    preferred_path = DEFAULT_MODEL_DIR / preferred
    if preferred_path.exists():
        return str(preferred_path)

    return str(gguf_files[0])


def _try_connect_ollama() -> str:
    """
    Check whether a local Ollama instance is running and has at least one model.
    Returns the name of the first available model, or an empty string if unavailable.
    """
    try:
        with urllib.request.urlopen(
            f"{OLLAMA_BASE_URL}/api/tags", timeout=3
        ) as resp:
            data = json.loads(resp.read())
            models = data.get("models", [])
            if models:
                return models[0]["name"]
    except Exception:
        pass
    return ""


def _load_model():
    global _model, _tokenizer, _ollama_model_name
    if _model is not None:
        return

    # 1. Explicit override via environment variable
    model_path = os.environ.get("ARBITER_MODEL_PATH", "")

    # 2. Auto-discover any .gguf in the standard model folder
    if not model_path or not os.path.exists(model_path):
        model_path = _find_model_in_default_dir()

    vram = _detect_vram_gb()

    # Try llama-cpp-python first (most efficient for local LLMs)
    if model_path and os.path.exists(model_path):
        try:
            from llama_cpp import Llama
            n_gpu_layers = -1 if vram >= MIN_VRAM_FOR_GPU_GB else 0
            _model = Llama(model_path=model_path, n_gpu_layers=n_gpu_layers, n_ctx=2048)
            print(f"[LLM] Loaded GGUF model from {model_path} (GPU layers: {n_gpu_layers})")
            return
        except ImportError:
            print("[LLM] llama-cpp-python not installed — skipping GGUF loader. "
                  "Install it with: pip install llama-cpp-python")

    # Try Ollama next (easy local LLM runner — just needs `ollama` installed & a model pulled)
    ollama_model = _try_connect_ollama()
    if ollama_model:
        _ollama_model_name = ollama_model
        _model = "ollama"
        print(f"[LLM] Using Ollama model: {ollama_model}  (host: {OLLAMA_BASE_URL})")
        return

    # Fallback: stub responder (no model installed)
    print("[LLM] No model configured — using stub responder. "
          "Run setup_arbiter.py or POST /models/download to download a model automatically, "
          "or install Ollama (https://ollama.com) and run: ollama pull mistral")
    _model = "stub"


def get_model_status() -> dict:
    """
    Return the current LLM backend status without triggering a load.
    If the model has not been loaded yet, trigger loading now.
    """
    _load_model()
    if _model == "stub":
        return {"backend": "stub", "detail": "No model configured"}
    if _model == "ollama":
        return {"backend": "ollama", "detail": _ollama_model_name}
    if _model is not None:
        path = os.environ.get("ARBITER_MODEL_PATH") or _find_model_in_default_dir()
        return {"backend": "gguf", "detail": path}
    return {"backend": "not_loaded", "detail": ""}


def preload_model() -> None:
    """Public entry-point for pre-loading the model at server startup."""
    _load_model()


def generate_response(
    message: str,
    project: str,
    max_tokens: int = 512,
    system_prompt: str = "",
) -> str:
    """Generate a response from Arbiter's LLM.

    Args:
        message:       The user's input message.
        project:       The active project name (used in the default system prompt).
        max_tokens:    Maximum number of tokens to generate.
        system_prompt: Optional override for the system prompt.  When empty the
                       default Arbiter persona prompt is used.
    """
    _load_model()

    if not system_prompt:
        try:
            from persona_manager import get_system_prompt, DEFAULT_PERSONA
            system_prompt = get_system_prompt(DEFAULT_PERSONA, project)
        except ImportError:
            system_prompt = (
                "You are Arbiter, a personal autonomous AI development assistant. "
                "You are precise, technical, and explain your reasoning clearly. "
                f"You are currently working on the project: {project}."
            )

    if _model == "stub" or _model is None:
        return (
            f"[Stub] Arbiter received: '{message}' for project '{project}'. "
            "Configure ARBITER_MODEL_PATH to enable real LLM inference, "
            "or install Ollama (https://ollama.com) and run: ollama pull mistral"
        )

    # ── Ollama inference ──────────────────────────────────────────────────────
    if _model == "ollama":
        try:
            payload = json.dumps({
                "model": _ollama_model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": message},
                ],
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                f"{OLLAMA_BASE_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
                return data["message"]["content"].strip()
        except Exception as e:
            return f"[Ollama Error] {e}"

    # ── llama-cpp-python inference ────────────────────────────────────────────
    try:
        prompt = f"<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n{message} [/INST]"
        output = _model(prompt, max_tokens=max_tokens, stop=["</s>", "[INST]"])
        return output["choices"][0]["text"].strip()
    except Exception as e:
        return f"[LLM Error] {str(e)}"
