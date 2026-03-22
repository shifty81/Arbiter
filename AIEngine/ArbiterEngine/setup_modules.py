#!/usr/bin/env python3
"""
setup_modules.py — Fetch Arbiter Engine modules from the SwissAgent repository.

Run this once after cloning ArbiterAI to populate AIEngine/ArbiterEngine/modules/
with the full 42-module toolset.

Usage:
    python setup_modules.py
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_URL = "https://github.com/shifty81/SwissAgent.git"
MODULES_SRC = "modules"
BASE_DIR = Path(__file__).resolve().parent
MODULES_DST = BASE_DIR / "modules"


def main() -> None:
    print("Arbiter Engine — Module Setup")
    print("=" * 40)

    if any(MODULES_DST.iterdir()) if MODULES_DST.exists() else False:
        ans = input("modules/ already contains files. Overwrite? [y/N] ").strip().lower()
        if ans != "y":
            print("Aborted.")
            return

    print(f"Cloning {REPO_URL} (shallow) …")
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            ["git", "clone", "--depth=1", "--filter=blob:none", "--sparse", REPO_URL, tmp],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"git clone failed:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)

        subprocess.run(
            ["git", "sparse-checkout", "set", MODULES_SRC],
            cwd=tmp, capture_output=True, check=True,
        )

        src = Path(tmp) / MODULES_SRC
        if not src.is_dir():
            print("modules/ directory not found in cloned repo.", file=sys.stderr)
            sys.exit(1)

        if MODULES_DST.exists():
            shutil.rmtree(MODULES_DST)
        shutil.copytree(src, MODULES_DST)

    count = sum(1 for p in MODULES_DST.iterdir() if p.is_dir())
    print(f"✅ {count} modules installed to {MODULES_DST}")
    print("\nNext steps:")
    print("  1. Install Python deps:  pip install -r requirements.txt")
    print("  2. Start Arbiter Engine: python server.py")
    print("  3. Launch ArbiterAI and choose 'Arbiter Engine' in the launcher.")


if __name__ == "__main__":
    main()
