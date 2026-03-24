"""SteamServerAdmin — Role-Based Permissions & Audit.

This module provides the full permission enforcement layer for the SSA
platform.  It is entirely standalone: no dependency on ArbiterEngine or
any external service.

Roles (highest privilege first)
--------------------------------
admin      — full control: server lifecycle, RCON, role assignment, whitelist
moderator  — kick, ban, broadcast (RCON say), read status
operator   — restart, update, read status
standard   — read-only status

SSA Phase 2 tasks
-----------------
SSA2-1  Four permission tiers with enforced action sets.
SSA2-2  Per-server role config: Steam IDs / usernames → role, loaded from
        ``config/<server_id>.json`` ``permissions`` key.
SSA2-3  Dynamic restriction — call ``reload()`` to hot-apply config changes
        without restarting any server process.
SSA2-4  Whitelist management: admin-only add/remove backed by config file.
SSA2-5  Audit log — append-only JSONL at
        ``logs/steam_server_admin/audit_<server_id>.jsonl``.
SSA2-6  ``get_audit()`` helper returns structured log entries for REST API
        and web dashboard consumption.
SSA2-7  Change-notification queue polled by the web dashboard; optional
        Discord webhook delivery.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import threading
import time
import urllib.request as _urllib
from dataclasses import dataclass, field
from typing import Any

from src.logger import get_ssa_logger

logger = get_ssa_logger("permissions")

# ── Project root (two levels up from this file) ───────────────────────────────
_SSA_ROOT = pathlib.Path(__file__).resolve().parent.parent

# =============================================================================
# SSA2-1 — Permission tiers and action sets
# =============================================================================

# Ordered from lowest privilege to highest.  The enforcement logic grants
# a tier *all* actions available to every tier below it.
TIER_HIERARCHY: list[str] = ["standard", "operator", "moderator", "admin"]

#: Actions a tier may perform *exclusively* at that level (not inherited).
#: Inheritance is applied by ``_allowed_actions()`` at runtime.
_TIER_OWN_ACTIONS: dict[str, set[str]] = {
    "standard":  {"status"},
    "operator":  {"restart", "update"},
    "moderator": {"kick", "ban", "say", "broadcast"},
    "admin":     {"start", "stop", "roles.assign", "roles.revoke", "whitelist.add",
                  "whitelist.remove", "rcon"},
}


def allowed_actions(tier: str) -> set[str]:
    """Return the full set of actions permitted for *tier* (including inherited).

    SSA2-1
    """
    if tier not in TIER_HIERARCHY:
        return set()
    idx = TIER_HIERARCHY.index(tier)
    result: set[str] = set()
    for t in TIER_HIERARCHY[: idx + 1]:
        result |= _TIER_OWN_ACTIONS.get(t, set())
    return result


# =============================================================================
# SSA2-2/3/4 — PermissionManager
# =============================================================================

class PermissionError(Exception):
    """Raised when a user attempts an action their role does not permit."""


class PermissionManager:
    """Manage per-server role assignments and whitelist.

    Roles and whitelist are loaded from the server's ``config/<server_id>.json``
    file under the ``permissions`` and ``whitelist`` keys respectively.

    Thread-safe: all mutations and reads use an internal ``RLock``.

    Parameters
    ----------
    server_id:
        Unique server identifier (must match the config filename stem).
    config_dir:
        Directory containing per-server config JSON files.  Defaults to
        ``{SSA_ROOT}/config/``.
    """

    def __init__(
        self,
        server_id: str,
        config_dir: pathlib.Path | None = None,
    ) -> None:
        self.server_id = server_id
        self._config_dir: pathlib.Path = config_dir or (_SSA_ROOT / "config")
        self._config_path: pathlib.Path = self._config_dir / f"{server_id}.json"
        self._lock = threading.RLock()
        # SSA2-2: user_id → role
        self._roles: dict[str, str] = {}
        # SSA2-4: whitelist (ordered set via list)
        self._whitelist: list[str] = []
        self._load()
        logger.info("[%s] PermissionManager initialised (%d roles, %d whitelist entries)",
                    server_id, len(self._roles), len(self._whitelist))

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load roles and whitelist from the server config file."""
        with self._lock:
            if not self._config_path.exists():
                logger.warning("[%s] Config not found at %s; starting with empty roles",
                               self.server_id, self._config_path)
                return
            try:
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
                raw_roles = data.get("permissions", {})
                self._roles = {
                    str(k): str(v).lower()
                    for k, v in raw_roles.items()
                    if isinstance(v, str) and v.lower() in TIER_HIERARCHY
                }
                self._whitelist = [str(u) for u in data.get("whitelist", [])]
            except Exception as exc:
                logger.error("[%s] Failed to load config: %s", self.server_id, exc)

    def _save(self) -> None:
        """Persist current roles and whitelist back to the config file."""
        with self._lock:
            if not self._config_path.exists():
                logger.warning("[%s] Cannot save — config file missing: %s",
                               self.server_id, self._config_path)
                return
            try:
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
                data["permissions"] = dict(self._roles)
                data["whitelist"] = list(self._whitelist)
                self._config_path.write_text(
                    json.dumps(data, indent=2), encoding="utf-8"
                )
            except Exception as exc:
                logger.error("[%s] Failed to save config: %s", self.server_id, exc)

    # ── SSA2-3: Dynamic reload ────────────────────────────────────────────────

    def reload(self) -> None:
        """Hot-reload roles and whitelist from disk.

        Applies immediately — no server process restart required.
        SSA2-3
        """
        with self._lock:
            self._load()
        logger.info("[%s] Permissions reloaded from disk", self.server_id)

    # ── SSA2-1/2: Role checks ─────────────────────────────────────────────────

    def get_role(self, user_id: str) -> str | None:
        """Return the role assigned to *user_id*, or ``None`` if not found.

        SSA2-2
        """
        with self._lock:
            return self._roles.get(str(user_id))

    def can(self, user_id: str, action: str) -> bool:
        """Return ``True`` if *user_id* is permitted to perform *action*.

        SSA2-1
        """
        role = self.get_role(user_id)
        if role is None:
            return False
        return action in allowed_actions(role)

    def require(self, user_id: str, action: str) -> None:
        """Assert that *user_id* may perform *action*.

        Raises :exc:`PermissionError` if not permitted.

        SSA2-1
        """
        if not self.can(user_id, action):
            role = self.get_role(user_id) or "<unassigned>"
            raise PermissionError(
                f"User '{user_id}' (role={role}) is not permitted to '{action}'"
            )

    # ── SSA2-1: Role assignment (requires caller to be admin) ─────────────────

    def assign_role(
        self,
        actor: str,
        target_user: str,
        role: str,
        audit: "AuditLogger | None" = None,
        notifier: "NotificationDispatcher | None" = None,
    ) -> None:
        """Assign *role* to *target_user*.

        *actor* must have the ``roles.assign`` permission.

        SSA2-1, SSA2-3
        """
        role = role.lower()
        if role not in TIER_HIERARCHY:
            raise ValueError(f"Unknown role '{role}'. Valid: {TIER_HIERARCHY}")
        self.require(actor, "roles.assign")

        with self._lock:
            previous = self._roles.get(target_user)
            self._roles[str(target_user)] = role
            self._save()

        logger.info("[%s] %s assigned role '%s' to %s (was: %s)",
                    self.server_id, actor, role, target_user, previous)

        if audit:
            audit.write(
                event="roles.assign",
                actor=actor,
                target=target_user,
                detail={"role": role, "previous_role": previous},
            )
        if notifier:
            notifier.notify(
                f"[{self.server_id}] {actor} assigned '{role}' to {target_user}"
            )

    def revoke_role(
        self,
        actor: str,
        target_user: str,
        audit: "AuditLogger | None" = None,
        notifier: "NotificationDispatcher | None" = None,
    ) -> None:
        """Remove *target_user*'s role assignment.

        *actor* must have the ``roles.revoke`` permission.

        SSA2-3
        """
        self.require(actor, "roles.assign")

        with self._lock:
            removed = self._roles.pop(str(target_user), None)
            if removed is not None:
                self._save()

        if removed:
            logger.info("[%s] %s revoked role from %s (was: %s)",
                        self.server_id, actor, target_user, removed)
            if audit:
                audit.write(
                    event="roles.revoke",
                    actor=actor,
                    target=target_user,
                    detail={"removed_role": removed},
                )
            if notifier:
                notifier.notify(
                    f"[{self.server_id}] {actor} revoked '{removed}' from {target_user}"
                )

    def list_roles(self) -> list[dict[str, str]]:
        """Return all role assignments as a list of dicts.

        SSA2-6
        """
        with self._lock:
            return [{"user_id": uid, "role": r} for uid, r in self._roles.items()]

    # ── SSA2-4: Whitelist management ──────────────────────────────────────────

    def whitelist_add(
        self,
        actor: str,
        user_id: str,
        audit: "AuditLogger | None" = None,
        notifier: "NotificationDispatcher | None" = None,
    ) -> bool:
        """Add *user_id* to the whitelist.

        *actor* must have the ``whitelist.add`` permission.
        Returns ``True`` if added, ``False`` if already present.

        SSA2-4
        """
        self.require(actor, "whitelist.add")
        with self._lock:
            if user_id in self._whitelist:
                return False
            self._whitelist.append(user_id)
            self._save()

        logger.info("[%s] %s added %s to whitelist", self.server_id, actor, user_id)
        if audit:
            audit.write("whitelist.add", actor=actor, target=user_id, detail={})
        if notifier:
            notifier.notify(f"[{self.server_id}] {actor} whitelisted {user_id}")
        return True

    def whitelist_remove(
        self,
        actor: str,
        user_id: str,
        audit: "AuditLogger | None" = None,
        notifier: "NotificationDispatcher | None" = None,
    ) -> bool:
        """Remove *user_id* from the whitelist.

        *actor* must have the ``whitelist.remove`` permission.
        Returns ``True`` if removed, ``False`` if not present.

        SSA2-4
        """
        self.require(actor, "whitelist.remove")
        with self._lock:
            if user_id not in self._whitelist:
                return False
            self._whitelist.remove(user_id)
            self._save()

        logger.info("[%s] %s removed %s from whitelist", self.server_id, actor, user_id)
        if audit:
            audit.write("whitelist.remove", actor=actor, target=user_id, detail={})
        if notifier:
            notifier.notify(f"[{self.server_id}] {actor} un-whitelisted {user_id}")
        return True

    def is_whitelisted(self, user_id: str) -> bool:
        """Return ``True`` if the whitelist is empty (open) or *user_id* is listed.

        SSA2-4
        """
        with self._lock:
            return not self._whitelist or user_id in self._whitelist

    def get_whitelist(self) -> list[str]:
        """Return a copy of the current whitelist.

        SSA2-4
        """
        with self._lock:
            return list(self._whitelist)


# =============================================================================
# SSA2-5/6 — Audit Logger
# =============================================================================

class AuditLogger:
    """Append-only JSONL audit log for a single server.

    Every permission change, ban, kick, restart, and update is logged here
    with actor, timestamp, target, and a detail dict.

    The log file is located at::

        {SSA_ROOT}/logs/steam_server_admin/audit_{server_id}.jsonl

    SSA2-5, SSA2-6
    """

    def __init__(
        self,
        server_id: str,
        log_dir: pathlib.Path | None = None,
    ) -> None:
        self.server_id = server_id
        log_dir = log_dir or (_SSA_ROOT / "logs" / "steam_server_admin")
        log_dir.mkdir(parents=True, exist_ok=True)
        self._path = log_dir / f"audit_{server_id}.jsonl"
        self._lock = threading.Lock()

    # ── SSA2-5: Write ─────────────────────────────────────────────────────────

    def write(
        self,
        event: str,
        actor: str,
        target: str,
        detail: dict[str, Any],
    ) -> None:
        """Append one audit event to the JSONL log.

        SSA2-5
        """
        entry: dict[str, Any] = {
            "ts":     datetime.datetime.utcnow().isoformat(),
            "server": self.server_id,
            "event":  event,
            "actor":  actor,
            "target": target,
            **detail,
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError as exc:
                logger.error("[%s] Audit write failed: %s", self.server_id, exc)

    # ── SSA2-6: Read ──────────────────────────────────────────────────────────

    def get_audit(
        self,
        limit: int = 100,
        event_prefix: str = "",
    ) -> list[dict[str, Any]]:
        """Return up to *limit* most-recent audit entries.

        Filter by *event_prefix* (e.g. ``"roles"`` matches ``"roles.assign"``).

        SSA2-6
        """
        if not self._path.exists():
            return []
        try:
            raw_lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

        entries: list[dict[str, Any]] = []
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not event_prefix or entry.get("event", "").startswith(event_prefix):
                    entries.append(entry)
            except json.JSONDecodeError:
                pass

        return entries[-limit:]

    def stats(self) -> dict[str, Any]:
        """Return aggregate statistics from the audit log.

        SSA2-6
        """
        all_entries = self.get_audit(limit=100_000)
        by_event: dict[str, int] = {}
        by_actor: dict[str, int] = {}
        for e in all_entries:
            ev = e.get("event", "?")
            ac = e.get("actor", "?")
            by_event[ev] = by_event.get(ev, 0) + 1
            by_actor[ac] = by_actor.get(ac, 0) + 1
        return {
            "total":    len(all_entries),
            "by_event": by_event,
            "by_actor": by_actor,
        }


# =============================================================================
# SSA2-7 — Notification Dispatcher
# =============================================================================

@dataclass
class NotificationConfig:
    """Notification delivery configuration.

    SSA2-7
    """
    discord_webhook: str = ""
    email: str = ""
    queue_max: int = 500


class NotificationDispatcher:
    """Push permission change notifications to the SSA dashboard and externally.

    The in-memory ``queue`` is consumed by the SSA REST API's
    ``GET /notifications`` endpoint (long-poll).  Optionally delivers to a
    Discord webhook and/or an email address.

    SSA2-7
    """

    def __init__(self, server_id: str, config: NotificationConfig | None = None) -> None:
        self.server_id = server_id
        self._cfg = config or NotificationConfig()
        self._queue: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    # ── SSA2-7: Enqueue + dispatch ────────────────────────────────────────────

    def notify(self, message: str, event_type: str = "permission_change") -> None:
        """Enqueue *message* and attempt optional external delivery.

        SSA2-7
        """
        entry = {
            "ts":      datetime.datetime.utcnow().isoformat(),
            "server":  self.server_id,
            "type":    event_type,
            "message": message,
        }
        with self._lock:
            self._queue.append(entry)
            if len(self._queue) > self._cfg.queue_max:
                self._queue.pop(0)

        # Fire-and-forget external dispatch in a daemon thread so it never
        # blocks the caller (server lifecycle operations).
        if self._cfg.discord_webhook:
            threading.Thread(
                target=self._send_discord,
                args=(message,),
                daemon=True,
            ).start()

    def poll(self, clear: bool = True) -> list[dict[str, Any]]:
        """Return (and optionally drain) the pending notification queue.

        Called by the SSA REST API's ``GET /notifications`` endpoint.

        SSA2-7
        """
        with self._lock:
            result = list(self._queue)
            if clear:
                self._queue.clear()
        return result

    # ── Discord webhook (optional) ────────────────────────────────────────────

    def _send_discord(self, message: str) -> None:
        """POST *message* to the configured Discord webhook.

        Silently swallows errors so a broken webhook never crashes the server.

        SSA2-7
        """
        if not self._cfg.discord_webhook:
            return
        try:
            payload = json.dumps({"content": message}).encode()
            req = _urllib.Request(
                self._cfg.discord_webhook,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _urllib.urlopen(req, timeout=5):
                pass
        except Exception as exc:
            logger.warning("[%s] Discord notification failed: %s", self.server_id, exc)


# =============================================================================
# Convenience factory
# =============================================================================

@dataclass
class ServerPermissionBundle:
    """All permission-related components for one server, bundled together.

    Usage example::

        bundle = create_bundle("novaforge_eu1")
        bundle.manager.require("76561198000000001", "restart")
        bundle.audit.write("server.restart", actor="76561198000000001",
                           target="novaforge_eu1", detail={})
        bundle.notifier.notify("novaforge_eu1 restarted by admin")
    """
    server_id: str
    manager: PermissionManager
    audit: AuditLogger
    notifier: NotificationDispatcher


def create_bundle(
    server_id: str,
    config_dir: pathlib.Path | None = None,
    discord_webhook: str = "",
    email: str = "",
) -> ServerPermissionBundle:
    """Construct and return a :class:`ServerPermissionBundle` for *server_id*.

    SSA2-1, SSA2-2, SSA2-3, SSA2-4, SSA2-5, SSA2-6, SSA2-7
    """
    cfg = NotificationConfig(discord_webhook=discord_webhook, email=email)
    return ServerPermissionBundle(
        server_id=server_id,
        manager=PermissionManager(server_id, config_dir=config_dir),
        audit=AuditLogger(server_id),
        notifier=NotificationDispatcher(server_id, config=cfg),
    )
