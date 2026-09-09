#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from PCCSurfaceCommon import (
    BackendClient,
    ProjectContract,
    ProjectRegistry,
    RegisteredProject,
    SurfaceError,
    compact_path,
    latest_debug_bundle,
    open_path,
    resolve_root,
    reveal_file,
    terminate_process_tree,
    validate_surface,
)

GUI_VERSION = "PCC-GUI-0.3"

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


class CortexPCCGui:
    def __init__(self, root: Path) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, simpledialog, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.simpledialog = simpledialog

        self.registry = ProjectRegistry()
        self.root_path = root.resolve()
        self.contract = ProjectContract.load(self.root_path)
        self.backend: BackendClient | None = None
        self.backend_error = ""
        self._bind_project_backend()
        self.registry.touch(self.root_path)

        self.window = tk.Tk()
        self.window.title(f"Project Control Center — {self.contract.name}")
        self.window.geometry("1280x860")
        self.window.minsize(1040, 720)
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._event_q: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._active_proc: subprocess.Popen[str] | None = None
        self._active_command = ""
        self._last_status: dict[str, Any] = {}
        self._page_frames: dict[str, Any] = {}
        self._status_values: dict[str, Any] = {}
        self._nav_buttons: dict[str, Any] = {}
        self._app_frames: dict[str, Any] = {}
        self._app_tab_buttons: dict[str, Any] = {}
        self._project_entries_by_id: dict[str, RegisteredProject] = {}
        self._busy = False

        self._configure_styles()
        self._build_shell()
        self._refresh_projects()
        self._show_page("Dashboard")
        self._show_app_tab("Projects")
        self._append_log(f"Project Control Center {GUI_VERSION} started.\n", "info")
        self._append_log(f"Active project: {self.contract.name} — {self.root_path}\n", "muted")
        self._refresh_status_async()
        self.window.after(60, self._drain_events)

    # ------------------------------------------------------------------
    # Shell / styling
    # ------------------------------------------------------------------
    def _configure_styles(self) -> None:
        ttk = self.ttk
        style = ttk.Style(self.window)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Treeview",
            background=PANEL_2,
            fieldbackground=PANEL_2,
            foreground=TEXT,
            rowheight=29,
            borderwidth=0,
        )
        style.configure("Treeview.Heading", background=PANEL, foreground=CYAN, relief="flat")
        style.map("Treeview", background=[("selected", "#21404a")], foreground=[("selected", TEXT)])
        style.configure("TProgressbar", troughcolor=PANEL_2, background=CYAN, borderwidth=0)

    def _build_shell(self) -> None:
        tk = self.tk

        header = tk.Frame(self.window, bg=BG, height=78)
        header.pack(fill="x", padx=22, pady=(14, 6))
        header.pack_propagate(False)

        title_block = tk.Frame(header, bg=BG)
        title_block.pack(side="left", fill="y")
        tk.Label(
            title_block,
            text="PROJECT CONTROL CENTER",
            bg=BG,
            fg=CYAN,
            font=("Segoe UI Semibold", 18),
        ).pack(anchor="w")
        self.active_project_label = tk.Label(
            title_block,
            text="",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        )
        self.active_project_label.pack(anchor="w", pady=(4, 0))
        self._update_header()

        header_actions = tk.Frame(header, bg=BG)
        header_actions.pack(side="right", fill="y")
        self.refresh_btn = self._button(header_actions, "Refresh", self._refresh_clicked, compact=True)
        self.refresh_btn.pack(side="left", padx=4, pady=12)
        self.cli_btn = self._button(header_actions, "Open Project CLI", self._open_cli, compact=True)
        self.cli_btn.pack(side="left", padx=4, pady=12)

        tk.Frame(self.window, bg=CYAN, height=1).pack(fill="x")

        tabs = tk.Frame(self.window, bg=PANEL, height=44)
        tabs.pack(fill="x")
        tabs.pack_propagate(False)
        for name in ("Projects", "Project Workspace"):
            btn = tk.Button(
                tabs,
                text=name,
                command=lambda n=name: self._show_app_tab(n),
                bg=PANEL,
                fg=TEXT,
                activebackground=PANEL_2,
                activeforeground=CYAN,
                bd=0,
                relief="flat",
                cursor="hand2",
                font=("Segoe UI Semibold", 10),
                padx=20,
                pady=8,
            )
            btn.pack(side="left", fill="y")
            self._app_tab_buttons[name] = btn

        self.app_content = tk.Frame(self.window, bg=BG)
        self.app_content.pack(fill="both", expand=True)
        for name in ("Projects", "Project Workspace"):
            frame = tk.Frame(self.app_content, bg=BG)
            self._app_frames[name] = frame

        self._build_projects_tab(self._app_frames["Projects"])
        self._build_workspace_tab(self._app_frames["Project Workspace"])

    def _build_projects_tab(self, parent: Any) -> None:
        tk = self.tk
        ttk = self.ttk

        shell = tk.Frame(parent, bg=BG)
        shell.pack(fill="both", expand=True, padx=20, pady=18)
        self._section_title(
            shell,
            "Registered Projects",
            "Universal PCC registry. Select a project to load its Project Workspace.",
        )

        toolbar = tk.Frame(shell, bg=BG)
        toolbar.pack(fill="x", pady=(0, 10))
        self._button(toolbar, "Register Project...", self._register_project, primary=True, compact=True).pack(side="left", padx=(0, 6))
        self._button(toolbar, "Open Project Workspace", self._open_selected_project, compact=True).pack(side="left", padx=6)
        self._button(toolbar, "Open Folder", self._open_selected_project_folder, compact=True).pack(side="left", padx=6)
        self._button(toolbar, "Remove Registration", self._remove_selected_project, compact=True, danger=True).pack(side="left", padx=6)
        self._button(toolbar, "Refresh List", self._refresh_projects, compact=True).pack(side="left", padx=6)

        panel = self._panel(shell)
        panel.pack(fill="both", expand=True)
        self.projects_tree = ttk.Treeview(
            panel,
            columns=("name", "kind", "root", "adapter", "last"),
            show="headings",
            selectmode="browse",
        )
        for key, title, width in (
            ("name", "Project", 190),
            ("kind", "Type", 140),
            ("root", "Repository / Root", 520),
            ("adapter", "PCC", 130),
            ("last", "Last Opened", 160),
        ):
            self.projects_tree.heading(key, text=title)
            self.projects_tree.column(key, width=width, anchor="w")
        self.projects_tree.tag_configure("ready", foreground=GREEN)
        self.projects_tree.tag_configure("adapter", foreground=YELLOW)
        self.projects_tree.tag_configure("missing", foreground=RED)
        scroll = tk.Scrollbar(panel, command=self.projects_tree.yview, bg=PANEL)
        self.projects_tree.configure(yscrollcommand=scroll.set)
        self.projects_tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=10)
        self.projects_tree.bind("<<TreeviewSelect>>", self._project_selection_changed)
        self.projects_tree.bind("<Double-1>", lambda _e: self._open_selected_project())

        detail = self._panel(shell, "Selected Project")
        detail.pack(fill="x", pady=(10, 0))
        self.project_detail = tk.Label(
            detail,
            text="Select a registered project.",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            font=("Consolas", 9),
        )
        self.project_detail.pack(fill="x", padx=14, pady=(4, 12))

    def _build_workspace_tab(self, parent: Any) -> None:
        tk = self.tk

        # A compact Havenwild-style project workspace occupies the upper region.
        upper = tk.Frame(parent, bg=BG)
        upper.pack(fill="both", expand=True)

        nav = tk.Frame(upper, bg=PANEL, width=190, highlightthickness=1, highlightbackground=BORDER)
        nav.pack(side="left", fill="y", padx=(18, 8), pady=(14, 8))
        nav.pack_propagate(False)
        tk.Label(nav, text="PROJECT OPERATIONS", bg=PANEL, fg=MUTED, font=("Segoe UI Semibold", 9)).pack(
            anchor="w", padx=16, pady=(16, 8)
        )
        for page in ("Dashboard", "Build & Run", "Updates", "Source Control", "Diagnostics", "Logs", "Registered Commands"):
            btn = tk.Button(
                nav,
                text=page,
                anchor="w",
                command=lambda p=page: self._show_page(p),
                bg=PANEL,
                fg=TEXT,
                activebackground=PANEL_2,
                activeforeground=CYAN,
                bd=0,
                relief="flat",
                font=("Segoe UI", 10),
                cursor="hand2",
                padx=16,
                pady=8,
            )
            btn.pack(fill="x", padx=2, pady=1)
            self._nav_buttons[page] = btn

        tk.Frame(nav, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(12, 9))
        self.operation_label = tk.Label(
            nav,
            text="Idle",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            wraplength=155,
            justify="left",
        )
        self.operation_label.pack(anchor="w", padx=16, pady=(0, 5))
        self.stop_btn = self._button(nav, "Stop Active Job", self._stop_active, compact=True, danger=True)
        self.stop_btn.pack(fill="x", padx=12, pady=(2, 8))
        self.stop_btn.configure(state="disabled")

        self.content = tk.Frame(upper, bg=BG)
        self.content.pack(side="left", fill="both", expand=True, padx=(8, 18), pady=(14, 8))

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

        # Persistent embedded console: every project operation streams here, including Full Gate.
        console = tk.Frame(parent, bg=PANEL, height=250, highlightthickness=1, highlightbackground=BORDER)
        console.pack(fill="x", padx=18, pady=(0, 6))
        console.pack_propagate(False)
        console_bar = tk.Frame(console, bg=PANEL)
        console_bar.pack(fill="x", padx=10, pady=(7, 4))
        tk.Label(console_bar, text="PROJECT CONSOLE", bg=PANEL, fg=CYAN, font=("Segoe UI Semibold", 9)).pack(side="left")
        tk.Label(console_bar, text=GUI_VERSION, bg=PANEL, fg=MUTED, font=("Consolas", 8)).pack(side="left", padx=(8, 0))
        self.console_job_label = tk.Label(console_bar, text="Idle", bg=PANEL, fg=MUTED, font=("Segoe UI", 9))
        self.console_job_label.pack(side="left", padx=(12, 0))
        self._button(console_bar, "Copy All", lambda: self._copy_all(self.console_text), compact=True).pack(side="right", padx=(6, 0))
        self._button(console_bar, "Copy Selection", lambda: self._copy_selection(self.console_text), compact=True).pack(side="right", padx=(6, 0))
        self._button(console_bar, "Clear", self._clear_log, compact=True).pack(side="right", padx=(6, 0))
        self._button(console_bar, "Open Active Log", self._open_active_log, compact=True).pack(side="right", padx=(6, 0))

        console_body = tk.Frame(console, bg="#07090b")
        console_body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.console_text = tk.Text(
            console_body,
            bg="#07090b",
            fg=TEXT,
            insertbackground=TEXT,
            bd=0,
            relief="flat",
            font=("Consolas", 9),
            wrap="word",
        )
        cscroll = tk.Scrollbar(console_body, command=self.console_text.yview, bg=PANEL)
        self.console_text.configure(yscrollcommand=cscroll.set)
        self.console_text.pack(side="left", fill="both", expand=True)
        cscroll.pack(side="right", fill="y")
        self._configure_log_tags(self.console_text)

        statusbar = tk.Frame(parent, bg="#07090b", height=28, highlightthickness=1, highlightbackground="#20262d")
        statusbar.pack(fill="x", side="bottom")
        statusbar.pack_propagate(False)
        self.footer = tk.Label(statusbar, text="[Status:Loading]", bg="#07090b", fg=CYAN, font=("Consolas", 9), anchor="w")
        self.footer.pack(fill="both", padx=12)

    def _panel(self, parent: Any, title: str | None = None) -> Any:
        tk = self.tk
        frame = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        if title:
            tk.Label(frame, text=title, bg=PANEL, fg=CYAN, font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=14, pady=(12, 6))
        return frame

    def _button(
        self,
        parent: Any,
        text: str,
        command: Callable[[], None],
        *,
        primary: bool = False,
        compact: bool = False,
        danger: bool = False,
    ) -> Any:
        tk = self.tk
        bg = CYAN if primary else (RED if danger else PANEL_2)
        fg = "#001018" if primary else TEXT
        active = "#52e7ff" if primary else ("#ff7a83" if danger else "#24303a")
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            bd=0,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold" if primary else "Segoe UI", 10),
            padx=12 if compact else 18,
            pady=6 if compact else 10,
        )

    def _section_title(self, parent: Any, title: str, subtitle: str = "") -> None:
        tk = self.tk
        tk.Label(parent, text=title, bg=BG, fg=TEXT, font=("Segoe UI Semibold", 16)).pack(anchor="w")
        if subtitle:
            tk.Label(parent, text=subtitle, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 12))

    # ------------------------------------------------------------------
    # Project workspace pages
    # ------------------------------------------------------------------
    def _build_dashboard(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Project Health", "Compact operational summary backed by the selected project's PCC authority.")

        cards = tk.Frame(parent, bg=BG)
        cards.pack(fill="x")
        labels = ["Git", "GREEN", "Updates", "Hygiene", "PCC", "Runtime"]
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
        self.summary_text = tk.Text(summary, bg=PANEL, fg=TEXT, insertbackground=TEXT, bd=0, relief="flat", font=("Consolas", 10), height=10, wrap="word")
        self.summary_text.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        self.summary_text.configure(state="disabled")

    def _build_build_page(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Build & Run", "Project operations stream into the embedded Project Console below.")
        panel = self._panel(parent, "Build")
        panel.pack(fill="x")
        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill="x", padx=14, pady=14)
        self._button(row, "Build Debug", lambda: self._start_command("build"), primary=True).pack(side="left", padx=(0, 8))
        self._button(row, "Build Release", lambda: self._start_command("build-release")).pack(side="left", padx=8)
        self._button(row, "Quick Gate", lambda: self._start_command("quick")).pack(side="left", padx=8)
        self._button(row, "Fast Gate", lambda: self._start_command("fast")).pack(side="left", padx=8)

        run_panel = self._panel(parent, "Run")
        run_panel.pack(fill="x", pady=(12, 0))
        row2 = tk.Frame(run_panel, bg=PANEL)
        row2.pack(fill="x", padx=14, pady=14)
        self._button(row2, "Launch Project Runtime", lambda: self._start_command("launch-gui"), primary=True).pack(side="left", padx=(0, 8))
        self._button(row2, "Open Project Folder", lambda: open_path(self.root_path)).pack(side="left", padx=8)

    def _build_updates_page(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Updates", "Fail-closed update authority with explicit apply and recovery evidence.")
        panel = self._panel(parent, "Update Queue")
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
        patch_root = lambda: self.root_path / "artifacts" / "patches"
        self._button(r2, "Applied", lambda: open_path(patch_root() / "applied")).pack(side="left", padx=(0, 8))
        self._button(r2, "Failed", lambda: open_path(patch_root() / "failed")).pack(side="left", padx=8)
        self._button(r2, "Receipts", lambda: open_path(patch_root() / "receipts")).pack(side="left", padx=8)
        self._button(r2, "Backups", lambda: open_path(patch_root() / "backups")).pack(side="left", padx=8)

    def _build_source_page(self, parent: Any) -> None:
        tk = self.tk
        self._section_title(parent, "Source Control", "GREEN-gated source control remains behind the selected project's PCC authority.")
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
        self._section_title(parent, "Diagnostics & Recovery", "Detailed evidence stays in artifacts/logs while live progress remains visible below.")
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
        self._section_title(parent, "Logs", "Expanded live view. The same stream remains visible in the Project Console at all times.")
        toolbar = tk.Frame(parent, bg=BG)
        toolbar.pack(fill="x", pady=(0, 8))
        self._button(toolbar, "Copy All", lambda: self._copy_all(self.log_text), primary=True, compact=True).pack(side="left", padx=(0, 6))
        self._button(toolbar, "Copy Selection", lambda: self._copy_selection(self.log_text), compact=True).pack(side="left", padx=6)
        self._button(toolbar, "Clear", self._clear_log, compact=True).pack(side="left", padx=6)
        self._button(toolbar, "Open Active Log", self._open_active_log, compact=True).pack(side="left", padx=6)
        self._button(toolbar, "Open Session Logs", lambda: open_path(self.root_path / "artifacts" / "logs" / "sessions"), compact=True).pack(side="left", padx=6)
        self._button(toolbar, "Open Latest Debug", self._open_latest_debug, compact=True).pack(side="left", padx=6)

        frame = self._panel(parent)
        frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(frame, bg="#07090b", fg=TEXT, insertbackground=TEXT, bd=0, relief="flat", font=("Consolas", 9), wrap="word")
        scroll = tk.Scrollbar(frame, command=self.log_text.yview, bg=PANEL)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll.pack(side="right", fill="y", pady=10, padx=(0, 8))
        self._configure_log_tags(self.log_text)

    def _build_commands_page(self, parent: Any) -> None:
        ttk = self.ttk
        self._section_title(parent, "Registered Commands", "Project contract commands. Execution policy remains in the PCC Core / project adapter.")
        panel = self._panel(parent)
        panel.pack(fill="both", expand=True)
        self.commands_tree = ttk.Treeview(panel, columns=("key", "label", "risk", "program"), show="headings")
        for key, title, width in (("key", "Key", 190), ("label", "Label", 300), ("risk", "Risk", 120), ("program", "Program", 130)):
            self.commands_tree.heading(key, text=title)
            self.commands_tree.column(key, width=width, anchor="w")
        self.commands_tree.pack(fill="both", expand=True, padx=10, pady=10)
        self._reload_registered_commands()

    # ------------------------------------------------------------------
    # App / project navigation
    # ------------------------------------------------------------------
    def _show_app_tab(self, name: str) -> None:
        for key, frame in self._app_frames.items():
            frame.pack_forget()
            btn = self._app_tab_buttons.get(key)
            if btn:
                btn.configure(bg=PANEL, fg=TEXT)
        self._app_frames[name].pack(fill="both", expand=True)
        self._app_tab_buttons[name].configure(bg=PANEL_2, fg=CYAN)

    def _show_page(self, page: str) -> None:
        for name, frame in self._page_frames.items():
            frame.pack_forget()
            btn = self._nav_buttons.get(name)
            if btn:
                btn.configure(bg=PANEL, fg=TEXT)
        self._page_frames[page].pack(fill="both", expand=True)
        if page in self._nav_buttons:
            self._nav_buttons[page].configure(bg=PANEL_2, fg=CYAN)

    def _bind_project_backend(self) -> None:
        try:
            self.backend = BackendClient(self.root_path, self.contract)
            self.backend_error = ""
        except SurfaceError as exc:
            self.backend = None
            self.backend_error = str(exc)

    def _activate_project(self, root: Path) -> None:
        if self._busy:
            self.messagebox.showwarning("Project Control Center", "Finish or stop the active PCC job before switching projects.")
            return
        try:
            contract = ProjectContract.load(root.resolve())
        except Exception as exc:
            self.messagebox.showerror("Project Control Center", f"Unable to load project:\n{root}\n\n{exc}")
            return
        self.root_path = root.resolve()
        self.contract = contract
        self._bind_project_backend()
        self.registry.touch(self.root_path)
        self._last_status = {}
        self._update_header()
        self._reload_registered_commands()
        self._reset_status_cards()
        self._clear_log()
        self._append_log(f"Active project changed to {self.contract.name}.\n", "info")
        self._append_log(f"Root: {self.root_path}\n", "muted")
        if self.backend_error:
            self._append_log(f"PCC adapter: {self.backend_error}\n", "warn")
            self._render_adapter_unavailable()
        else:
            self._refresh_status_async()
        self._show_page("Dashboard")
        self._show_app_tab("Project Workspace")
        self._refresh_projects()

    def _update_header(self) -> None:
        if not hasattr(self, "active_project_label"):
            return
        adapter = "PCC adapter ready" if self.backend is not None else "adapter standardization required"
        self.active_project_label.configure(
            text=f"Active: {self.contract.name}  •  {self.contract.kind}  •  {compact_path(self.root_path, 88)}  •  {adapter}"
        )
        self.window.title(f"Project Control Center — {self.contract.name}")

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def _refresh_projects(self) -> None:
        if not hasattr(self, "projects_tree"):
            return
        self._project_entries_by_id.clear()
        for iid in self.projects_tree.get_children():
            self.projects_tree.delete(iid)
        try:
            entries = self.registry.entries()
        except Exception as exc:
            self.messagebox.showerror("Project Registry", str(exc))
            return
        for entry in entries:
            self._project_entries_by_id[entry.registry_id] = entry
            tag = "ready"
            adapter_text = "Ready"
            if not entry.root.is_dir():
                tag, adapter_text = "missing", "Missing root"
            else:
                try:
                    contract = ProjectContract.load(entry.root)
                    BackendClient(entry.root, contract)
                except SurfaceError:
                    tag, adapter_text = "adapter", "Needs adapter"
                except Exception:
                    tag, adapter_text = "missing", "Invalid"
            last = entry.last_opened_utc.replace("T", " ")[:19] if entry.last_opened_utc else "—"
            self.projects_tree.insert(
                "",
                "end",
                iid=entry.registry_id,
                values=(entry.name, entry.kind, str(entry.root), adapter_text, last),
                tags=(tag,),
            )
        current_id = ProjectRegistry._registry_id(self.root_path)
        if current_id in self._project_entries_by_id:
            self.projects_tree.selection_set(current_id)
            self.projects_tree.focus(current_id)
            self._project_selection_changed()

    def _selected_project(self) -> RegisteredProject | None:
        sel = self.projects_tree.selection()
        if not sel:
            return None
        return self._project_entries_by_id.get(sel[0])

    def _project_selection_changed(self, _event: Any = None) -> None:
        entry = self._selected_project()
        if entry is None:
            self.project_detail.configure(text="Select a registered project.", fg=MUTED)
            return
        adapter = "Ready"
        detail_color = TEXT
        try:
            contract = ProjectContract.load(entry.root)
            backend = BackendClient(entry.root, contract)
            provider = str(backend.script)
        except Exception as exc:
            adapter = "Needs standardization"
            provider = str(exc)
            detail_color = YELLOW if entry.root.exists() else RED
        self.project_detail.configure(
            text=(
                f"Project    : {entry.name}\n"
                f"Type       : {entry.kind}\n"
                f"Root       : {entry.root}\n"
                f"PCC        : {adapter}\n"
                f"Provider   : {provider}"
            ),
            fg=detail_color,
        )

    def _register_project(self) -> None:
        raw = self.filedialog.askdirectory(title="Register Project Root")
        if not raw:
            return
        try:
            entry = self.registry.register(Path(raw), make_active=False)
        except Exception as exc:
            self.messagebox.showerror(
                "Register Project",
                f"This folder cannot be registered yet. A standardized project.control.json is required.\n\n{exc}",
            )
            return
        self._refresh_projects()
        if entry.registry_id in self._project_entries_by_id:
            self.projects_tree.selection_set(entry.registry_id)
            self.projects_tree.focus(entry.registry_id)
            self._project_selection_changed()

    def _remove_selected_project(self) -> None:
        entry = self._selected_project()
        if entry is None:
            return
        if entry.root.resolve() == self.root_path.resolve():
            if not self.messagebox.askyesno("Remove Registration", f"Remove the active project '{entry.name}' from the registry? This does not delete any project files."):
                return
        elif not self.messagebox.askyesno("Remove Registration", f"Remove '{entry.name}' from the PCC registry? This does not delete any project files."):
            return
        self.registry.remove(entry.registry_id)
        self._refresh_projects()

    def _open_selected_project(self) -> None:
        entry = self._selected_project()
        if entry is None:
            self.messagebox.showinfo("Projects", "Select a project first.")
            return
        self._activate_project(entry.root)

    def _open_selected_project_folder(self) -> None:
        entry = self._selected_project()
        if entry:
            open_path(entry.root)

    # ------------------------------------------------------------------
    # Live output / clipboard
    # ------------------------------------------------------------------
    def _configure_log_tags(self, widget: Any) -> None:
        widget.tag_configure("pass", foreground=GREEN)
        widget.tag_configure("warn", foreground=YELLOW)
        widget.tag_configure("fail", foreground=RED)
        widget.tag_configure("info", foreground=CYAN)
        widget.tag_configure("muted", foreground=MUTED)

    def _append_log(self, text: str, tag: str = "") -> None:
        for widget_name in ("console_text", "log_text"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.insert("end", text, tag)
            widget.see("end")
            widget.configure(state="disabled")

    def _clear_log(self) -> None:
        for widget_name in ("console_text", "log_text"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")

    def _copy_to_clipboard(self, text: str, label: str) -> None:
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update_idletasks()
        if hasattr(self, "footer"):
            self.footer.configure(text=f"[Copied:{label}] [{len(text)} chars]", fg=GREEN)

    def _copy_all(self, widget: Any) -> None:
        text = widget.get("1.0", "end-1c")
        if not text:
            self.messagebox.showinfo("Copy Console", "There is no console output to copy.")
            return
        self._copy_to_clipboard(text, "All Console Output")

    def _copy_selection(self, widget: Any) -> None:
        try:
            text = widget.get("sel.first", "sel.last")
        except self.tk.TclError:
            self.messagebox.showinfo("Copy Selection", "Select console text first, or use Copy All.")
            return
        self._copy_to_clipboard(text, "Console Selection")

    def _open_active_log(self) -> None:
        raw = str(((self._last_status.get("session") or {}).get("log") or "")).strip()
        if raw:
            path = Path(raw)
            if path.exists():
                reveal_file(path)
                return
        open_path(self.root_path / "artifacts" / "logs" / "sessions")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def _refresh_clicked(self) -> None:
        self._refresh_projects()
        self._refresh_status_async()

    def _refresh_status_async(self) -> None:
        if self._busy:
            return
        if self.backend is None:
            self._render_adapter_unavailable()
            return
        self.refresh_btn.configure(state="disabled")
        self.footer.configure(text="[Status:Refreshing]", fg=CYAN)

        def work() -> None:
            try:
                status = self.backend.status() if self.backend is not None else {}
                self._event_q.put(("status", status))
            except Exception as exc:
                self._event_q.put(("status-error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _set_status_card(self, key: str, text: str, color: str) -> None:
        label = self._status_values.get(key)
        if label:
            label.configure(text=text, fg=color)

    def _reset_status_cards(self) -> None:
        for key in self._status_values:
            self._set_status_card(key, "Loading", CYAN)

    def _render_adapter_unavailable(self) -> None:
        self._set_status_card("Git", "Unknown", MUTED)
        self._set_status_card("GREEN", "Unknown", MUTED)
        self._set_status_card("Updates", "Unknown", MUTED)
        self._set_status_card("Hygiene", "Unknown", MUTED)
        self._set_status_card("PCC", "Needs adapter", YELLOW)
        self._set_status_card("Runtime", "Unknown", MUTED)
        lines = [
            f"Repository : {self.root_path}",
            f"Project    : {self.contract.name}",
            f"Type       : {self.contract.kind}",
            "PCC        : Needs standardized machine provider",
            f"Detail     : {self.backend_error or 'No provider detected'}",
        ]
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", "\n".join(lines))
        self.summary_text.configure(state="disabled")
        self.footer.configure(text="[PCC:Needs Adapter]", fg=YELLOW)
        self.refresh_btn.configure(state="normal")

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

        self._set_status_card("PCC", "Ready", GREEN)
        runtime_ready = bool(binaries.get("gui"))
        self._set_status_card("Runtime", "Ready" if runtime_ready else "Not built", GREEN if runtime_ready else YELLOW)

        ahead = git.get("ahead")
        behind = git.get("behind")
        if ahead is None or behind is None:
            sync = "Unknown"
        elif int(ahead) == 0 and int(behind) == 0:
            sync = "MATCH"
        else:
            sync = f"{ahead} ahead / {behind} behind"

        provider = str(self.backend.script.relative_to(self.root_path)) if self.backend is not None else "Unavailable"
        lines = [
            f"Repository : {self.root_path}",
            f"Project    : {self.contract.name}",
            f"Branch     : {git.get('branch') or '<none>'} @ {git.get('headShort') or '<unborn>'}",
            f"Git        : {git_text}",
            f"Sync       : {sync}",
            f"GREEN      : {green_text}",
            f"Updates    : {upd_text}",
            f"Hygiene    : {'Clean' if hygiene.get('clean', True) else 'Needs attention'}",
            f"PCC        : {provider}",
            f"Cargo      : {'Ready' if tools.get('cargo') else 'Missing'}",
            f"Rustc      : {'Ready' if tools.get('rustc') else 'Missing'}",
            f"Runtime    : {binaries.get('gui') or 'Not built / not reported'}",
            f"Active log : {(status.get('session') or {}).get('log') or '<not reported>'}",
        ]
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", "\n".join(lines))
        self.summary_text.configure(state="disabled")

        self.footer.configure(
            text="[" + "] [".join([f"Git:{git_text}", f"GREEN:{green_text}", f"Updates:{upd_text}", f"Hygiene:{'Clean' if hygiene.get('clean', True) else 'WARN'}"]) + "]",
            fg=CYAN,
        )
        self.refresh_btn.configure(state="normal")

    def _reload_registered_commands(self) -> None:
        if not hasattr(self, "commands_tree"):
            return
        for iid in self.commands_tree.get_children():
            self.commands_tree.delete(iid)
        for item in self.contract.commands:
            self.commands_tree.insert("", "end", values=(item.key, item.label, item.risk, item.program))

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _start_command(self, command: str, extra: Sequence[str] = (), *, label: str | None = None) -> None:
        if self.backend is None:
            self.messagebox.showwarning(
                "Project Control Center",
                "This registered project does not yet expose the standardized Python PCC machine provider required for universal operations.",
            )
            return
        if self._busy or (self._active_proc and self._active_proc.poll() is None):
            self.messagebox.showwarning("Project Control Center", "Another PCC job is already running.")
            return
        self._show_app_tab("Project Workspace")
        # The embedded project console is the authoritative visible execution surface.
        # Never require an external console window to understand gate/build/Git progress.
        if hasattr(self, "console_text"):
            self.console_text.see("end")
            self.console_text.focus_set()
        self._busy = True
        self._active_command = label or command
        self.operation_label.configure(text=f"Running: {self._active_command}", fg=CYAN)
        self.console_job_label.configure(text=f"Running: {self._active_command}", fg=CYAN)
        self.stop_btn.configure(state="normal")
        self.refresh_btn.configure(state="disabled")
        self._append_log(f"\n=== {datetime.now().strftime('%H:%M:%S')} START {self._active_command} ===\n", "info")
        self.footer.configure(text=f"[Job:Running] [{self._active_command}]", fg=CYAN)

        def work() -> None:
            try:
                backend = self.backend
                if backend is None:
                    raise SurfaceError("PCC backend became unavailable.")
                proc = backend.popen(command, extra)
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
            self.console_job_label.configure(text=f"Stopping: {self._active_command}", fg=YELLOW)
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
                    self.console_job_label.configure(text=f"Last: {command} {state}", fg=color)
                    self._append_log(f"=== END {command}: {state} ===\n", "pass" if rc == 0 else "fail")
                    self.footer.configure(text=f"[Last:{command}] [{state}]", fg=color)
                    self._refresh_status_async()
                elif kind == "command-error":
                    command, detail = payload
                    self._active_proc = None
                    self._busy = False
                    self.stop_btn.configure(state="disabled")
                    self.operation_label.configure(text=f"Last: {command} FAIL", fg=RED)
                    self.console_job_label.configure(text=f"Last: {command} FAIL", fg=RED)
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

    def _latest_applied_patch_identity(self) -> tuple[str, str] | None:
        """Return the newest successfully applied patch identity for commit-message carry-forward."""
        receipts = self.root_path / "artifacts" / "patches" / "receipts"
        if not receipts.is_dir():
            return None
        candidates: list[tuple[float, str, str]] = []
        for path in receipts.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if str(data.get("status") or "").strip().casefold() != "applied":
                continue
            patch_id = str(data.get("patchId") or "").strip()
            if not patch_id:
                continue
            title = str(data.get("title") or "").strip()
            try:
                stamp = path.stat().st_mtime
            except OSError:
                stamp = 0.0
            candidates.append((stamp, patch_id, title))
        if not candidates:
            return None
        _stamp, patch_id, title = max(candidates, key=lambda row: row[0])
        return patch_id, title

    def _green_commit_default(self) -> tuple[str, str]:
        patch = self._latest_applied_patch_identity()
        if patch:
            patch_id, title = patch
            subject = f"{self.contract.name} GREEN {patch_id}"
            if title:
                subject += f" - {title}"
            return subject, f"Current applied patch: {patch_id}" + (f" — {title}" if title else "")
        marker = self.root_path / ".cortex" / "last-green-quality-gate.json"
        if marker.is_file():
            try:
                data = json.loads(marker.read_text(encoding="utf-8-sig"))
                head = str(data.get("gitHead") or "").strip()[:12]
                created = str(data.get("createdUtc") or "").strip()
                basis = "Current certified GREEN source"
                if head:
                    basis += f" @ {head}"
                if created:
                    basis += f" ({created})"
                return f"{self.contract.name} GREEN checkpoint - {datetime.now().strftime('%Y-%m-%d %H:%M')}", basis
            except Exception:
                pass
        return (
            f"{self.contract.name} GREEN checkpoint - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "Current certified GREEN source",
        )

    def _ask_commit_message(self, *, push: bool) -> str | None:
        tk = self.tk
        default, basis = self._green_commit_default()
        dialog = tk.Toplevel(self.window)
        dialog.title("Commit + Push Certified GREEN" if push else "Commit Certified GREEN")
        dialog.configure(bg=BG)
        dialog.transient(self.window)
        dialog.resizable(True, True)
        dialog.geometry("760x360")
        dialog.minsize(620, 300)

        shell = tk.Frame(dialog, bg=BG)
        shell.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(
            shell,
            text="Commit Certified GREEN",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 15),
        ).pack(anchor="w")
        tk.Label(
            shell,
            text=basis,
            bg=BG,
            fg=GREEN,
            font=("Segoe UI", 9),
            wraplength=710,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))
        tk.Label(shell, text="Commit message", bg=BG, fg=MUTED, font=("Segoe UI Semibold", 9)).pack(anchor="w")

        editor_frame = tk.Frame(shell, bg="#07090b", highlightthickness=1, highlightbackground=BORDER)
        editor_frame.pack(fill="both", expand=True, pady=(5, 12))
        editor = tk.Text(
            editor_frame,
            bg="#07090b",
            fg=TEXT,
            insertbackground=TEXT,
            bd=0,
            relief="flat",
            font=("Consolas", 10),
            wrap="word",
            undo=True,
            height=7,
        )
        scroll = tk.Scrollbar(editor_frame, command=editor.yview, bg=PANEL)
        editor.configure(yscrollcommand=scroll.set)
        editor.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll.pack(side="right", fill="y", padx=(4, 8), pady=8)
        editor.insert("1.0", default)
        editor.tag_add("sel", "1.0", "end-1c")
        editor.focus_set()

        result: list[str | None] = [None]

        def accept() -> None:
            message = editor.get("1.0", "end-1c").strip()
            if not message:
                self.messagebox.showwarning("Commit Certified GREEN", "Enter a commit message.", parent=dialog)
                return
            result[0] = message
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        actions = tk.Frame(shell, bg=BG)
        actions.pack(fill="x")
        self._button(actions, "Cancel", cancel, compact=True).pack(side="right", padx=(8, 0))
        self._button(
            actions,
            "Commit + Push GREEN" if push else "Commit GREEN",
            accept,
            primary=True,
            compact=True,
        ).pack(side="right")

        dialog.bind("<Escape>", lambda _e: cancel())
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.grab_set()
        self.window.wait_window(dialog)
        return result[0]

    def _commit_green(self) -> None:
        message = self._ask_commit_message(push=False)
        if message:
            self._start_command("commit-green", ["--message", message], label="commit-green")

    def _commit_push_green(self) -> None:
        message = self._ask_commit_message(push=True)
        if message and self.messagebox.askyesno(
            "Commit + push",
            "Commit the current certified GREEN source and push it to the configured remote?",
        ):
            self._start_command("commit-push-green", ["--message", message], label="commit-push-green")

    def _apply_updates(self) -> None:
        if self.messagebox.askyesno("Apply validated updates", "Apply the currently validated PCC update queue? Invalid updates remain fail-closed."):
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
        self.messagebox.showinfo("Project Control Center", f"Project CLI launcher not found: {launcher}")

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
    p = argparse.ArgumentParser(description="Universal Project Control Center GUI")
    p.add_argument("--root")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = resolve_root(args.root)
    if args.self_test:
        for note in validate_surface(root):
            print(f"PASS {note}")
        registry = ProjectRegistry()
        registry.register(root, make_active=False)
        print(f"PASS registry={registry.path}")
        print(f"PASS registered-projects={len(registry.entries())}")
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
