#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

SURFACE_VERSION = "PCC-SURFACE-0.1"


class SurfaceError(RuntimeError):
    pass


def resolve_root(raw: str | os.PathLike[str] | None = None) -> Path:
    if raw:
        root = Path(raw).expanduser().resolve()
    else:
        root = Path(__file__).resolve().parents[2]
    if not root.is_dir():
        raise SurfaceError(f"Project root does not exist: {root}")
    return root


@dataclass(frozen=True)
class ContractCommand:
    key: str
    label: str
    risk: str = "unknown"
    program: str = ""
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectContract:
    root: Path
    project_id: str
    name: str
    kind: str
    commands: tuple[ContractCommand, ...] = field(default_factory=tuple)
    gate_keys: tuple[str, ...] = field(default_factory=tuple)
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def load(cls, root: Path) -> "ProjectContract":
        path = root / "project.control.json"
        if not path.is_file():
            raise SurfaceError(f"Missing project.control.json: {path}")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        project = data.get("project") or {}
        commands: list[ContractCommand] = []
        for item in data.get("commands", []) or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            commands.append(
                ContractCommand(
                    key=key,
                    label=str(item.get("label") or key),
                    risk=str(item.get("risk") or "unknown"),
                    program=str(item.get("program") or ""),
                    args=tuple(str(x) for x in (item.get("args") or [])),
                )
            )
        gate_keys = tuple(
            str(item.get("key"))
            for item in (data.get("quality_gates") or [])
            if isinstance(item, dict) and item.get("key")
        )
        return cls(
            root=root,
            project_id=str(project.get("id") or root.name).strip(),
            name=str(project.get("name") or root.name).strip(),
            kind=str(project.get("kind") or "project").strip(),
            commands=tuple(commands),
            gate_keys=gate_keys,
            raw=data,
        )

    @property
    def command_keys(self) -> set[str]:
        return {item.key for item in self.commands}


class BackendClient:
    """Thin client for the authoritative project-side PCC provider.

    The operator surfaces do not implement build/Git/update policy themselves. They invoke
    the existing machine-facing PCC authority and render its results. This keeps GUI, CLI,
    Cortex and automation on one execution path.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.script = self._resolve_provider_script()

    def _resolve_provider_script(self) -> Path:
        # Current Cortex authority. A future universal PCC contract can declare this path;
        # keeping provider discovery isolated here avoids hard-wiring it throughout the UI.
        candidates = [
            self.root / "tools" / "control" / "CortexPCC.py",
        ]
        for path in candidates:
            if path.is_file():
                return path
        raise SurfaceError(
            "No supported machine-facing PCC provider was found. Expected "
            "tools/control/CortexPCC.py for this Cortex transition build."
        )

    def argv(self, command: str, extra: Sequence[str] = ()) -> list[str]:
        return [sys.executable, str(self.script), command, "--root", str(self.root), *map(str, extra)]

    def run(self, command: str, extra: Sequence[str] = (), *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.argv(command, extra),
            cwd=str(self.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def status(self) -> dict[str, Any]:
        cp = self.run("status-json", timeout=90)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout).strip()
            raise SurfaceError(f"PCC status failed with exit {cp.returncode}: {detail[-1500:]}")
        text = cp.stdout.strip().splitlines()
        if not text:
            raise SurfaceError("PCC status returned no JSON payload.")
        try:
            return json.loads(text[-1])
        except json.JSONDecodeError as exc:
            raise SurfaceError(f"PCC status returned invalid JSON: {exc}") from exc

    def popen(self, command: str, extra: Sequence[str] = ()) -> subprocess.Popen[str]:
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(
            self.argv(command, extra),
            cwd=str(self.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )


def terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        else:
            proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def open_path(path: Path) -> None:
    target = path.resolve()
    if not target.exists():
        # Operator shortcuts under artifacts are safe to materialize as directories;
        # file-like targets fall back to their nearest existing parent.
        if target.suffix:
            target = target.parent
        else:
            target.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener:
        subprocess.Popen([opener, str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal_file(path: Path) -> None:
    path = path.resolve()
    if os.name == "nt" and path.exists():
        subprocess.Popen(["explorer.exe", f"/select,{path}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    open_path(path.parent if path.parent.exists() else path)


def latest_debug_bundle(root: Path) -> Path | None:
    pointer = root / "artifacts" / "debug" / "LATEST_DEBUG_BUNDLE.json"
    if pointer.is_file():
        try:
            data = json.loads(pointer.read_text(encoding="utf-8-sig"))
            raw = str(data.get("path") or "").strip()
            if raw:
                path = Path(raw)
                if path.exists():
                    return path
        except Exception:
            pass
    txt = root / "artifacts" / "debug" / "LATEST_DEBUG_BUNDLE.txt"
    if txt.is_file():
        for line in txt.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.startswith("Path="):
                path = Path(line.split("=", 1)[1].strip())
                if path.exists():
                    return path
    return None


def compact_path(path: str | Path, max_chars: int = 92) -> str:
    value = str(path)
    if len(value) <= max_chars:
        return value
    keep = max(12, (max_chars - 3) // 2)
    return value[:keep] + "..." + value[-keep:]


def status_text(value: Any, *, true_text: str = "Ready", false_text: str = "Missing") -> str:
    return true_text if bool(value) else false_text


def validate_surface(root: Path) -> list[str]:
    contract = ProjectContract.load(root)
    backend = BackendClient(root)
    notes = [
        f"contract={contract.project_id}:{contract.kind}",
        f"provider={backend.script.relative_to(root)}",
        f"commands={len(contract.commands)}",
        f"gates={len(contract.gate_keys)}",
    ]
    return notes
