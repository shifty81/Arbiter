#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import hashlib
from datetime import datetime, timezone
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


@dataclass(frozen=True)
class RegisteredProject:
    registry_id: str
    project_id: str
    name: str
    kind: str
    root: Path
    last_opened_utc: str = ""


class ProjectRegistry:
    SCHEMA = "pcc.project_registry.v1"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def default_path() -> Path:
        env = os.environ.get("PCC_PROJECT_REGISTRY")
        if env:
            return Path(env).expanduser().resolve()
        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            return base / "ProjectControlCenter" / "project_registry.json"
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        return base / "project-control-center" / "project_registry.json"

    @staticmethod
    def _registry_id(root: Path) -> str:
        key = os.path.normcase(str(root.resolve()))
        return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schema": self.SCHEMA, "projects": [], "activeProject": ""}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise SurfaceError(f"Project registry is unreadable: {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise SurfaceError(f"Project registry root must be an object: {self.path}")
        data.setdefault("schema", self.SCHEMA)
        data.setdefault("projects", [])
        data.setdefault("activeProject", "")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.path)

    def entries(self) -> list[RegisteredProject]:
        data = self._read()
        rows: list[RegisteredProject] = []
        for item in data.get("projects", []) or []:
            if not isinstance(item, dict):
                continue
            raw_root = str(item.get("root") or "").strip()
            if not raw_root:
                continue
            root = Path(raw_root).expanduser()
            rows.append(RegisteredProject(
                registry_id=str(item.get("registryId") or self._registry_id(root)),
                project_id=str(item.get("projectId") or root.name),
                name=str(item.get("name") or root.name),
                kind=str(item.get("kind") or "project"),
                root=root,
                last_opened_utc=str(item.get("lastOpenedUtc") or ""),
            ))
        rows.sort(key=lambda x: (x.name.lower(), str(x.root).lower()))
        return rows

    def active_registry_id(self) -> str:
        return str(self._read().get("activeProject") or "")

    def register(self, root: Path, *, make_active: bool = False) -> RegisteredProject:
        root = root.expanduser().resolve()
        contract = ProjectContract.load(root)
        rid = self._registry_id(root)
        now = datetime.now(timezone.utc).isoformat()
        data = self._read()
        projects = [x for x in (data.get("projects") or []) if isinstance(x, dict)]
        record = {
            "registryId": rid,
            "projectId": contract.project_id,
            "name": contract.name,
            "kind": contract.kind,
            "root": str(root),
            "lastOpenedUtc": now if make_active else "",
        }
        found = False
        for i, item in enumerate(projects):
            if str(item.get("registryId") or "") == rid or os.path.normcase(str(item.get("root") or "")) == os.path.normcase(str(root)):
                previous = str(item.get("lastOpenedUtc") or "")
                if not make_active:
                    record["lastOpenedUtc"] = previous
                projects[i] = record
                found = True
                break
        if not found:
            projects.append(record)
        data["projects"] = projects
        if make_active:
            data["activeProject"] = rid
        self._write(data)
        return RegisteredProject(rid, contract.project_id, contract.name, contract.kind, root, str(record["lastOpenedUtc"]))

    def touch(self, root: Path) -> RegisteredProject:
        return self.register(root, make_active=True)

    def remove(self, registry_id: str) -> None:
        data = self._read()
        data["projects"] = [x for x in (data.get("projects") or []) if not (isinstance(x, dict) and str(x.get("registryId") or "") == registry_id)]
        if str(data.get("activeProject") or "") == registry_id:
            data["activeProject"] = ""
        self._write(data)


class BackendClient:
    """Thin client for the authoritative project-side PCC provider.

    The operator surfaces do not implement build/Git/update policy themselves. They invoke
    the existing machine-facing PCC authority and render its results. This keeps GUI, CLI,
    Cortex and automation on one execution path.
    """

    def __init__(self, root: Path, contract: ProjectContract | None = None) -> None:
        self.root = root
        self.contract = contract or ProjectContract.load(root)
        self.script = self._resolve_provider_script()

    def _resolve_provider_script(self) -> Path:
        control = self.contract.raw.get("root_control_center") or {}
        declared = str(control.get("machine_provider") or control.get("python_entrypoint") or "").strip()
        candidates: list[Path] = []
        if declared:
            candidates.append((self.root / declared).resolve())
        candidates.extend([
            self.root / "tools" / "control" / "ProjectControlCenter.py",
            self.root / "tools" / "control" / "CortexPCC.py",
            self.root / "tools" / "pcc" / "ProjectControlCenter.py",
        ])
        for path in candidates:
            if path.is_file():
                return path
        raise SurfaceError(
            "This project is registered but does not yet expose a standardized Python PCC machine provider. "
            "Standardize its project adapter before running project operations from the universal GUI."
        )

    def argv(self, command: str, extra: Sequence[str] = ()) -> list[str]:
        return [sys.executable, str(self.script), command, "--root", str(self.root), *map(str, extra)]

    @staticmethod
    def _embedded_creationflags(*, process_group: bool = False) -> int:
        """Keep project commands embedded in the GUI on Windows.

        The universal PCC captures stdout/stderr itself, so child console programs must not
        allocate transient Windows console windows when the operator launched the GUI through
        pythonw.exe.  CREATE_NO_WINDOW preserves the captured pipes while preventing the
        distracting flash of cargo/git/python command consoles.
        """
        if os.name != "nt":
            return 0
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if process_group:
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return flags

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
            creationflags=self._embedded_creationflags(),
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
            creationflags=self._embedded_creationflags(process_group=True),
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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
