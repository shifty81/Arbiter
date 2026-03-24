"""SteamServerAdmin — Audit Log.

SSA2-5  Every permission change, ban, kick, and restart is JSONL-logged.
SSA2-6  Audit log accessible via REST endpoint; queried by the web dashboard.
SSA2-7  Permission change notifications pushed to in-memory queue (polled by
        the web dashboard) and optionally to a Discord webhook.

Log file location:  logs/steam_server_admin/audit_<server_id>.jsonl
Global audit log :  logs/steam_server_admin/audit.jsonl
"""
from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

from src.logger import get_ssa_logger

logger = get_ssa_logger("audit")

_SSA_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_DIR = _SSA_ROOT / "logs" / "steam_server_admin"
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# ── JSONL writer ─────────────────────────────────────────────────────────────


def _audit_path(server_id: Optional[str] = None) -> Path:
    if server_id:
        return _AUDIT_DIR / f"audit_{server_id}.jsonl"
    return _AUDIT_DIR / "audit.jsonl"


def _write_entry(entry: Dict[str, Any], server_id: Optional[str] = None) -> None:
    """Append *entry* as a JSON line to the JSONL audit log(s)."""
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    for path in [_audit_path(server_id), _audit_path(None)] if server_id else [_audit_path(None)]:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as exc:
            logger.error("Audit write failed (%s): %s", path, exc)


# ── Notification queue (SSA2-7) ────────────────────────────────────────────────

_notifications: List[Dict[str, Any]] = []
_notif_lock = threading.Lock()
_MAX_NOTIF = 500


def _queue_notification(entry: Dict[str, Any]) -> None:
    with _notif_lock:
        _notifications.append(entry)
        if len(_notifications) > _MAX_NOTIF:
            _notifications.pop(0)


def get_pending_notifications(limit: int = 50) -> List[Dict[str, Any]]:
    """Return (and drain) up to *limit* pending notifications."""
    with _notif_lock:
        batch = _notifications[:limit]
        del _notifications[:limit]
    return batch


def peek_notifications(limit: int = 50) -> List[Dict[str, Any]]:
    """Return up to *limit* pending notifications without draining."""
    with _notif_lock:
        return list(_notifications[:limit])


# ── Discord webhook notifier (SSA2-7) ─────────────────────────────────────────


_DISCORD_MAX_CONTENT_LENGTH = 2000


def _discord_notify(webhook_url: str, entry: Dict[str, Any]) -> None:
    """Best-effort POST to a Discord webhook in a background thread."""
    if not webhook_url:
        return
    event = entry.get("event", "unknown")
    server = entry.get("server_id", "")
    actor  = entry.get("actor", "")
    target = entry.get("target", "")
    detail = entry.get("detail", {})
    content = (
        f"**SSA Audit [{server}]** `{event}`\n"
        f"Actor: `{actor}` → Target: `{target}`\n"
        + (f"```{json.dumps(detail, indent=2)}```" if detail else "")
    )
    payload = json.dumps({"content": content[:_DISCORD_MAX_CONTENT_LENGTH]}).encode()
    req = Request(webhook_url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=5):
            pass
    except URLError as exc:
        logger.warning("Discord webhook error: %s", exc)


# ── Public audit API ─────────────────────────────────────────────────────────


def log_event(
    event: str,
    actor: str,
    target: str,
    server_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
    webhook_url: str = "",
) -> Dict[str, Any]:
    """Write a structured audit event and queue a notification.

    Parameters
    ----------
    event:      Short event name (e.g. ``"role.assign"``, ``"player.ban"``).
    actor:      The identity performing the action.
    target:     The entity the action is applied to.
    server_id:  If set, also written to ``audit_<server_id>.jsonl``.
    detail:     Arbitrary metadata dict.
    webhook_url: Discord webhook URL; omit or empty to skip.
    """
    entry: Dict[str, Any] = {
        "ts":        datetime.datetime.utcnow().isoformat(),
        "event":     event,
        "actor":     actor,
        "target":    target,
        "server_id": server_id or "",
        "detail":    detail or {},
    }
    _write_entry(entry, server_id)
    _queue_notification(entry)
    logger.info("[Audit] %s | actor=%s target=%s server=%s", event, actor, target, server_id or "global")

    if webhook_url:
        threading.Thread(target=_discord_notify, args=(webhook_url, entry), daemon=True).start()

    return entry


# ── Query helpers (SSA2-6) ────────────────────────────────────────────────────


def read_log(
    server_id: Optional[str] = None,
    limit: int = 100,
    event_prefix: str = "",
    actor: str = "",
    target: str = "",
) -> List[Dict[str, Any]]:
    """Return the last *limit* audit entries, optionally filtered.

    Uses the server-scoped log if *server_id* is set, else the global log.
    Entries are returned newest-first.
    """
    path = _audit_path(server_id)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        logger.error("Audit read error: %s", exc)
        return []

    entries: List[Dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event_prefix and not e.get("event", "").startswith(event_prefix):
            continue
        if actor and e.get("actor") != actor:
            continue
        if target and e.get("target") != target:
            continue
        entries.append(e)
        if len(entries) >= limit:
            break

    return entries


def audit_stats(server_id: Optional[str] = None) -> Dict[str, Any]:
    """Return a summary of audit log statistics for *server_id* (or global)."""
    entries = read_log(server_id, limit=10_000)
    total = len(entries)
    event_counts: Dict[str, int] = {}
    actor_counts: Dict[str, int] = {}
    for e in entries:
        event_counts[e.get("event", "?")] = event_counts.get(e.get("event", "?"), 0) + 1
        actor_counts[e.get("actor", "?")] = actor_counts.get(e.get("actor", "?"), 0) + 1

    top_events = sorted(event_counts.items(), key=lambda x: -x[1])[:10]
    top_actors = sorted(actor_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "server_id":  server_id or "global",
        "total":      total,
        "top_events": [{"event": e, "count": c} for e, c in top_events],
        "top_actors": [{"actor": a, "count": c} for a, c in top_actors],
    }
