"""Novaforge — SteamServerAdmin integration stub.

This module is a thin client that talks to the standalone SteamServerAdmin
REST API (Projects/SteamServerAdmin) to surface server state into the
Novaforge Tooling Layer.

Integration tasks are tracked in roadmap.json → NF3-1 through NF3-5.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib.request import urlopen
from urllib.error import URLError


class SSAClient:
    """Lightweight HTTP client for the SteamServerAdmin REST API.

    Parameters
    ----------
    base_url:
        Base URL of the SSA API server (e.g. ``http://localhost:8080``).
    timeout:
        Request timeout in seconds.
    """

    def __init__(self, base_url: str = "http://localhost:8080", timeout: int = 5) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{path}"
        try:
            with urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except (URLError, Exception):
            return None

    # ── NF3-2: Status events ──────────────────────────────────────────────────

    def get_servers(self) -> list:
        """Return the list of all managed servers and their status."""
        # TODO NF3-2: map SSA status to Tooling Layer StatusLogPanel model
        result = self._get("/servers")
        return result.get("servers", []) if result else []

    def get_server_status(self, server_id: str) -> Optional[Dict[str, Any]]:
        """Return status for a single server (uptime, player count, state)."""
        return self._get(f"/servers/{server_id}/status")

    # ── NF3-3: Feed logs into AI monitoring ──────────────────────────────────

    def get_server_logs(self, server_id: str, lines: int = 100) -> list:
        """Return recent log lines for a server (used by AI monitoring rules)."""
        result = self._get(f"/servers/{server_id}/logs?lines={lines}")
        return result.get("lines", []) if result else []

    # ── NF3-1: Wire Novaforge server identifiers into SSA config ─────────────

    NOVAFORGE_SERVERS: Dict[str, Dict[str, Any]] = {
        # Populate with actual Novaforge app IDs and install paths.
        # Example:
        # "novaforge_eu1": {
        #     "app_id": 12345,
        #     "install_path": "/opt/gameservers/novaforge_eu1",
        #     "branch": "public",
        # },
    }
