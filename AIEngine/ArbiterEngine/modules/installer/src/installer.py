"""Installer module — dependency installation and distributable package creation."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


def _run(cmd: list[str], cwd: str | None = None) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=120)
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Executable not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "Command timed out"}
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}


def install_deps(path: str, **kwargs) -> dict:
    """Install all project dependencies found in *path*.

    Supports:
    - ``requirements.txt``  → ``pip install -r requirements.txt``
    - ``package.json``      → ``npm install``
    - ``Gemfile``           → ``bundle install``
    - ``Cargo.toml``        → ``cargo fetch``
    - ``go.mod``            → ``go mod download``
    """
    root = Path(path)
    if not root.is_dir():
        return {"status": "error", "error": f"Directory not found: {path}"}

    results: list[dict] = []
    installed: list[str] = []

    # Python
    req = root / "requirements.txt"
    if req.exists():
        r = _run([sys.executable, "-m", "pip", "install", "-r", str(req)], cwd=str(root))
        results.append({"manager": "pip", **r})
        if r["returncode"] == 0:
            installed.append("pip")

    # Node.js
    pkg = root / "package.json"
    if pkg.exists() and shutil.which("npm"):
        r = _run(["npm", "install"], cwd=str(root))
        results.append({"manager": "npm", **r})
        if r["returncode"] == 0:
            installed.append("npm")

    # Ruby
    if (root / "Gemfile").exists() and shutil.which("bundle"):
        r = _run(["bundle", "install"], cwd=str(root))
        results.append({"manager": "bundler", **r})
        if r["returncode"] == 0:
            installed.append("bundler")

    # Rust
    if (root / "Cargo.toml").exists() and shutil.which("cargo"):
        r = _run(["cargo", "fetch"], cwd=str(root))
        results.append({"manager": "cargo", **r})
        if r["returncode"] == 0:
            installed.append("cargo")

    # Go
    if (root / "go.mod").exists() and shutil.which("go"):
        r = _run(["go", "mod", "download"], cwd=str(root))
        results.append({"manager": "go", **r})
        if r["returncode"] == 0:
            installed.append("go")

    if not results:
        return {"status": "nothing_to_install", "path": path, "message": "No recognized dependency manifest found."}

    all_ok = all(r["returncode"] == 0 for r in results)
    return {
        "status": "ok" if all_ok else "partial",
        "path": path,
        "installed": installed,
        "results": results,
    }


def create_installer(path: str, output: str, platform: str = "zip", **kwargs) -> dict:
    """Create a distributable installer for the project at *path*.

    Supported *platform* values:
    - ``zip``   — ZIP archive of the project (all platforms, default)
    - ``tar``   — gzip-compressed tar archive
    """
    root = Path(path)
    if not root.is_dir():
        return {"status": "error", "error": f"Source directory not found: {path}"}

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    plat = platform.lower()

    if plat == "zip":
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file in sorted(root.rglob("*")):
                if file.is_file():
                    zf.write(file, file.relative_to(root))
        kind = "zip"
    elif plat == "tar":
        import tarfile
        with tarfile.open(out_path, "w:gz") as tf:
            tf.add(root, arcname=root.name)
        kind = "tar.gz"
    else:
        return {"status": "error", "error": f"Unsupported platform: {platform}. Use 'zip' or 'tar'."}

    size = out_path.stat().st_size
    checksum = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return {
        "status": "ok",
        "installer": str(out_path),
        "kind": kind,
        "size_bytes": size,
        "sha256": checksum,
    }


def verify_install(path: str, **kwargs) -> dict:
    """Verify that a project directory has its required dependencies installed.

    Checks:
    - Python: imports all packages listed in ``requirements.txt``
    - Node.js: ``node_modules/`` directory present next to ``package.json``
    - Rust: ``Cargo.lock`` present
    - Go: ``vendor/`` or module cache present
    """
    root = Path(path)
    if not root.is_dir():
        return {"status": "error", "error": f"Directory not found: {path}"}

    checks: list[dict] = []

    # Python
    req = root / "requirements.txt"
    if req.exists():
        missing = []
        for line in req.read_text().splitlines():
            pkg = line.strip().split("==")[0].split(">=")[0].split("<=")[0].strip()
            if pkg and not pkg.startswith("#"):
                result = subprocess.run(
                    [sys.executable, "-c", f"import {pkg.replace('-', '_')}"],
                    capture_output=True,
                )
                if result.returncode != 0:
                    missing.append(pkg)
        checks.append({"manager": "pip", "ok": len(missing) == 0, "missing": missing})

    # Node.js
    pkg_json = root / "package.json"
    if pkg_json.exists():
        node_modules = root / "node_modules"
        checks.append({"manager": "npm", "ok": node_modules.is_dir()})

    # Rust
    if (root / "Cargo.toml").exists():
        lock = root / "Cargo.lock"
        checks.append({"manager": "cargo", "ok": lock.exists()})

    # Go
    if (root / "go.mod").exists():
        vendor = root / "vendor"
        checks.append({"manager": "go", "ok": vendor.is_dir()})

    if not checks:
        return {"status": "ok", "path": path, "checks": [], "message": "No recognized dependency manifest found."}

    all_ok = all(c["ok"] for c in checks)
    return {"status": "ok" if all_ok else "incomplete", "path": path, "checks": checks}
