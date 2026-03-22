#!/usr/bin/env python3
"""
Arbiter AI — One-Click Setup
Automates:
  1. Python dependency installation
  2. Hardware detection (GPU / VRAM)
  3. Automatic model selection and download
  4. Model path configuration (.env)

Run from the repository root:
    python setup_arbiter.py
"""

import os
import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent
BRIDGE_DIR = REPO_ROOT / "AIEngine" / "PythonBridge"
MODEL_DIR = REPO_ROOT / "AIEngine" / "LLaMA2-13B"
REQUIREMENTS = BRIDGE_DIR / "requirements.txt"
ENV_FILE = REPO_ROOT / ".env"


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"\n[Error] Command failed (exit {result.returncode}). Aborting.")
        sys.exit(result.returncode)
    return result


def _banner(text: str) -> None:
    width = 52
    print("\n" + "=" * width)
    print(f"  {text}")
    print("=" * width)


def main() -> None:
    _banner("Arbiter AI — Automated Setup")

    # ── Step 1: Install Python dependencies ───────────────────────────────
    print("\n[1/4] Installing Python dependencies …")
    _run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS), "--quiet"],
    )
    print("  ✓ Dependencies installed")

    # ── Step 2: Detect hardware ────────────────────────────────────────────
    print("\n[2/4] Detecting hardware …")
    sys.path.insert(0, str(BRIDGE_DIR))
    from model_downloader import (  # noqa: E402  (inserted into path above)
        detect_vram_gb,
        recommend_model,
        list_downloaded_models,
        download_model,
    )

    vram = detect_vram_gb()
    print(f"  GPU VRAM   : {vram:.1f} GB")

    # Warn if nvidia-smi found a GPU but PyTorch didn't (CPU-only build)
    if vram > 0.0:
        try:
            import torch  # noqa: F401
            if not torch.cuda.is_available():
                print(
                    "\n  ⚠ Warning: GPU detected via nvidia-smi but PyTorch reports no CUDA.\n"
                    "    You appear to have a CPU-only PyTorch build installed.\n"
                    "    For GPU-accelerated inference, reinstall PyTorch with CUDA support:\n"
                    "      pip install torch --index-url https://download.pytorch.org/whl/cu121\n"
                    "    (replace cu121 with the CUDA version shown by: nvidia-smi)\n"
                )
        except ImportError:
            pass

    model_info = recommend_model(vram)
    print(f"  Recommended: {model_info['label']}  ({model_info['filename']})")

    # ── Step 3: Download model (skip if already present) ──────────────────
    print("\n[3/4] Checking for existing models …")
    existing = list_downloaded_models(MODEL_DIR)
    if existing:
        model_path = Path(existing[0])
        print(f"  ✓ Found existing model: {model_path}")
    else:
        print(f"\n  Downloading {model_info['label']} — this may take a few minutes …")

        def _progress(pct: float, msg: str) -> None:
            bar_len = 30
            filled = int(bar_len * pct / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"\r  [{bar}] {pct:5.1f}%  {msg:<50}", end="", flush=True)

        try:
            model_path = download_model(
                repo_id=model_info["repo"],
                filename=model_info["filename"],
                destination_dir=MODEL_DIR,
                progress_callback=_progress,
            )
            print(f"\n  ✓ Model saved to: {model_path}")
        except RuntimeError as exc:
            print(f"\n\n[Error] {exc}")
            sys.exit(1)

    # ── Step 4: Write .env configuration ──────────────────────────────────
    print("\n[4/4] Writing configuration …")
    env_lines: list[str] = []
    if ENV_FILE.exists():
        # Preserve any existing entries, replacing ARBITER_MODEL_PATH if present
        kept = [
            ln for ln in ENV_FILE.read_text(encoding="utf-8").splitlines()
            if not ln.startswith("ARBITER_MODEL_PATH=")
        ]
        env_lines = kept

    env_lines.append(f"ARBITER_MODEL_PATH={model_path}")
    ENV_FILE.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    print(f"  ✓ Config written to: {ENV_FILE}")

    # ── Done ───────────────────────────────────────────────────────────────
    _banner("Setup complete!")
    print(f"\n  Model : {model_path}")
    print(f"  Config: {ENV_FILE}")
    print("\nTo start the Arbiter bridge:")
    print(f"  cd {BRIDGE_DIR}")
    print("  python fastapi_bridge.py\n")


if __name__ == "__main__":
    main()
