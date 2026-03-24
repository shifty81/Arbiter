"""SteamServerAdmin — ServerManager.

Core start / stop / restart / update operations for any registered Steam game
server.  The ServerManager is the central orchestrator for SSA Phase 1:

  SSA1-1  start  — SteamCMD install + launch via config launch_args
  SSA1-2  stop   — graceful RCON shutdown, then SIGTERM fallback
  SSA1-3  restart — countdown warning → stop → start
  SSA1-4  update  — SteamCMD app_update validate → restart
  SSA1-5  scheduler — cron-style auto restart/update
  SSA1-6  supervisor — watch PID, auto-restart on crash
  SSA1-7  multi-server — manage N servers independently
  SSA1-8  RCON — send console commands to live server
"""
from __future__ import annotations

import os
import signal
import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.logger import get_ssa_logger, setup_ssa_logging
from src.steamcmd import SteamCMD, SteamCMDError

setup_ssa_logging()
logger = get_ssa_logger("server_manager")

_SSA_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _SSA_ROOT / "config"
_LOG_DIR = _SSA_ROOT / "logs" / "steam_server_admin"


# ── Server state ──────────────────────────────────────────────────────────────

class ServerState:
    STOPPED  = "stopped"
    STARTING = "starting"
    RUNNING  = "running"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    UPDATING = "updating"
    CRASHED  = "crashed"


@dataclass
class ServerInfo:
    """Live runtime information for a single managed server."""
    server_id: str
    state: str = ServerState.STOPPED
    pid: Optional[int] = None
    started_at: Optional[str] = None
    crash_count: int = 0
    last_crash: Optional[str] = None
    uptime_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "server_id":      self.server_id,
            "state":          self.state,
            "pid":            self.pid,
            "started_at":     self.started_at,
            "crash_count":    self.crash_count,
            "last_crash":     self.last_crash,
            "uptime_seconds": self.uptime_seconds,
        }


# ── RCON client (SSA1-8) ─────────────────────────────────────────────────────

class RCONClient:
    """Minimal Source RCON protocol client.

    Sends a single command and returns the server response.
    Reference: https://developer.valvesoftware.com/wiki/Source_RCON_Protocol
    """

    SERVERDATA_AUTH           = 3
    SERVERDATA_AUTH_RESPONSE  = 2
    SERVERDATA_EXECCOMMAND    = 2
    SERVERDATA_RESPONSE_VALUE = 0

    def __init__(self, host: str, port: int, password: str, timeout: int = 5) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._req_id = 1

    def _connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))

    def _send_packet(self, req_type: int, body: str) -> int:
        assert self._sock is not None
        req_id = self._req_id
        self._req_id += 1
        body_bytes = body.encode("utf-8") + b"\x00"
        # packet: size(4) + id(4) + type(4) + body + null(1)
        packet = struct.pack("<iii", len(body_bytes) + 8, req_id, req_type) + body_bytes + b"\x00"
        self._sock.sendall(packet)
        return req_id

    def _recv_packet(self) -> tuple[int, int, str]:
        assert self._sock is not None
        size_data = self._recv_exact(4)
        size = struct.unpack("<i", size_data)[0]
        payload = self._recv_exact(size)
        resp_id   = struct.unpack("<i", payload[:4])[0]
        resp_type = struct.unpack("<i", payload[4:8])[0]
        body = payload[8:-2].decode("utf-8", errors="replace")
        return resp_id, resp_type, body

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        data = b""
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("RCON connection closed")
            data += chunk
        return data

    def send_command(self, command: str) -> str:
        """Authenticate and send *command*; return the server's response."""
        try:
            self._connect()
            # Authenticate
            auth_id = self._send_packet(self.SERVERDATA_AUTH, self.password)
            _, _, _ = self._recv_packet()   # discard junk packet
            resp_id, resp_type, _ = self._recv_packet()
            if resp_id == -1:
                raise PermissionError("RCON authentication failed (wrong password?)")

            # Send command
            cmd_id = self._send_packet(self.SERVERDATA_EXECCOMMAND, command)
            # Send a no-op to mark end of response
            self._send_packet(self.SERVERDATA_EXECCOMMAND, "")

            response_parts: list[str] = []
            while True:
                r_id, _, body = self._recv_packet()
                if r_id == cmd_id + 1:
                    break
                response_parts.append(body)
            return "".join(response_parts)
        finally:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None


# ── ServerManager (SSA1-1 through SSA1-8) ────────────────────────────────────

class ServerManager:
    """Manages the full lifecycle of a single Steam game server instance.

    One ServerManager per server.  Use MultiServerManager to supervise several
    servers from a single SSA instance (SSA1-7).
    """

    def __init__(self, config: Dict[str, Any], steamcmd: Optional[SteamCMD] = None) -> None:
        self.cfg = config
        self.server_id: str = config["server_id"]
        self.app_id: int = int(config["app_id"])
        self.install_path = Path(config["install_path"])
        self.branch: str = config.get("branch", "public")
        self.launch_args: list[str] = config.get("launch_args", [])
        self.executable: str = config.get("executable", "")
        self.restart_warning_minutes: int = int(config.get("restart_warning_minutes", 5))
        self.auto_restart_on_crash: bool = bool(config.get("auto_restart_on_crash", True))
        self.max_crash_restarts: int = int(config.get("max_crash_restarts", 5))

        rcon_cfg = config.get("rcon", {})
        self._rcon_enabled   = bool(rcon_cfg.get("enabled", False))
        self._rcon_host      = rcon_cfg.get("host", "127.0.0.1")
        self._rcon_port      = int(rcon_cfg.get("port", 27015))
        self._rcon_password  = rcon_cfg.get("password", "")

        self._steamcmd: Optional[SteamCMD] = steamcmd
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._supervisor_thread: Optional[threading.Thread] = None
        self._supervisor_stop = threading.Event()

        self.info = ServerInfo(server_id=self.server_id)
        self._on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None

    # ── Event hook ────────────────────────────────────────────────────────────

    def set_event_hook(self, hook: Callable[[str, Dict[str, Any]], None]) -> None:
        """Register a callback(event_type, data) for status change events."""
        self._on_event = hook

    def _emit(self, event_type: str, **data: Any) -> None:
        logger.info("[%s] %s %s", self.server_id, event_type, data)
        if self._on_event:
            try:
                self._on_event(event_type, {"server_id": self.server_id, **data})
            except Exception:
                pass

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_executable(self) -> Path:
        """Resolve the server executable path."""
        if self.executable:
            return self.install_path / self.executable
        # Heuristic: find the first .sh or .exe inside install_path
        for ext in ("*.sh", "*.exe", "server", "srcds"):
            for p in self.install_path.glob(ext):
                return p
        return self.install_path / "server"

    def _is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    def _set_state(self, state: str) -> None:
        self.info.state = state

    # ── SSA1-1: Start ─────────────────────────────────────────────────────────

    def start(self, install_if_missing: bool = True) -> Dict[str, Any]:
        """Install (if missing) and launch the server process.

        SSA1-1
        """
        with self._lock:
            if self._is_running():
                # _is_running() verified self._process is not None and still alive
                pid = self._process.pid if self._process is not None else None
                return {"status": "already_running", "pid": pid}

            self._set_state(ServerState.STARTING)
            self._emit("starting")

            # Install / update via SteamCMD if the install path doesn't exist
            if install_if_missing and self._steamcmd and not self.install_path.is_dir():
                logger.info("[%s] Install path missing — running SteamCMD install", self.server_id)
                try:
                    self._steamcmd.update_app(self.app_id, self.install_path, self.branch)
                except SteamCMDError as exc:
                    self._set_state(ServerState.STOPPED)
                    return {"status": "error", "error": f"SteamCMD install failed: {exc}"}

            exe = self._get_executable()
            if not exe.exists():
                self._set_state(ServerState.STOPPED)
                return {"status": "error", "error": f"Server executable not found: {exe}"}

            cmd = [str(exe)] + self.launch_args
            try:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=str(self.install_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            except Exception as exc:
                self._set_state(ServerState.STOPPED)
                return {"status": "error", "error": str(exc)}

            self.info.pid = self._process.pid
            self.info.started_at = datetime.utcnow().isoformat()
            self._set_state(ServerState.RUNNING)
            self._emit("started", pid=self.info.pid)
            self._start_supervisor()
            return {"status": "started", "pid": self.info.pid}

    # ── SSA1-2: Stop ─────────────────────────────────────────────────────────

    def stop(self, graceful_timeout: int = 30) -> Dict[str, Any]:
        """Graceful RCON shutdown, then SIGTERM/kill fallback.

        SSA1-2
        """
        with self._lock:
            if not self._is_running():
                self._set_state(ServerState.STOPPED)
                return {"status": "already_stopped"}

            self._set_state(ServerState.STOPPING)
            self._emit("stopping")
            self._stop_supervisor()

            # Try RCON graceful shutdown first
            if self._rcon_enabled and self._process is not None:
                try:
                    rcon = RCONClient(self._rcon_host, self._rcon_port, self._rcon_password)
                    rcon.send_command("quit")
                    logger.info("[%s] RCON quit sent", self.server_id)
                    try:
                        self._process.wait(timeout=graceful_timeout)
                    except subprocess.TimeoutExpired:
                        logger.info("[%s] RCON shutdown timed out — falling back to SIGTERM", self.server_id)
                except Exception as exc:
                    logger.warning("[%s] RCON shutdown failed: %s", self.server_id, exc)

            # SIGTERM fallback
            if self._is_running() and self._process is not None:
                try:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                except Exception as exc:
                    logger.error("[%s] Kill failed: %s", self.server_id, exc)

            self.info.pid = None
            self._process = None
            self._set_state(ServerState.STOPPED)
            self._emit("stopped")
            return {"status": "stopped"}

    # ── SSA1-3: Restart ───────────────────────────────────────────────────────

    def restart(self, warn_players: bool = True) -> Dict[str, Any]:
        """Countdown warning → stop → start.

        SSA1-3
        """
        self._set_state(ServerState.RESTARTING)
        self._emit("restart_initiated")

        if warn_players and self._rcon_enabled and self.restart_warning_minutes > 0:
            self._broadcast(f"Server restarting in {self.restart_warning_minutes} minute(s). Please save and disconnect.")
            # Wait for the warning period in 60-second chunks
            for remaining in range(self.restart_warning_minutes, 0, -1):
                time.sleep(60)
                if remaining > 1:
                    self._broadcast(f"Restarting in {remaining - 1} minute(s).")
            self._broadcast("Server is restarting NOW.")

        stop_result = self.stop()
        if stop_result.get("status") == "error":
            return stop_result
        return self.start()

    # ── SSA1-4: Update ────────────────────────────────────────────────────────

    def update(self, validate: bool = True) -> Dict[str, Any]:
        """SteamCMD app_update validate → broadcast warning → restart.

        SSA1-4
        """
        if self._steamcmd is None:
            return {"status": "error", "error": "SteamCMD not configured"}

        self._set_state(ServerState.UPDATING)
        self._emit("update_started")

        # Warn players
        if self._rcon_enabled and self._is_running():
            self._broadcast(f"Server updating in {self.restart_warning_minutes} minute(s). Please disconnect.")
            time.sleep(self.restart_warning_minutes * 60)
            self._broadcast("Server update starting NOW.")

        # Stop the server before updating
        if self._is_running():
            self.stop()

        # Run SteamCMD update
        try:
            self._steamcmd.update_app(self.app_id, self.install_path, self.branch, validate=validate)
        except SteamCMDError as exc:
            self._set_state(ServerState.STOPPED)
            return {"status": "error", "error": str(exc)}

        self._emit("update_complete")
        # Restart after update
        return self.start()

    # ── SSA1-8: RCON command ──────────────────────────────────────────────────

    def send_rcon(self, command: str) -> Dict[str, Any]:
        """Send a raw RCON command and return the response.

        SSA1-8
        """
        if not self._rcon_enabled:
            return {"status": "error", "error": "RCON is not enabled for this server"}
        try:
            rcon = RCONClient(self._rcon_host, self._rcon_port, self._rcon_password)
            response = rcon.send_command(command)
            return {"status": "ok", "command": command, "response": response}
        except Exception as exc:
            return {"status": "error", "command": command, "error": str(exc)}

    def _broadcast(self, message: str) -> None:
        """Broadcast a message to all connected players via RCON `say`."""
        if self._rcon_enabled:
            try:
                rcon = RCONClient(self._rcon_host, self._rcon_port, self._rcon_password)
                rcon.send_command(f"say {message}")
            except Exception as exc:
                logger.warning("[%s] Broadcast failed: %s", self.server_id, exc)

    # ── SSA1-6: Process supervisor ────────────────────────────────────────────

    def _start_supervisor(self) -> None:
        """Start the background thread that watches the server PID.

        SSA1-6
        """
        self._supervisor_stop.clear()
        self._supervisor_thread = threading.Thread(
            target=self._supervisor_loop,
            daemon=True,
            name=f"ssa-supervisor-{self.server_id}",
        )
        self._supervisor_thread.start()

    def _stop_supervisor(self) -> None:
        self._supervisor_stop.set()
        if self._supervisor_thread and self._supervisor_thread.is_alive():
            self._supervisor_thread.join(timeout=5)

    def _supervisor_loop(self) -> None:
        """Watch server PID; auto-restart on unexpected exit.

        SSA1-6
        """
        while not self._supervisor_stop.is_set():
            time.sleep(5)
            if self._supervisor_stop.is_set():
                break
            if self._process is not None and self._process.poll() is not None:
                # Process has exited unexpectedly
                exit_code = self._process.returncode
                self.info.crash_count += 1
                self.info.last_crash = datetime.utcnow().isoformat()
                self._set_state(ServerState.CRASHED)
                self._emit("crashed", exit_code=exit_code, crash_count=self.info.crash_count)
                logger.warning(
                    "[%s] Server crashed (exit=%d) — crash #%d",
                    self.server_id, exit_code, self.info.crash_count,
                )

                if self.auto_restart_on_crash and self.info.crash_count <= self.max_crash_restarts:
                    logger.info("[%s] Auto-restarting after crash", self.server_id)
                    time.sleep(5)
                    self.start(install_if_missing=False)
                else:
                    logger.error(
                        "[%s] Max crash restarts (%d) reached — giving up",
                        self.server_id, self.max_crash_restarts,
                    )
                    self._set_state(ServerState.STOPPED)
                    self._emit("max_crashes_reached")
                    break

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return current runtime status of this server."""
        if self._is_running() and self.info.started_at:
            started = datetime.fromisoformat(self.info.started_at)
            self.info.uptime_seconds = (datetime.utcnow() - started).total_seconds()
        return self.info.to_dict()


# ── SSA1-5: Scheduler ────────────────────────────────────────────────────────

class ServerScheduler:
    """Cron-style scheduler for automatic restarts and updates.

    Reads cron expressions from each server's config and dispatches
    restart/update operations at the scheduled times.

    SSA1-5
    """

    def __init__(self) -> None:
        self._tasks: List[Dict[str, Any]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def register(self, manager: "ServerManager") -> None:
        """Register a ServerManager for scheduled operations."""
        cfg = manager.cfg
        if cfg.get("restart_schedule"):
            self._tasks.append({
                "server_id": manager.server_id,
                "cron": cfg["restart_schedule"],
                "action": "restart",
                "manager": manager,
                "_last_fired": None,
            })
            logger.info("[scheduler] Registered restart schedule '%s' for %s",
                        cfg["restart_schedule"], manager.server_id)
        if cfg.get("update_schedule"):
            self._tasks.append({
                "server_id": manager.server_id,
                "cron": cfg["update_schedule"],
                "action": "update",
                "manager": manager,
                "_last_fired": None,
            })
            logger.info("[scheduler] Registered update schedule '%s' for %s",
                        cfg["update_schedule"], manager.server_id)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ssa-scheduler"
        )
        self._thread.start()
        logger.info("[scheduler] Started with %d tasks", len(self._tasks))

    def stop(self) -> None:
        self._stop.set()

    def _cron_matches(self, cron_expr: str, now: datetime) -> bool:
        """Very lightweight cron matcher for 5-field expressions.

        Supports: ``*``, ``*/N``, and exact values only.
        """
        try:
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                return False
            fields = [now.minute, now.hour, now.day, now.month, now.weekday()]
            for value, part in zip(fields, parts):
                if part == "*":
                    continue
                if part.startswith("*/"):
                    step = int(part[2:])
                    if value % step != 0:
                        return False
                elif int(part) != value:
                    return False
            return True
        except Exception:
            return False

    def _run(self) -> None:
        while not self._stop.is_set():
            now = datetime.utcnow().replace(second=0, microsecond=0)
            for task in self._tasks:
                if self._cron_matches(task["cron"], now):
                    last = task["_last_fired"]
                    if last != now:
                        task["_last_fired"] = now
                        mgr: ServerManager = task["manager"]
                        action: str = task["action"]
                        logger.info(
                            "[scheduler] Firing %s for %s", action, task["server_id"]
                        )
                        threading.Thread(
                            target=getattr(mgr, action),
                            daemon=True,
                            name=f"ssa-sched-{task['server_id']}-{action}",
                        ).start()
            # Sleep until the next minute boundary
            time.sleep(60 - datetime.utcnow().second)


# ── SSA1-7: Multi-server manager ─────────────────────────────────────────────

class MultiServerManager:
    """Manage any number of registered servers from one SSA instance.

    Usage::

        msm = MultiServerManager()
        msm.load_configs(_SSA_ROOT / "config")
        msm.start_all()
    """

    def __init__(self, steamcmd: Optional[SteamCMD] = None) -> None:
        self._servers: Dict[str, ServerManager] = {}
        self._scheduler = ServerScheduler()
        self._steamcmd = steamcmd

    # ── Config loading ────────────────────────────────────────────────────────

    def load_configs(self, config_dir: Path) -> List[str]:
        """Load all server configs from *config_dir*.

        Skips ``server_schema.json`` and ``example_server.json``.
        Returns the list of loaded server IDs.
        """
        loaded: List[str] = []
        skip = {"server_schema.json", "example_server.json"}
        for cfg_file in sorted(config_dir.glob("*.json")):
            if cfg_file.name in skip:
                continue
            try:
                import json
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                self.register(cfg)
                loaded.append(cfg["server_id"])
            except Exception as exc:
                logger.error("Failed to load config %s: %s", cfg_file, exc)
        return loaded

    def register(self, config: Dict[str, Any]) -> ServerManager:
        """Register a server from a config dict and return its manager."""
        mgr = ServerManager(config, steamcmd=self._steamcmd)
        self._servers[config["server_id"]] = mgr
        self._scheduler.register(mgr)
        return mgr

    def get(self, server_id: str) -> Optional[ServerManager]:
        return self._servers.get(server_id)

    def all_ids(self) -> List[str]:
        return list(self._servers.keys())

    def all_status(self) -> List[Dict[str, Any]]:
        return [mgr.status() for mgr in self._servers.values()]

    # ── Bulk operations ───────────────────────────────────────────────────────

    def start_all(self) -> Dict[str, Any]:
        results = {}
        for sid, mgr in self._servers.items():
            results[sid] = mgr.start()
        self._scheduler.start()
        return results

    def stop_all(self) -> Dict[str, Any]:
        self._scheduler.stop()
        return {sid: mgr.stop() for sid, mgr in self._servers.items()}
