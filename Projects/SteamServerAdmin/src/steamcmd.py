"""SteamServerAdmin — SteamCMD Wrapper.

Detects the SteamCMD binary for the current platform, and exposes a clean
Python API for the most common operations:

  - install / update / validate an app
  - download a single workshop item
  - run an arbitrary SteamCMD script

Usage example::

    from src.steamcmd import SteamCMD, SteamCMDError

    steam = SteamCMD("/opt/steamcmd/steamcmd.sh")
    steam.update_app(app_id=896660, install_dir="/opt/servers/valheim", validate=True)
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from src.logger import get_ssa_logger

logger = get_ssa_logger("steamcmd")


class SteamCMDError(RuntimeError):
    """Raised when a SteamCMD command exits with a non-zero return code."""


# ── Platform detection ────────────────────────────────────────────────────────

def _default_steamcmd_paths() -> list[Path]:
    """Return a list of candidate SteamCMD binary paths for the current OS."""
    system = platform.system().lower()
    if system == "windows":
        return [
            Path(r"C:\steamcmd\steamcmd.exe"),
            Path(r"C:\SteamCMD\steamcmd.exe"),
            Path(os.environ.get("STEAMCMD_DIR", r"C:\steamcmd")) / "steamcmd.exe",
        ]
    # Linux / macOS
    return [
        Path("/usr/games/steamcmd"),
        Path("/usr/bin/steamcmd"),
        Path(os.path.expanduser("~/steamcmd/steamcmd.sh")),
        Path("/opt/steamcmd/steamcmd.sh"),
    ]


def find_steamcmd(override: str | Path | None = None) -> Path | None:
    """Return the Path to a usable SteamCMD binary, or *None* if not found.

    Parameters
    ----------
    override:
        If given, only check this explicit path and skip platform defaults.
    """
    candidates = [Path(override)] if override else _default_steamcmd_paths()

    # Also check PATH
    which_result = shutil.which("steamcmd")
    if which_result:
        candidates.insert(0, Path(which_result))

    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            logger.debug("Found SteamCMD at %s", path)
            return path

    logger.warning("SteamCMD binary not found. Searched: %s", candidates)
    return None


# ── SteamCMD wrapper ──────────────────────────────────────────────────────────

class SteamCMD:
    """High-level wrapper around the SteamCMD command-line tool.

    Parameters
    ----------
    binary:
        Explicit path to the SteamCMD executable.  If not provided,
        ``find_steamcmd()`` is used.
    timeout:
        Subprocess timeout in seconds (default: 600 = 10 min for large installs).
    """

    def __init__(
        self,
        binary: str | Path | None = None,
        timeout: int = 600,
    ) -> None:
        resolved = find_steamcmd(binary)
        if resolved is None:
            raise SteamCMDError(
                "SteamCMD binary not found. "
                "Install SteamCMD and ensure it is on PATH or pass the explicit path."
            )
        self.binary = resolved
        self.timeout = timeout
        self._platform = platform.system().lower()
        logger.info("SteamCMD initialised: binary=%s platform=%s", self.binary, self._platform)

    # ── Internal runner ───────────────────────────────────────────────────────

    def _run(self, *cmds: str) -> str:
        """Build and execute a SteamCMD command string.

        Each positional argument in *cmds* is one SteamCMD command token
        (e.g. ``"+login anonymous"``, ``"+app_update 896660 validate"``).
        The ``+quit`` token is appended automatically.

        Returns the combined stdout+stderr output as a string.
        Raises :class:`SteamCMDError` on non-zero exit.
        """
        args = [str(self.binary)] + list(cmds) + ["+quit"]
        logger.info("Running SteamCMD: %s", " ".join(args))
        try:
            proc = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise SteamCMDError(f"SteamCMD timed out after {self.timeout}s") from exc

        output = proc.stdout or ""
        logger.debug("SteamCMD output:\n%s", output[-2000:])  # last 2 KB

        if proc.returncode != 0:
            raise SteamCMDError(
                f"SteamCMD exited with code {proc.returncode}.\n"
                f"Last output:\n{output[-1000:]}"
            )
        return output

    # ── Public API ────────────────────────────────────────────────────────────

    def update_app(
        self,
        app_id: int,
        install_dir: str | Path,
        branch: str = "public",
        validate: bool = False,
        username: str = "anonymous",
        password: str = "",
        steam_guard_code: str = "",
    ) -> str:
        """Install or update a Steam app (dedicated server).

        Parameters
        ----------
        app_id:
            Steam AppID of the dedicated server application.
        install_dir:
            Directory where the server files should be installed.
        branch:
            Beta branch name (default ``"public"``).
        validate:
            If ``True``, appends ``validate`` to the ``+app_update`` command
            to verify all file checksums.
        username / password / steam_guard_code:
            Credentials for non-anonymous apps.
        """
        install_dir = Path(install_dir)
        install_dir.mkdir(parents=True, exist_ok=True)

        branch_flag = f"-beta {branch}" if branch and branch != "public" else ""
        validate_flag = "validate" if validate else ""
        app_update = f"+app_update {app_id} {branch_flag} {validate_flag}".strip()

        login = f"+login {username}"
        if password:
            login += f" {password}"
            if steam_guard_code:
                login += f" {steam_guard_code}"

        logger.info("Installing/updating app %s into %s", app_id, install_dir)
        return self._run(
            login,
            f"+force_install_dir {install_dir}",
            app_update,
        )

    def validate_app(self, app_id: int, install_dir: str | Path, branch: str = "public") -> str:
        """Re-validate an existing server installation (checksum all files)."""
        return self.update_app(app_id, install_dir, branch=branch, validate=True)

    def download_workshop_item(
        self,
        app_id: int,
        workshop_item_id: int,
        install_dir: str | Path,
    ) -> str:
        """Download a single Steam Workshop item."""
        install_dir = Path(install_dir)
        install_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading workshop item %s for app %s", workshop_item_id, app_id)
        return self._run(
            "+login anonymous",
            f"+force_install_dir {install_dir}",
            f"+workshop_download_item {app_id} {workshop_item_id}",
        )

    def run_script(self, script_path: str | Path) -> str:
        """Execute a SteamCMD script file (+runscript)."""
        script_path = Path(script_path)
        if not script_path.exists():
            raise SteamCMDError(f"Script file not found: {script_path}")
        logger.info("Running SteamCMD script: %s", script_path)
        return self._run(f"+runscript {script_path}")

    def is_available(self) -> bool:
        """Return True if SteamCMD can be executed (binary exists and is runnable)."""
        try:
            self._run("+login anonymous")
            return True
        except SteamCMDError:
            return False
        except Exception:
            return False
