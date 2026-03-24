"""Novaforge — Atlas Core + ECS: stub entry points.

This module defines the foundational Entity-Component-System architecture
for the Novaforge game engine.  It is a scaffold / stub — all types and
methods are documented and typed but contain minimal implementation.

Full implementation is tracked in roadmap.json → NF4-1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Set, Type, TypeVar

T = TypeVar("T")

# ── Entity ────────────────────────────────────────────────────────────────────

EntityId = int


class EntityManager:
    """Create and destroy entities; assign / remove components."""

    def __init__(self) -> None:
        self._next_id: EntityId = 1
        self._alive: Set[EntityId] = set()
        self._components: Dict[EntityId, Dict[str, Any]] = {}

    def create(self) -> EntityId:
        eid = self._next_id
        self._next_id += 1
        self._alive.add(eid)
        self._components[eid] = {}
        return eid

    def destroy(self, eid: EntityId) -> None:
        self._alive.discard(eid)
        self._components.pop(eid, None)

    def is_alive(self, eid: EntityId) -> bool:
        return eid in self._alive

    def add_component(self, eid: EntityId, component: Any) -> None:
        key = type(component).__name__
        self._components[eid][key] = component

    def get_component(self, eid: EntityId, comp_type: Type[T]) -> Optional[T]:
        return self._components.get(eid, {}).get(comp_type.__name__)

    def remove_component(self, eid: EntityId, comp_type: Type) -> None:
        self._components.get(eid, {}).pop(comp_type.__name__, None)

    def query(self, *comp_types: Type) -> Iterator[EntityId]:
        """Yield all alive entities that have every requested component type."""
        keys = {ct.__name__ for ct in comp_types}
        for eid in list(self._alive):
            if keys.issubset(self._components.get(eid, {}).keys()):
                yield eid


# ── Core Components ───────────────────────────────────────────────────────────

@dataclass
class Transform:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rot_x: float = 0.0
    rot_y: float = 0.0
    rot_z: float = 0.0
    scale: float = 1.0


@dataclass
class PCGTier:
    """Drives PCG complexity and visual propagation. Tier 1–5."""
    tier: int = 1

    @property
    def complexity(self) -> float:
        """Normalised complexity value in [0.0, 1.0]."""
        return max(0.0, min(1.0, (self.tier - 1) / 4.0))


@dataclass
class RenderMesh:
    mesh_id: str = ""
    material_id: str = ""
    visible: bool = True


# ── System Scheduler ──────────────────────────────────────────────────────────

class System:
    """Base class for all ECS systems."""

    def update(self, world: "World", delta: float) -> None:
        raise NotImplementedError


class SystemScheduler:
    def __init__(self) -> None:
        self._systems: List[System] = []

    def register(self, system: System) -> None:
        self._systems.append(system)

    def tick(self, world: "World", delta: float) -> None:
        for system in self._systems:
            system.update(world, delta)


# ── Event Bus ─────────────────────────────────────────────────────────────────

class EventBus:
    def __init__(self) -> None:
        self._handlers: Dict[str, List[Any]] = {}

    def subscribe(self, event_type: str, handler: Any) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event_type: str, **kwargs: Any) -> None:
        for handler in self._handlers.get(event_type, []):
            handler(**kwargs)


# ── World ─────────────────────────────────────────────────────────────────────

class World:
    """Top-level ECS container."""

    def __init__(self) -> None:
        self.entities = EntityManager()
        self.scheduler = SystemScheduler()
        self.events = EventBus()

    def tick(self, delta: float = 0.016) -> None:
        self.scheduler.tick(self, delta)
