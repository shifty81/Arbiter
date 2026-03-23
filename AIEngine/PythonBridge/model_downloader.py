"""
Arbiter AI — Model Downloader
Detects available hardware, recommends the best GGUF model, and downloads it
from HuggingFace Hub to the standard model folder.
"""

import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, Callable

SCRIPT_DIR = Path(__file__).parent
DEFAULT_MODEL_DIR = SCRIPT_DIR.parent / "LLaMA2-13B"

# Ordered from highest VRAM requirement to lowest.
# Each entry: (min_vram_gb, repo_id, filename, label)
VRAM_TIERS: list[tuple[float, str, str, str]] = [
    (20.0, "TheBloke/Llama-2-13B-GGUF",      "llama-2-13b.Q8_0.gguf",        "13B-8bit (HQ)"),
    (12.0, "TheBloke/Llama-2-13B-GGUF",      "llama-2-13b.Q4_K_M.gguf",      "13B-4bit"),
    ( 6.0, "TheBloke/Llama-2-7B-GGUF",       "llama-2-7b.Q8_0.gguf",         "7B-8bit"),
    ( 4.0, "TheBloke/Llama-2-7B-GGUF",       "llama-2-7b.Q4_K_M.gguf",       "7B-4bit"),
    ( 0.0, "TheBloke/Mistral-7B-v0.1-GGUF",  "mistral-7b-v0.1.Q4_K_M.gguf", "Mistral-7B-4bit (CPU-friendly)"),
]

# Thread-safe download status shared with the FastAPI bridge
_status_lock = threading.Lock()
_download_status: dict = {
    "running": False,
    "progress": 0.0,
    "message": "idle",
    "model_path": None,
    "error": None,
}


def detect_vram_gb() -> float:
    """Return the total VRAM (GB) of the first CUDA device, or 0.0 if unavailable.

    Detection order:
    1. PyTorch CUDA (most accurate when a CUDA-enabled build is installed).
    2. ``nvidia-smi`` subprocess (works even with a CPU-only PyTorch build as
       long as NVIDIA drivers are present).
    """
    # ── 1. Try PyTorch first ──────────────────────────────────────────────
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except ImportError:
        pass

    # ── 2. Fallback: query nvidia-smi directly ────────────────────────────
    # This succeeds even when PyTorch was installed without CUDA support.
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
            # nvidia-smi reports memory in MiB; take the first GPU
            first_line = result.stdout.strip().splitlines()[0]
            vram_mib = float(first_line.strip())
            return vram_mib / 1024.0
    except (FileNotFoundError, IndexError, ValueError, subprocess.TimeoutExpired):
        pass

    return 0.0


def recommend_model(vram_gb: float) -> dict:
    """Return the best model dict for the given VRAM amount."""
    for min_vram, repo, filename, label in VRAM_TIERS:
        if vram_gb >= min_vram:
            return {
                "repo": repo,
                "filename": filename,
                "label": label,
                "vram_required_gb": min_vram,
            }
    # Should never be reached given 0.0 tier, but satisfy type checkers
    _, repo, filename, label = VRAM_TIERS[-1]
    return {"repo": repo, "filename": filename, "label": label, "vram_required_gb": 0.0}


def list_downloaded_models(model_dir: Optional[Path] = None) -> list[str]:
    """Return sorted list of .gguf files already present in the model directory."""
    d = model_dir or DEFAULT_MODEL_DIR
    if not d.exists():
        return []
    return sorted(str(p) for p in d.glob("*.gguf"))


def download_model(
    repo_id: str,
    filename: str,
    destination_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Path:
    """
    Download *filename* from *repo_id* on HuggingFace Hub.

    Files are saved to *destination_dir* (defaults to ``DEFAULT_MODEL_DIR``).
    *progress_callback* receives ``(percent: float, message: str)`` updates.

    Returns the local :class:`~pathlib.Path` to the downloaded file.
    Raises :class:`RuntimeError` if ``huggingface_hub`` is not installed.
    """
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except ImportError:
        raise RuntimeError(
            "huggingface_hub is required for model downloads. "
            "Run: pip install huggingface-hub"
        )

    dest = destination_dir or DEFAULT_MODEL_DIR
    dest.mkdir(parents=True, exist_ok=True)

    local_path = dest / filename
    if local_path.exists():
        if progress_callback:
            progress_callback(100.0, f"Already downloaded: {local_path}")
        return local_path

    if progress_callback:
        progress_callback(0.0, f"Downloading {filename} from {repo_id} …")

    downloaded = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=str(dest),
        local_dir_use_symlinks=False,
    )

    final_path = Path(downloaded)
    if progress_callback:
        progress_callback(100.0, f"Download complete: {final_path}")
    return final_path


def auto_download(
    destination_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Path:
    """
    Detect hardware, pick the best model, and download it.

    Returns the local path to the downloaded model file.
    """
    vram = detect_vram_gb()
    model_info = recommend_model(vram)

    if progress_callback:
        progress_callback(
            0.0,
            f"Detected {vram:.1f} GB VRAM → Recommended: {model_info['label']}",
        )

    return download_model(
        repo_id=model_info["repo"],
        filename=model_info["filename"],
        destination_dir=destination_dir,
        progress_callback=progress_callback,
    )


def start_background_download(
    repo_id: str = "",
    filename: str = "",
    auto: bool = True,
    destination_dir: Optional[Path] = None,
) -> bool:
    """
    Start a model download in a background thread.

    Progress is written to the module-level ``_download_status`` dict.
    Returns ``False`` if a download is already in progress, ``True`` otherwise.
    """
    with _status_lock:
        if _download_status["running"]:
            return False
        _download_status.update(
            running=True, progress=0.0, message="Starting…",
            model_path=None, error=None,
        )

    def _callback(pct: float, msg: str) -> None:
        with _status_lock:
            _download_status["progress"] = pct
            _download_status["message"] = msg

    def _run() -> None:
        try:
            if auto or not (repo_id and filename):
                path = auto_download(
                    destination_dir=destination_dir,
                    progress_callback=_callback,
                )
            else:
                path = download_model(
                    repo_id, filename,
                    destination_dir=destination_dir,
                    progress_callback=_callback,
                )
            with _status_lock:
                _download_status.update(
                    running=False, progress=100.0,
                    message="Complete", model_path=str(path),
                )
        except Exception as exc:
            with _status_lock:
                _download_status.update(
                    running=False, error=str(exc),
                    message=f"Error: {exc}",
                )

    threading.Thread(target=_run, daemon=True).start()
    return True


def get_download_status() -> dict:
    """Return a snapshot of the current download status."""
    with _status_lock:
        return dict(_download_status)


# ── CLI entry-point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def _print(pct: float, msg: str) -> None:
        print(f"[{pct:5.1f}%] {msg}", flush=True)

    print("Arbiter AI — Automated Model Downloader")
    print("=" * 45)
    try:
        model_path = auto_download(progress_callback=_print)
        print(f"\n✓ Model saved to: {model_path}")
        print("\nActivate with:")
        print(f"  Windows:   set ARBITER_MODEL_PATH={model_path}")
        print(f"  Linux/Mac: export ARBITER_MODEL_PATH={model_path}")
    except Exception as exc:
        print(f"\n[Error] {exc}")
        sys.exit(1)
