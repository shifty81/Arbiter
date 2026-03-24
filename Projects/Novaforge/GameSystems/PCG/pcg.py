"""Novaforge — Procedural Content Generation stubs.

Defines the PCG pipeline stages and generation targets.
Implementation tracked in roadmap.json → NF4-7 through NF4-9.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PCGTarget(str, Enum):
    ROOM_INTERIOR = "room_interior"
    MECH_COCKPIT  = "mech_cockpit"
    BASE_EXTERIOR = "base_exterior"


@dataclass
class PCGRequest:
    """Input to the PCG pipeline."""
    target: PCGTarget
    complexity: float        # 0.0–1.0 derived from mech tier
    seed: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PCGResult:
    """Output from the PCG pipeline."""
    target: PCGTarget
    complexity: float
    modules: List[str] = field(default_factory=list)   # asset module IDs placed
    props: List[str]   = field(default_factory=list)   # secondary props placed
    error: Optional[str] = None


class ModuleSelector:
    """Select compatible asset modules for the given complexity tier.

    NF4-7
    """
    def select(self, req: PCGRequest) -> List[str]:
        # TODO NF4-7: query asset catalogue filtered by complexity range
        return [f"module_{req.target.value}_t{int(req.complexity * 4) + 1}"]


class LayoutSolver:
    """Solve spatial placement using constraint rules.

    NF4-7
    """
    def solve(self, modules: List[str], req: PCGRequest) -> List[str]:
        # TODO NF4-7: constraint-based tile layout
        return modules


class PropPlacer:
    """Place secondary detail props (pipes, panels, decals).

    NF4-7
    """
    def place(self, layout: List[str], req: PCGRequest) -> List[str]:
        # TODO NF4-7: prop placement rules
        return []


class PCGEngine:
    """Top-level PCG orchestrator.

    Usage::

        engine = PCGEngine()
        result = engine.generate(PCGRequest(
            target=PCGTarget.MECH_COCKPIT,
            complexity=0.6,
            seed=42,
        ))
    """

    def __init__(self) -> None:
        self._selector = ModuleSelector()
        self._solver   = LayoutSolver()
        self._placer   = PropPlacer()

    def generate(self, req: PCGRequest) -> PCGResult:
        modules = self._selector.select(req)
        layout  = self._solver.solve(modules, req)
        props   = self._placer.place(layout, req)
        return PCGResult(
            target=req.target,
            complexity=req.complexity,
            modules=layout,
            props=props,
        )

    def on_tier_change(self, mech_tier: int) -> PCGRequest:
        """Build a PCGRequest for a mech tier change event.

        NF4-9: Upgrade tier drives generation complexity.
        """
        from Core.ECS import PCGTier
        tier_comp = PCGTier(tier=mech_tier)
        return PCGRequest(
            target=PCGTarget.MECH_COCKPIT,
            complexity=tier_comp.complexity,
        )
