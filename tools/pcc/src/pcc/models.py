from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandSpec:
    key: str
    label: str
    program: str
    args: tuple[str, ...] = ()
    risk: str = "read_only"
    side_effects: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    network_required: bool = False
    cancellation: str = "bounded_kill"
    rollback: str = "none"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CommandSpec":
        return cls(
            key=str(value["key"]),
            label=str(value.get("label") or value["key"]),
            program=str(value["program"]),
            args=tuple(str(v) for v in value.get("args", [])),
            risk=str(value.get("risk", "read_only")),
            side_effects=tuple(str(v) for v in value.get("side_effects", [])),
            permissions=tuple(str(v) for v in value.get("permissions", [])),
            network_required=bool(value.get("network_required", False)),
            cancellation=str(value.get("cancellation", "bounded_kill")),
            rollback=str(value.get("rollback", "none")),
        )


@dataclass(frozen=True)
class GateSpec:
    key: str
    label: str
    stages: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GateSpec":
        return cls(
            key=str(value["key"]),
            label=str(value.get("label") or value["key"]),
            stages=tuple(str(v) for v in value.get("stages", [])),
        )


@dataclass
class ProjectControl:
    root: Path
    raw: dict[str, Any]
    commands: dict[str, CommandSpec] = field(default_factory=dict)
    gates: dict[str, GateSpec] = field(default_factory=dict)

    @property
    def project(self) -> dict[str, Any]:
        return dict(self.raw.get("project") or {})

    @property
    def requirements(self) -> list[dict[str, Any]]:
        return list(self.raw.get("requirements") or [])

    @classmethod
    def from_dict(cls, root: Path, value: dict[str, Any]) -> "ProjectControl":
        commands = {
            spec.key: spec
            for spec in (CommandSpec.from_dict(v) for v in value.get("commands", []))
        }
        gates = {
            spec.key: spec
            for spec in (GateSpec.from_dict(v) for v in value.get("quality_gates", []))
        }
        return cls(root=root, raw=value, commands=commands, gates=gates)
