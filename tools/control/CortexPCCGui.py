#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from PCCSurfaceCommon import (
    BackendClient,
    ProjectContract,
    SurfaceError,
    compact_path,
    latest_debug_bundle,
    open_path,
    resolve_root,
    reveal_file,
    terminate_process_tree,
    validate_surface,
)

GUI_VERSION = "PCC-GUI-0.1"

BG = "#090b0e"
PANEL = "#11151a"
PANEL_2 = "#171c22"
BORDER = "#28313a"
TEXT = "#edf2f5"
MUTED = "#929aa3"
CYAN = "#00d9ff"
GREEN = "#43f071"
YELLOW = "#ffd44a"
RED = "#ff5d68"
BLUE = "#5aa9ff"


class CortexPCCGui:
    def __init__(self, root: Path) -> None:
        # Lazy import keeps --self-test usable on hosts without Tk.
        import tkinter as tk
        from tkinter import messagebox, simpledialog, ttk

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.simpledialog = simpledialog
        self.root_path = root
        self.contract = ProjectContract.load(root)
        self.backend = BackendClient(root)

        self.window = tk.Tk()
        self.window.title(f"{self.contract.name} Project Control Center")
        self.window.geometry("1180x760")
        self.window.minsize(980, 660)
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._event_q: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._active_proc: subprocess.Popen[str] | None = None
        self._active_command = ""
        self._last_status: dict[str, Any] = {}
        self._page_frames: dict[str, Any] = {}
        self._status_values: dict[str, Any] = {}
        self._status_colors: dict[str, Any] = {}
        self._nav_buttons: dict[str, Any] = {}
        self._busy = False

        self._configure_styles()
        self._build_shell()
        self._show_page("Dashboard")
        self._append_log(f"{self.contract.name} PCC GUI {GUI_VERSION} started.\n", "info")
        self._append_log(f"Project: {self.root_path}\n", "muted")
        self._refresh_status_async()
        self.window.after(60, self._drain_events)

    def _configure_styles(self) -> None:
        ttk = self.ttk
        style = ttk.Style(self.window)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview", background=PANEL_2, fieldbackground=PANEL_2, foreground=TEXT,
                        rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background=PANEL, foreground=CYAN, relief="flat")
        style.map("Treeview", background=[("selected", "#21404a")], foreground=[("selected", TEXT)])
        style.configure("TProgressbar", troughcolor=PANEL_2, background=CYAN, borderwidth=0)

    def _build_shell(self) -> None:
        tk = self.tk

        header = tk.Frame(self.window, bg=BG, height=82)
        header.pack(fill="x", padx=22, pady=(18, 8))
        header.pack_propagate(False)

        title_block = tk.Frame(header, bg=BG)
        title_block.pack(side="left", fill="y")
        tk.Label(title_block, text=f"{self.contract.name.upper()} PROJECT CONTROL CENTER",
                 bg=BG, fg=CYAN, font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(title_block, text=f"{self.contract.kind}  •  {compact_path(self.root_path, 105)}",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

        header_actions = tk.Frame(header, bg=BG)
        header_actions.pack(side="right", fill="y")
        self.refresh_btn = self._button(header_actions, "Refresh", self._refresh_status_async, compact=True)
        self.refresh_btn.pack(side="left", padx=4, pady=12)
        self.cli_btn = self._button(header_actions, "Open CLI", self._open_cli, compact=True)
        self.cli_btn.pack(side="left", padx=4, pady=12)

        separator = tk.Frame(self.window, bg=CYAN, height=1)
        separator.pack(fill="x")

        body = tk.Frame(self.window, bg=BG)
        body.pack(fill="both", expand=True)

        nav = tk.Frame(body, bg=PANEL, width=190, highlightthickness=1, highlightbackground=BORDER)
        nav.pack(side="left", fill="y", padx=(18, 8), pady=16)
        nav.pack_propagate(False)
        tk.Label(nav, text="OPERATIONS", bg=PANEL, fg=MUTED, font=("Segoe UI Semibold", 9)).pack(
            anchor="w", padx=16, pady=(18, 8)
        )
        for page in ("Dashboard", "Build & Run", "Updates", "Source Control", "Diagnostics", "Logs", "Registered Commands"):
            btn = tk.Button(nav, text=page, anchor="w", command=lambda p=page: self._show_page(p),
                            bg=PANEL, fg=TEXT, activebackground=PANEL_2, activeforeground=CYAN,
                            bd=0, relief="flat", font=("Segoe UI", 10), cursor="hand2",
                            padx=16, pady=9)
            btn.pack(fill="x", padx=2, pady=1)
            self._nav_buttons[page] = btn

        tk.Frame(nav, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(14, 10))
        self.operation_label = tk.Label(nav, text="Idle", bg=PANEL, fg=MUTED, font=("Segoe UI", 9),
                                        wraplength=155, justify="left")
        self.operation_label.pack(anchor="w", padx=16, pady=(0, 6))
        self.stop_btn = self._button(nav, "Stop Active Job", self._stop_active, compact=True, danger=True)
        self.stop_btn.pack(fill="x", padx=12, pady=(2, 8))
        self.stop_btn.configure(state="disabled")

        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side="left", fill="both", expand=True, padx=(8, 18), pady=16)

        for page in ("Dashboard", "Build & Run", "Updates", "Source Control", "Diagnostics", "Logs", "Registered Commands"):
            frame = tk.Frame(self.content, bg=BG)
            self._page_frames[page] = frame

        self._build_dashboard(self._page_frames["Dashboard"])
        self._build_build_page(self._page_frames["Build & Run"])
        self._build_updates_page(self._page_frames["Updates"])
        self._build_source_page(self._page_frames["Source Control"])
        self._build_diagnostics_page(self._page_frames["Diagnostics"])
        self._build_logs_page(self._page_frames["Logs"])
        self._build_commands_page(self._page_frames["Registered Commands"])

        statusbar = tk.Frame(self.window, bg="#07090b", height=30, highlightthickness=1, highlightbackground="#20262d")
        statusbar.pack(fill="x", side="bottom")
        statusbar.pack_propagate(False)
        self.footer = tk.Label(statusbar, text="[Status:Loading]", bg="#07090b", fg=CYAN,
                               font=("Consolas", 9), anchor="w")
        self.footer.pack(fill="both", padx=12)

    def _panel(self, parent: Any, title: str | None = None) -> Any:
        tk = self.tk
        frame = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        if title:
            tk.Label(frame, text=title, bg=PANEL, fg=CYAN, font=("Segoe UI Semibold", 11)).pack(
                anchor="w", padx=14, pady=(12, 6)
            )
        return frame

    def _button(self, parent: Any, text: str, command: Callable[[], None], *, primary: bool = False,
                compact: bool = False, danger: bool = False) -> Any:
        tk = self.tk
        bg = CYAN if primary else (RED if danger else PANEL_2)
        fg = "#001018" if primary else TEXT
        active = "#52e7ff" if primary else ("#ff7a83" if danger else "#24303a")
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                         activebackground=active, activeforeground=fg, bd=0, relief="flat",
                         cursor="hand2", font=("Segoe UI Semibold" if primary else "Segoe UI", 10),
                         padx=12 if compact else 18, pady=6 if compact else 10)

    def _section_title(self, parent: Any, title: str, subtitle: str = "") -> None:
        tk = self.tk
        tk.Label(parent, text=title, bg=BG, fg=TEXT, font=("Segoe UI Semibold", 16)).pack(anchor="w")
        if subtitle:
            tk.Label(parent, text=subtitle, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 12))

    def _build_dashboard(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Project Health", "Havenwild-style operational summary backed by the project PCC authority.")

        cards = tk.Frame(parent, bg=BG)
        cards.pack(fill="x")
        labels = ["Git", "GREEN", "Updates", "Hygiene", "CLI", "Desktop"]
        for col, key in enumerate(labels):
            card = self._panel(cards)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 5, 5 if col < len(labels) - 1 else 0))
            cards.grid_columnconfigure(col, weight=1)
            tk.Label(card, text=key, bg=PANEL, fg=MUTED, font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=12, pady=(10, 1))
            value = tk.Label(card, text="Loading", bg=PANEL, fg=CYAN, font=("Segoe UI Semibold", 11), anchor="w")
            value.pack(fill="x", padx=12, pady=(0, 10))
            self._status_values[key] = value

        actions = self._panel(parent, "Primary Actions")
        actions.pack(fill="x", pady=(14, 10))
        row = tk.Frame(actions, bg=PANEL)
        row.pack(fill="x", padx=14, pady=(4, 14))
        self._button(row, "FULL QUALITY GATE / CERTIFY GREEN", lambda: self._start_command("full"), primary=True).pack(side="left", padx=(0, 8))
        self._button(row, "COMMIT CURRENT CERTIFIED GREEN", self._commit_green).pack(side="left", padx=8)
        self._button(row, "Apply Updates", self._apply_updates).pack(side="left", padx=8)
        self._button(row, "Open Latest Debug", self._open_latest_debug).pack(side="left", padx=8)

        summary = self._panel(parent, "Current Authority")
        summary.pack(fill="both", expand=True)
        self.summary_text = tk.Text(summary, bg=PANEL, fg=TEXT, insertbackground=TEXT, bd=0, relief="flat",
                                    font=("Consolas", 10), height=12, wrap="word")
        self.summary_text.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        self.summary_text.configure(state="disabled")

    def _build_build_page(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Build & Run", "Builds and launches use the same machine-facing PCC authority as CLI/Cortex.")
        panel = self._panel(parent, "Build")
        panel.pack(fill="x")
        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill="x", padx=14, pady=14)
        self._button(row, "Build Debug Workspace", lambda: self._start_command("build"), primary=True).pack(side="left", padx=(0, 8))
        self._button(row, "Build Release Workspace", lambda: self._start_command("build-release")).pack(side="left", padx=8)
        self._button(row, "Quick Gate", lambda: self._start_command("quick")).pack(side="left", padx=8)
        self._button(row, "Fast Gate", lambda: self._start_command("fast")).pack(side="left", padx=8)

        run_panel = self._panel(parent, "Run")
        run_panel.pack(fill="x", pady=(12, 0))
        row2 = tk.Frame(run_panel, bg=PANEL)
        row2.pack(fill="x", padx=14, pady=14)
        self._button(row2, "Launch Cortex Desktop", lambda: self._start_command("launch-gui"), primary=True).pack(side="left", padx=(0, 8))
        self._button(row2, "Open Project Folder", lambda: open_path(self.root_path)).pack(side="left", padx=8)

    def _build_updates_page(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Updates", "Fail-closed patch authority with explicit apply and recovery evidence.")
        panel = self._panel(parent, "Patch Queue")
        panel.pack(fill="x")
        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill="x", padx=14, pady=14)
        self._button(row, "Inspect Queue", lambda: self._start_command("patch-status"), primary=True).pack(side="left", padx=(0, 8))
        self._button(row, "Apply Validated Queue", self._apply_updates).pack(side="left", padx=8)
        self._button(row, "Refresh Health", self._refresh_status_async).pack(side="left", padx=8)

        paths = self._panel(parent, "History & Evidence")
        paths.pack(fill="x", pady=(12, 0))
        r2 = tk.Frame(paths, bg=PANEL)
        r2.pack(fill="x", padx=14, pady=14)
        patch_root = self.root_path / "artifacts" / "patches"
        self._button(r2, "Applied", lambda: open_path(patch_root / "applied")).pack(side="left", padx=(0, 8))
        self._button(r2, "Failed", lambda: open_path(patch_root / "failed")).pack(side="left", padx=8)
        self._button(r2, "Receipts", lambda: open_path(patch_root / "receipts")).pack(side="left", padx=8)
        self._button(r2, "Backups", lambda: open_path(patch_root / "backups")).pack(side="left", padx=8)

    def _build_source_page(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Source Control", "GREEN-gated source control stays behind the PCC Git authority.")
        panel = self._panel(parent, "Git / Repository")
        panel.pack(fill="x")
        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill="x", padx=14, pady=14)
        self._button(row, "Status", lambda: self._start_command("git-status"), primary=True).pack(side="left", padx=(0, 8))
        self._button(row, "Review Changes", lambda: self._start_command("git-review")).pack(side="left", padx=8)
        self._button(row, "History", lambda: self._start_command("git-history")).pack(side="left", padx=8)
        self._button(row, "Verify Authority", lambda: self._start_command("git-verify")).pack(side="left", padx=8)

        row2 = tk.Frame(panel, bg=PANEL)
        row2.pack(fill="x", padx=14, pady=(0, 14))
        self._button(row2, "Commit Certified GREEN", self._commit_green, primary=True).pack(side="left", padx=(0, 8))
        self._button(row2, "Commit + Push GREEN", self._commit_push_green).pack(side="left", padx=8)
        self._button(row2, "Push", lambda: self._start_command("push")).pack(side="left", padx=8)
        self._button(row2, "Pull (FF only)", lambda: self._start_command("git-pull")).pack(side="left", padx=8)

    def _build_diagnostics_page(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Diagnostics & Recovery", "Detailed evidence stays in artifacts/logs; the operator surface remains concise.")
        panel = self._panel(parent, "Diagnostics")
        panel.pack(fill="x")
        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill="x", padx=14, pady=14)
        self._button(row, "PCC Self-Test", lambda: self._start_command("self-test"), primary=True).pack(side="left", padx=(0, 8))
        self._button(row, "Doctor", lambda: self._start_command("doctor")).pack(side="left", padx=8)
        self._button(row, "Root Hygiene", lambda: self._start_command("root-hygiene")).pack(side="left", padx=8)
        self._button(row, "Repair Hygiene", lambda: self._start_command("root-hygiene-fix")).pack(side="left", padx=8)

        row2 = tk.Frame(panel, bg=PANEL)
        row2.pack(fill="x", padx=14, pady=(0, 14))
        self._button(row2, "Create Debug Bundle", lambda: self._start_command("debug-bundle"), primary=True).pack(side="left", padx=(0, 8))
        self._button(row2, "Verify Latest Debug", lambda: self._start_command("verify-latest-debug")).pack(side="left", padx=8)
        self._button(row2, "Open Debug Folder", lambda: open_path(self.root_path / "artifacts" / "debug")).pack(side="left", padx=8)
        self._button(row2, "Open Artifacts", lambda: open_path(self.root_path / "artifacts")).pack(side="left", padx=8)

    def _build_logs_page(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Logs", "Live command output is available here without flooding the main dashboard.")
        toolbar = tk.Frame(parent, bg=BG)
        toolbar.pack(fill="x", pady=(0, 8))
        self._button(toolbar, "Clear", self._clear_log, compact=True).pack(side="left", padx=(0, 6))
        self._button(toolbar, "Open Session Logs", lambda: open_path(self.root_path / "artifacts" / "logs" / "sessions"), compact=True).pack(side="left", padx=6)
        self._button(toolbar, "Open Latest Debug", self._open_latest_debug, compact=True).pack(side="left", padx=6)

        frame = self._panel(parent)
        frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(frame, bg="#07090b", fg=TEXT, insertbackground=TEXT, bd=0, relief="flat",
                                font=("Consolas", 9), wrap="word")
        scroll = tk.Scrollbar(frame, command=self.log_text.yview, bg=PANEL)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll.pack(side="right", fill="y", pady=10, padx=(0, 8))
        self.log_text.tag_configure("pass", foreground=GREEN)
        self.log_text.tag_configure("warn", foreground=YELLOW)
        self.log_text.tag_configure("fail", foreground=RED)
        self.log_text.tag_configure("info", foreground=CYAN)
        self.log_text.tag_configure("muted", foreground=MUTED)

    def _build_commands_page(self, parent: Any) -> None:
        tk = self.tk
        ttk = self.ttk
        self._section_title(parent, "Registered Commands", "Read-only view of project.control.json; execution policy remains in PCC Core.")
        panel = self._panel(parent)
        panel.pack(fill="both", expand=True)
        tree = ttk.Treeview(panel, columns=("key", "label", "risk", "program"), show="headings")
        for key, title, width in (("key", "Key", 190), ("label", "Label", 300), ("risk", "Risk", 120), ("program", "Program", 130)):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        for item in self.contract.commands:
            tree.insert("", "end", values=(item.key, item.label, item.risk, item.program))
        tree.pack(fill="both", expand=True, padx=10, pady=10)

    def _show_page(self, page: str) -> None:
        for name, frame in self._page_frames.items():
            frame.pack_forget()
            btn = self._nav_buttons.get(name)
            if btn:
                btn.configure(bg=PANEL, fg=TEXT)
        self._page_frames[page].pack(fill="both", expand=True)
        if page in self._nav_buttons:
            self._nav_buttons[page].configure(bg=PANEL_2, fg=CYAN)

    def _append_log(self, text: str, tag: str = "") -> None:
        # During early shell construction Logs page may not yet exist.
        widget = getattr(self, "log_text", None)
        if widget is None:
            return
        widget.configure(state="normal")
        widget.insert("end", text, tag)
        widget.see("end")
        widget.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _refresh_status_async(self) -> None:
        if self._busy:
            return
        self.refresh_btn.configure(state="disabled")
        self.footer.configure(text="[Status:Refreshing]", fg=CYAN)

        def work() -> None:
            try:
                status = self.backend.status()
                self._event_q.put(("status", status))
            except Exception as exc:
                self._event_q.put(("status-error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _set_status_card(self, key: str, text: str, color: str) -> None:
        label = self._status_values.get(key)
        if label:
            label.configure(text=text, fg=color)

    def _render_status(self, status: dict[str, Any]) -> None:
        self._last_status = status
        git = status.get("git") or {}
        patches = status.get("patches") or {}
        hygiene = status.get("hygiene") or {}
        binaries = status.get("binaries") or {}
        tools = status.get("tools") or {}

        if not git.get("gitReady"):
            git_text, git_color = "Not ready", RED
        elif git.get("clean"):
            git_text, git_color = "Clean", GREEN
        else:
            changed = int(git.get("staged", 0) or 0) + int(git.get("unstaged", 0) or 0) + int(git.get("untracked", 0) or 0)
            git_text, git_color = (f"Modified ({changed})" if changed else "Modified"), YELLOW
        self._set_status_card("Git", git_text, git_color)

        if git.get("greenMatch"):
            green_text, green_color = "MATCH", GREEN
        elif git.get("greenMarker"):
            green_text, green_color = "STALE", YELLOW
        else:
            green_text, green_color = "NONE", MUTED
        self._set_status_card("GREEN", green_text, green_color)

        invalid = int(patches.get("invalid", 0) or 0)
        pending = int(patches.get("pending", 0) or 0)
        if invalid:
            upd_text, upd_color = f"{invalid} invalid", RED
        elif pending:
            upd_text, upd_color = f"{pending} pending", YELLOW
        else:
            upd_text, upd_color = "0 pending", GREEN
        self._set_status_card("Updates", upd_text, upd_color)

        if hygiene.get("clean", True):
            self._set_status_card("Hygiene", "Clean", GREEN)
        else:
            self._set_status_card("Hygiene", f"{hygiene.get('violationCount', '?')} issue(s)", YELLOW)

        self._set_status_card("CLI", "Ready" if tools.get("python") else "Missing", GREEN if tools.get("python") else RED)
        self._set_status_card("Desktop", "Ready" if binaries.get("gui") else "Not built", GREEN if binaries.get("gui") else YELLOW)

        ahead = git.get("ahead")
        behind = git.get("behind")
        if ahead is None or behind is None:
            sync = "Unknown"
        elif int(ahead) == 0 and int(behind) == 0:
            sync = "MATCH"
        else:
            sync = f"{ahead} ahead / {behind} behind"

        lines = [
            f"Repository : {self.root_path}",
            f"Branch     : {git.get('branch') or '<none>'} @ {git.get('headShort') or '<unborn>'}",
            f"Git        : {git_text}",
            f"Sync       : {sync}",
            f"GREEN      : {green_text}",
            f"Updates    : {upd_text}",
            f"Hygiene    : {'Clean' if hygiene.get('clean', True) else 'Needs attention'}",
            f"Cargo      : {'Ready' if tools.get('cargo') else 'Missing'}",
            f"Rustc      : {'Ready' if tools.get('rustc') else 'Missing'}",
            f"GUI binary : {binaries.get('gui') or 'Not built'}",
            f"Active log : {(status.get('session') or {}).get('log') or '<not reported>'}",
        ]
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", "\n".join(lines))
        self.summary_text.configure(state="disabled")

        footer_parts = [
            f"Git:{git_text}", f"GREEN:{green_text}", f"Updates:{upd_text}",
            f"Hygiene:{'Clean' if hygiene.get('clean', True) else 'WARN'}",
        ]
        self.footer.configure(text="[" + "] [".join(footer_parts) + "]", fg=CYAN)
        self.refresh_btn.configure(state="normal")

    def _start_command(self, command: str, extra: Sequence[str] = (), *, label: str | None = None) -> None:
        if self._busy or (self._active_proc and self._active_proc.poll() is None):
            self.messagebox.showwarning("Project Control Center", "Another PCC job is already running.")
            return
        self._busy = True
        self._active_command = label or command
        self.operation_label.configure(text=f"Running: {self._active_command}", fg=CYAN)
        self.stop_btn.configure(state="normal")
        self.refresh_btn.configure(state="disabled")
        self._append_log(f"\n=== {datetime.now().strftime('%H:%M:%S')} START {self._active_command} ===\n", "info")
        self.footer.configure(text=f"[Job:Running] [{self._active_command}]", fg=CYAN)

        def work() -> None:
            try:
                proc = self.backend.popen(command, extra)
                self._active_proc = proc
                assert proc.stdout is not None
                for line in proc.stdout:
                    self._event_q.put(("log", line))
                rc = proc.wait()
                self._event_q.put(("done", (command, rc)))
            except Exception as exc:
                self._event_q.put(("command-error", (command, str(exc))))

        threading.Thread(target=work, daemon=True).start()

    def _stop_active(self) -> None:
        proc = self._active_proc
        if proc and proc.poll() is None:
            self.operation_label.configure(text=f"Stopping: {self._active_command}", fg=YELLOW)
            terminate_process_tree(proc)
            self._append_log("Cancellation requested by operator.\n", "warn")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self._event_q.get_nowait()
                if kind == "log":
                    line = str(payload)
                    up = line.upper()
                    tag = "fail" if ("FAIL" in up or "ERROR" in up) else ("warn" if "WARN" in up else ("pass" if "PASS" in up or "GREEN" in up else ""))
                    self._append_log(line, tag)
                elif kind == "done":
                    command, rc = payload
                    self._active_proc = None
                    self._busy = False
                    self.stop_btn.configure(state="disabled")
                    color = GREEN if rc == 0 else RED
                    state = "PASS" if rc == 0 else f"FAIL ({rc})"
                    self.operation_label.configure(text=f"Last: {command} {state}", fg=color)
                    self._append_log(f"=== END {command}: {state} ===\n", "pass" if rc == 0 else "fail")
                    self.footer.configure(text=f"[Last:{command}] [{state}]", fg=color)
                    self._refresh_status_async()
                    if rc != 0:
                        self._show_page("Logs")
                elif kind == "command-error":
                    command, detail = payload
                    self._active_proc = None
                    self._busy = False
                    self.stop_btn.configure(state="disabled")
                    self.operation_label.configure(text=f"Last: {command} FAIL", fg=RED)
                    self._append_log(f"ERROR: {detail}\n", "fail")
                    self.messagebox.showerror("PCC command failed", detail)
                    self._refresh_status_async()
                elif kind == "status":
                    self._render_status(payload)
                elif kind == "status-error":
                    self.refresh_btn.configure(state="normal")
                    self.footer.configure(text="[Status:Unavailable]", fg=RED)
                    self._append_log(f"Status refresh failed: {payload}\n", "fail")
        except queue.Empty:
            pass
        self.window.after(60, self._drain_events)

    def _commit_green(self) -> None:
        default = f"{self.contract.name} GREEN checkpoint - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        message = self.simpledialog.askstring("Commit certified GREEN", "Commit message:", initialvalue=default)
        if message:
            self._start_command("commit-green", ["--message", message], label="commit-green")

    def _commit_push_green(self) -> None:
        default = f"{self.contract.name} GREEN checkpoint - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        message = self.simpledialog.askstring("Commit + push certified GREEN", "Commit message:", initialvalue=default)
        if message and self.messagebox.askyesno("Commit + push", "Commit the current certified GREEN source and push it to the configured remote?"):
            self._start_command("commit-push-green", ["--message", message], label="commit-push-green")

    def _apply_updates(self) -> None:
        if self.messagebox.askyesno("Apply validated updates", "Apply the currently validated PCC patch queue? Invalid patches will remain fail-closed."):
            self._start_command("patch-apply", ["--yes"], label="apply-updates")

    def _open_latest_debug(self) -> None:
        path = latest_debug_bundle(self.root_path)
        if path:
            reveal_file(path)
        else:
            open_path(self.root_path / "artifacts" / "debug")

    def _open_cli(self) -> None:
        launcher = self.root_path / "PROJECT_CONTROL_CENTER.cmd"
        if os.name == "nt" and launcher.is_file():
            subprocess.Popen(["cmd.exe", "/k", str(launcher), "--cli"], cwd=str(self.root_path))
            return
        self.messagebox.showinfo("Project Control Center", f"CLI launcher: {launcher}")

    def _on_close(self) -> None:
        if self._active_proc and self._active_proc.poll() is None:
            if not self.messagebox.askyesno("Active PCC job", "A Project Control Center job is still running. Stop it and close?"):
                return
            terminate_process_tree(self._active_proc)
        self.window.destroy()

    def run(self) -> int:
        self.window.mainloop()
        return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Cortex Project Control Center GUI")
    p.add_argument("--root")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = resolve_root(args.root)
    if args.self_test:
        for note in validate_surface(root):
            print(f"PASS {note}")
        try:
            import tkinter as tk
            print(f"PASS tkinter={tk.TkVersion}")
        except Exception as exc:
            raise SurfaceError(f"Tkinter GUI runtime is unavailable: {exc}") from exc
        print(f"PASS gui-version={GUI_VERSION}")
        return 0
    return CortexPCCGui(root).run()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SurfaceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
