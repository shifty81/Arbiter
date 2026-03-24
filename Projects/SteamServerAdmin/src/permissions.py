"""SteamServerAdmin — Role-Based Permission System.

SSA2-1  Four-tier model: Admin → Moderator → Operator → Standard
SSA2-2  Per-server role configs persisted to  config/permissions/<server_id>.json
SSA2-3  Dynamic restriction: reload role map without server restart
SSA2-4  Whitelist management: Admin-only; add/remove; live updates
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.logger import get_ssa_logger

logger = get_ssa_logger("permissions")

# ── Permission tier definitions ───────────────────────────────────────────────

# Ordered highest → lowest privilege
ROLE_HIERARCHY: List[str] = ["admin", "moderator", "operator", "standard"]

# Actions exclusively owned by each role level (non-cumulative at definition).
# _effective_actions() adds all LOWER-privilege tiers so higher roles are
# strictly supersets of everything below them.
ROLE_ACTIONS: Dict[str, Set[str]] = {
    "admin": {
        "all",
        "roles.manage",
        "whitelist.manage",
    },
    "moderator": {
        "ban",
        "kick",
        "server.rcon",
        "audit.read",
    },
    "operator": {
        "server.start",
        "server.stop",
        "server.restart",
        "server.update",
    },
    "standard": {
        "status.read",
    },
}


# Pre-computed index for O(1) role lookups
_ROLE_INDEX: Dict[str, int] = {r: i for i, r in enumerate(ROLE_HIERARCHY)}


def _effective_actions(role: str) -> Set[str]:
    """Return the union of all actions permitted for *role* and every tier
    below it (role is cumulative / hierarchical).

    Because ROLE_HIERARCHY is ordered highest→lowest privilege, a role at
    index *i* inherits actions from roles at indices *i* through the end.
    """
    idx = _ROLE_INDEX.get(role, len(ROLE_HIERARCHY))
    combined: Set[str] = set()
    for r in ROLE_HIERARCHY[idx:]:   # current level + all less-privileged tiers
        combined |= ROLE_ACTIONS.get(r, set())
    return combined


# ── Per-server role registry ──────────────────────────────────────────────────

_SSA_ROOT = Path(__file__).resolve().parent.parent
_PERM_DIR = _SSA_ROOT / "config" / "permissions"


def _perm_file(server_id: str) -> Path:
    _PERM_DIR.mkdir(parents=True, exist_ok=True)
    return _PERM_DIR / f"{server_id}.json"


def _default_perm_data() -> Dict[str, Any]:
    return {"roles": {}, "whitelist": []}


class PermissionRegistry:
    """Thread-safe, per-server role and whitelist registry.

    State is persisted to ``config/permissions/<server_id>.json`` and can be
    reloaded at any time without restarting the server process (SSA2-3).
    """

    def __init__(self, server_id: str) -> None:
        self.server_id = server_id
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = _default_perm_data()
        self.load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def load(self) -> None:
        """Reload roles and whitelist from disk (SSA2-3 dynamic reload)."""
        path = _perm_file(self.server_id)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                with self._lock:
                    self._data = raw
                logger.debug("[%s] Permissions loaded from %s", self.server_id, path)
            except Exception as exc:
                logger.error("[%s] Failed to load permissions: %s", self.server_id, exc)
        else:
            self.save()  # create default file

    def save(self) -> None:
        path = _perm_file(self.server_id)
        with self._lock:
            data = dict(self._data)
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("[%s] Failed to save permissions: %s", self.server_id, exc)

    # ── Role management (SSA2-1 / SSA2-2) ────────────────────────────────────

    def get_role(self, identity: str) -> Optional[str]:
        """Return the role assigned to *identity* (Steam ID or username)."""
        with self._lock:
            return self._data["roles"].get(identity)

    def set_role(self, identity: str, role: str) -> None:
        """Assign *role* to *identity*.  Raises ``ValueError`` for unknown roles."""
        role = role.lower()
        if role not in ROLE_HIERARCHY:
            raise ValueError(f"Unknown role '{role}'. Valid: {ROLE_HIERARCHY}")
        with self._lock:
            self._data["roles"][identity] = role
        self.save()
        logger.info("[%s] Role set: %s → %s", self.server_id, identity, role)

    def remove_role(self, identity: str) -> Optional[str]:
        """Remove *identity*'s role assignment.  Returns the removed role or None."""
        with self._lock:
            removed = self._data["roles"].pop(identity, None)
        if removed is not None:
            self.save()
            logger.info("[%s] Role removed: %s (was %s)", self.server_id, identity, removed)
        return removed

    def list_roles(self) -> Dict[str, str]:
        """Return a copy of all identity → role assignments."""
        with self._lock:
            return dict(self._data["roles"])

    # ── Authorisation check ───────────────────────────────────────────────────

    def can(self, identity: str, action: str) -> bool:
        """Return True if *identity* is permitted to perform *action*."""
        role = self.get_role(identity)
        if role is None:
            # No role → only 'status.read' allowed (anonymous access)
            return action == "status.read"
        actions = _effective_actions(role)
        return "all" in actions or action in actions

    def require(self, identity: str, action: str) -> None:
        """Raise ``PermissionError`` if *identity* cannot perform *action*."""
        if not self.can(identity, action):
            role = self.get_role(identity) or "anonymous"
            raise PermissionError(
                f"'{identity}' (role={role}) is not permitted to '{action}' "
                f"on server '{self.server_id}'"
            )

    # ── Whitelist management (SSA2-4) ─────────────────────────────────────────

    def get_whitelist(self) -> List[str]:
        with self._lock:
            return list(self._data["whitelist"])

    def whitelist_add(self, identity: str, actor: str) -> bool:
        """Add *identity* to the whitelist.  *actor* must be an Admin."""
        self.require(actor, "whitelist.manage")
        with self._lock:
            wl: list = self._data["whitelist"]
            if identity in wl:
                return False
            wl.append(identity)
        self.save()
        logger.info("[%s] Whitelist add: %s (by %s)", self.server_id, identity, actor)
        return True

    def whitelist_remove(self, identity: str, actor: str) -> bool:
        """Remove *identity* from the whitelist.  *actor* must be an Admin."""
        self.require(actor, "whitelist.manage")
        with self._lock:
            wl: list = self._data["whitelist"]
            if identity not in wl:
                return False
            wl.remove(identity)
        self.save()
        logger.info("[%s] Whitelist remove: %s (by %s)", self.server_id, identity, actor)
        return True

    def is_whitelisted(self, identity: str) -> bool:
        """Return True if the whitelist is empty (open server) or *identity* is listed."""
        wl = self.get_whitelist()
        return len(wl) == 0 or identity in wl

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of all permissions and the whitelist."""
        with self._lock:
            roles_snapshot = dict(self._data["roles"])
            whitelist_snapshot = list(self._data["whitelist"])
        return {
            "server_id": self.server_id,
            "roles":     roles_snapshot,
            "whitelist": whitelist_snapshot,
            "hierarchy": ROLE_HIERARCHY,
            "actions_map": {r: sorted(ROLE_ACTIONS.get(r, set())) for r in ROLE_HIERARCHY},
        }


# ── Global registry manager ───────────────────────────────────────────────────

class PermissionManager:
    """Manages a PermissionRegistry instance per server ID."""

    def __init__(self) -> None:
        self._registries: Dict[str, PermissionRegistry] = {}
        self._lock = threading.Lock()

    def get(self, server_id: str) -> PermissionRegistry:
        """Return (and lazily create) the registry for *server_id*."""
        with self._lock:
            if server_id not in self._registries:
                self._registries[server_id] = PermissionRegistry(server_id)
            return self._registries[server_id]

    def reload_all(self) -> None:
        """Hot-reload permissions for all registered servers (SSA2-3)."""
        with self._lock:
            for reg in self._registries.values():
                reg.load()
        logger.info("[PermissionManager] All server permissions reloaded from disk")

    def list_servers(self) -> List[str]:
        with self._lock:
            return list(self._registries.keys())


# Singleton instance used by the rest of SSA
permission_manager = PermissionManager()
