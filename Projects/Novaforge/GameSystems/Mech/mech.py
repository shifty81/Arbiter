"""Novaforge — Mech Suit System stubs.

Defines the component and system stubs for the tiered mech upgrade system.
All classes are documented and typed; implementation is tracked in
roadmap.json → NF4-2 through NF4-6.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# ── Mech Components ───────────────────────────────────────────────────────────

@dataclass
class Reactor:
    """Mech reactor — primary power source; tier gates all other systems.

    NF4-2
    """
    tier: int = 1          # 1–5
    power_output: float = 100.0   # kW; scales with tier
    overloaded: bool = False

    def upgrade(self) -> None:
        """Increase reactor tier by one step (max T5)."""
        if self.tier < 5:
            self.tier += 1
            self.power_output = 100.0 * self.tier
        # TODO NF4-2: broadcast PCGTier event via EventBus


@dataclass
class Armor:
    """Mech plating — affects damage resistance and visual aesthetics.

    NF4-3
    """
    tier: int = 1
    damage_resistance: float = 0.1   # 0.0–1.0; scales with tier

    def upgrade(self) -> None:
        if self.tier < 5:
            self.tier += 1
            self.damage_resistance = 0.1 * self.tier
        # TODO NF4-3: propagate visual changes to exterior conduit textures


@dataclass
class Weapons:
    """Mech weapon hardpoints — count and visual mount geometry scales with tier.

    NF4-4
    """
    tier: int = 1
    hardpoint_count: int = 1

    def upgrade(self) -> None:
        if self.tier < 5:
            self.tier += 1
            self.hardpoint_count = self.tier
        # TODO NF4-4: update exterior weapon mounts and LCD overlays


@dataclass
class Cockpit:
    """Mech cockpit interior aesthetics — LCD panels, pipes, conduits, lighting.

    NF4-5
    """
    tier: int = 1
    lcd_panel_count: int = 2
    conduit_density: float = 0.2

    def upgrade(self) -> None:
        if self.tier < 5:
            self.tier += 1
            self.lcd_panel_count = self.tier * 2
            self.conduit_density = 0.2 * self.tier
        # TODO NF4-5: re-generate cockpit interior via PCG


@dataclass
class PilotedState:
    """Tracks whether a player is currently piloting this mech.

    NF4-6
    """
    is_piloted: bool = False
    pilot_entity_id: int = 0   # EntityId of the piloting player, 0 = none


# ── Mech Entity Assembler ─────────────────────────────────────────────────────

def create_mech(world: "Any") -> int:
    """Create a fully equipped mech entity in *world* with default T1 components.

    Returns the new entity's ID.
    """
    from Core.ECS import Transform, PCGTier
    eid = world.entities.create()
    world.entities.add_component(eid, Transform())
    world.entities.add_component(eid, PCGTier(tier=1))
    world.entities.add_component(eid, Reactor())
    world.entities.add_component(eid, Armor())
    world.entities.add_component(eid, Weapons())
    world.entities.add_component(eid, Cockpit())
    world.entities.add_component(eid, PilotedState())
    return eid
