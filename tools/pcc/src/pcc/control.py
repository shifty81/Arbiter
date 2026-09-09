from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .models import CommandSpec, ProjectControl


CONTROL_FILE = "project.control.json"


def load_project(root: str | os.PathLike[str]) -> ProjectControl:
    project_root = Path(root).resolve()
    path = project_root / CONTROL_FILE
    if not path.is_file():
        raise FileNotFoundError(f"{CONTROL_FILE} not found under {project_root}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{CONTROL_FILE} must contain a JSON object")
    return ProjectControl.from_dict(project_root, value)


def resolve_program(program: str) -> str | None:
    candidate = Path(program)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return str(candidate) if candidate.exists() else None
    return shutil.which(program)


def requirement_status(control: ProjectControl) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for requirement in control.requirements:
        tool = str(requirement.get("tool") or "").strip()
        if not tool:
            continue
        resolved = resolve_program(tool)
        output.append(
            {
                "tool": tool,
                "required": bool(requirement.get("required", False)),
                "ready": resolved is not None,
                "resolved": resolved,
            }
        )
    return output


def status(control: ProjectControl) -> dict[str, Any]:
    requirements = requirement_status(control)
    required_missing = [r["tool"] for r in requirements if r["required"] and not r["ready"]]
    return {
        "schema": "pcc.status.v1",
        "project_root": str(control.root),
        "project": control.project,
        "command_count": len(control.commands),
        "gate_count": len(control.gates),
        "requirements": requirements,
        "ready": not required_missing,
        "required_missing": required_missing,
    }


def command_catalog(control: ProjectControl) -> list[dict[str, Any]]:
    return [asdict(control.commands[key]) for key in sorted(control.commands)]


def _artifact_log_path(control: ProjectControl, key: str) -> Path:
    root = control.root / "artifacts" / "logs" / "pcc"
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
    return root / f"{stamp}_{safe}.log"


def run_command(
    control: ProjectControl,
    key: str,
    *,
    allow_mutation: bool = False,
    stream: bool = True,
) -> dict[str, Any]:
    if key not in control.commands:
        raise KeyError(f"unknown PCC command: {key}")
    spec: CommandSpec = control.commands[key]
    if spec.risk != "read_only" and not allow_mutation:
        raise PermissionError(
            f"PCC command '{key}' is risk={spec.risk}; rerun with mutation explicitly allowed"
        )
    program = resolve_program(spec.program)
    if not program:
        raise FileNotFoundError(f"program for PCC command '{key}' was not found: {spec.program}")

    argv = [program, *spec.args]
    log_path = _artifact_log_path(control, key)
    started = time.time()
    lines: list[str] = []
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        log.write(f"PCC COMMAND {key}\n")
        log.write(f"cwd={control.root}\n")
        log.write(f"argv={json.dumps(argv)}\n")
        log.flush()
        with subprocess.Popen(
            argv,
            cwd=control.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                text = line.rstrip("\r\n")
                lines.append(text)
                log.write(text + "\n")
                log.flush()
                if stream:
                    print(text, flush=True)
            code = process.wait()
    finished = time.time()
    return {
        "schema": "pcc.command_result.v1",
        "key": key,
        "label": spec.label,
        "risk": spec.risk,
        "argv": argv,
        "cwd": str(control.root),
        "exit_code": code,
        "success": code == 0,
        "duration_ms": int((finished - started) * 1000),
        "log_path": str(log_path),
        "tail": lines[-120:],
    }


SAFE_GATE_MUTATION_SIDE_EFFECTS = frozenset({
    "artifacts",
    "build_outputs",
    "cache",
    "logs",
    "temporary_files",
})


def _gate_stage_allowed(spec: CommandSpec) -> bool:
    if spec.risk == "read_only":
        return True
    if spec.risk != "local_mutation":
        return False
    return set(spec.side_effects).issubset(SAFE_GATE_MUTATION_SIDE_EFFECTS)


def run_gate(control: ProjectControl, key: str, *, stream: bool = True) -> dict[str, Any]:
    if key not in control.gates:
        raise KeyError(f"unknown PCC quality gate: {key}")
    gate = control.gates[key]
    results: list[dict[str, Any]] = []
    for stage in gate.stages:
        if stage not in control.commands:
            raise KeyError(f"quality gate '{key}' references unknown PCC command: {stage}")
        spec = control.commands[stage]
        if not _gate_stage_allowed(spec):
            effects = ", ".join(spec.side_effects) if spec.side_effects else "unspecified"
            raise PermissionError(
                f"quality gate '{key}' cannot execute '{stage}': "
                f"risk={spec.risk}, side_effects={effects}. "
                "Gates may only run read-only checks or bounded build/cache/artifact/log mutations."
            )
        result = run_command(
            control,
            stage,
            allow_mutation=spec.risk != "read_only",
            stream=stream,
        )
        results.append(result)
        if not result["success"]:
            break
    return {
        "schema": "pcc.gate_result.v1",
        "key": gate.key,
        "label": gate.label,
        "success": len(results) == len(gate.stages) and all(r["success"] for r in results),
        "stages": results,
    }


def discover(roots: Iterable[str], max_depth: int = 5) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[Path] = set()
    ignore = {".git", "target", "node_modules", ".venv", "venv", "artifacts", "build", "dist"}
    for raw_root in roots:
        scan_root = Path(raw_root).resolve()
        if not scan_root.exists():
            continue
        queue: list[tuple[Path, int]] = [(scan_root, 0)]
        while queue:
            current, depth = queue.pop(0)
            try:
                resolved = current.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            control_path = current / CONTROL_FILE
            if control_path.is_file():
                try:
                    control = load_project(current)
                    found.append({
                        "root": str(current),
                        "project": control.project,
                        "commands": len(control.commands),
                        "gates": len(control.gates),
                    })
                except Exception as exc:  # discovery should report malformed projects, not abort
                    found.append({"root": str(current), "error": str(exc)})
                continue
            if depth >= max_depth:
                continue
            try:
                children = [p for p in current.iterdir() if p.is_dir() and p.name not in ignore]
            except OSError:
                continue
            queue.extend((child, depth + 1) for child in children)
    found.sort(key=lambda row: row["root"].lower())
    return found
