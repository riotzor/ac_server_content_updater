from __future__ import annotations

import functools
import logging
import os
import subprocess
import tempfile
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import paramiko

from ac_updater._logging import setup_logging
from ac_updater.ac_finder import find_ac_install
from ac_updater.archiver import create_archive
from ac_updater.content_copier import CopyResult, copy_to_share
from ac_updater.content_scanner import scan_content
from ac_updater.gui.nextcloud_panel import open_connect_dialog, open_file_browser
from ac_updater.install_config import load_install_dir, save_install_dir
from ac_updater.nextcloud_client import NextcloudClient
from ac_updater.selection_store import save_selection
from ac_updater.server_names import get_display_name
from ac_updater.share_config import load_share_path, save_share_path
from ac_updater.ssh_client import _AC_HOME, DeployResult, SshClient
from ac_updater.ssh_config import load_ssh_config, save_ssh_config

log = logging.getLogger(__name__)

_SELECTION_FILE = Path("selections") / "selection.txt"
_WINDOW_TITLE = "AC Server Content Updater"
_WINDOW_SIZE = "1060x680"

_GREEN = "#27ae60"
_RED = "#c0392b"
_ORANGE = "#e67e00"
_GRAY = "gray"


class _ChecklistPanel(ttk.LabelFrame):
    """Scrollable checklist for a single content category."""

    def __init__(self, parent: tk.Widget, title: str, items: list[str]) -> None:
        super().__init__(parent, text=title, padding=4)
        self._vars: dict[str, tk.BooleanVar] = {}

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", pady=(0, 4))
        ttk.Button(btn_row, text="Select All", command=self._select_all).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(btn_row, text="Deselect All", command=self._deselect_all).pack(side="left")

        self._canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._inner = ttk.Frame(self._canvas)

        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        win_id = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>", lambda e: self._canvas.itemconfig(win_id, width=e.width)
        )

        for item in items:
            var = tk.BooleanVar(value=False)
            self._vars[item] = var
            ttk.Checkbutton(self._inner, text=item, variable=var).pack(anchor="w", pady=1)

    def _select_all(self) -> None:
        for var in self._vars.values():
            var.set(True)

    def _deselect_all(self) -> None:
        for var in self._vars.values():
            var.set(False)

    def set_items(self, items: list[str], default_checked: bool = False) -> None:
        """Replace the item list, clearing all previous entries."""
        for widget in self._inner.winfo_children():
            widget.destroy()
        self._vars.clear()
        for item in items:
            var = tk.BooleanVar(value=default_checked)
            self._vars[item] = var
            ttk.Checkbutton(self._inner, text=item, variable=var).pack(anchor="w", pady=1)
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def get_selected(self) -> list[str]:
        return [name for name, var in self._vars.items() if var.get()]


class _App(tk.Tk):
    def __init__(self, install_dir: Path, content: dict[str, list[str]]) -> None:
        super().__init__()
        self.title(_WINDOW_TITLE)
        self.geometry(_WINDOW_SIZE)
        self.resizable(True, True)
        self._install_dir = install_dir
        self._share_path = load_share_path()
        self._nc_client: NextcloudClient | None = None
        self._panels: dict[str, _ChecklistPanel] = {}
        self._ssh_client: SshClient | None = None
        self._ssh_server_map: dict[str, str] = {}
        self._ssh_panels: dict[str, _ChecklistPanel] = {}
        self._current_server_name: str = ""

        log.info("App window created: install_dir=%s  share=%s", install_dir, self._share_path)

        self._build_header()
        self._build_notebook(content)
        self._build_footer()

    # ------------------------------------------------------------------
    # Layout — header (always visible)
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(10, 8, 10, 4))
        header.pack(fill="x")

        ttk.Label(header, text="AC Install:", font=("", 9, "bold")).pack(side="left")
        self._install_path_label = ttk.Label(header, text=str(self._install_dir))
        self._install_path_label.pack(side="left", padx=(6, 4))
        ttk.Button(header, text="Change...", command=self._on_change_dir).pack(side="left")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=10)

    # ------------------------------------------------------------------
    # Layout — notebook with four tabs
    # ------------------------------------------------------------------

    def _build_notebook(self, content: dict[str, list[str]]) -> None:
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        tab1 = ttk.Frame(self._nb, padding=6)
        tab2 = ttk.Frame(self._nb, padding=12)
        tab3 = ttk.Frame(self._nb, padding=12)
        tab4 = ttk.Frame(self._nb, padding=12)

        self._nb.add(tab1, text="  Content Browser  ")
        self._nb.add(tab2, text="  Server Manager  ")
        self._nb.add(tab3, text="  Nextcloud  ")
        self._nb.add(tab4, text="  Archive  ")

        self._build_content_tab(tab1, content)
        self._build_server_tab(tab2)
        self._build_nextcloud_tab(tab3)
        self._build_archive_tab(tab4)

        self._nb.select(1)  # Server Manager is the default tab
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _build_content_tab(self, parent: ttk.Frame, content: dict[str, list[str]]) -> None:
        self._panel_area = ttk.Frame(parent)
        self._panel_area.pack(fill="both", expand=True)
        self._build_panels(content)

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Save Selection", command=self._on_save).pack(side="right")

    def _build_panels(self, content: dict[str, list[str]]) -> None:
        for category, items in content.items():
            panel = _ChecklistPanel(self._panel_area, title=category.title(), items=items)
            panel.pack(side="left", fill="both", expand=True, padx=(0, 4))
            self._panels[category] = panel

    def _build_server_tab(self, parent: ttk.Frame) -> None:
        ssh_host, ssh_user, ssh_key = load_ssh_config()

        # ── Share copy section ──────────────────────────────────────────────
        share_row = ttk.Frame(parent)
        share_row.pack(fill="x", pady=(0, 12))
        ttk.Label(share_row, text="Network Share:", font=("", 9, "bold")).pack(side="left")
        self._share_path_label = ttk.Label(share_row, text=str(self._share_path))
        self._share_path_label.pack(side="left", padx=(6, 4))
        ttk.Button(share_row, text="Change...", command=self._on_change_share).pack(side="left")

        # Selected content summary (refreshed from the Content Browser)
        sel_lf = ttk.LabelFrame(parent, text="Content Browser selection", padding=4)
        sel_lf.pack(fill="x", pady=(0, 6))
        self._selection_text = tk.Text(
            sel_lf,
            height=3,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
            relief="flat",
        )
        self._selection_text.pack(fill="x")
        self._refresh_selection_display()

        self._server_btn = ttk.Button(
            parent, text="Copy to Share", command=self._on_server_update
        )
        self._server_btn.pack(anchor="w", pady=(0, 14))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(0, 8))

        lbl_row = ttk.Frame(parent)
        lbl_row.pack(fill="x", pady=(0, 4))
        ttk.Label(lbl_row, text="Results", font=("", 9, "bold")).pack(side="left")
        ttk.Button(lbl_row, text="Clear", command=self._clear_server_results).pack(side="right")

        result_frame = ttk.Frame(parent, relief="sunken", borderwidth=1)
        result_frame.pack(fill="x")
        self._server_result = tk.Text(
            result_frame,
            height=5,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
        )
        sb = ttk.Scrollbar(result_frame, command=self._server_result.yview)
        self._server_result.configure(yscrollcommand=sb.set)
        self._server_result.tag_configure("error", foreground=_RED)
        self._server_result.tag_configure("warn", foreground=_ORANGE)
        self._server_result.tag_configure("ok", foreground=_GREEN)
        sb.pack(side="right", fill="y")
        self._server_result.pack(fill="both", expand=True)

        # ── SSH Deploy section ──────────────────────────────────────────────
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(8, 0))

        ssh_frame = ttk.LabelFrame(parent, text="SSH Deploy", padding=8)
        ssh_frame.pack(fill="both", expand=True, pady=(6, 0))

        # Connection row
        conn_row = ttk.Frame(ssh_frame)
        conn_row.pack(fill="x", pady=(0, 6))

        ttk.Label(conn_row, text="Host:").pack(side="left")
        self._ssh_host_var = tk.StringVar(value=ssh_host)
        ttk.Entry(conn_row, textvariable=self._ssh_host_var, width=18).pack(
            side="left", padx=(4, 12)
        )
        ttk.Label(conn_row, text="User:").pack(side="left")
        self._ssh_user_var = tk.StringVar(value=ssh_user)
        ttk.Entry(conn_row, textvariable=self._ssh_user_var, width=12).pack(
            side="left", padx=(4, 12)
        )
        self._ssh_connect_btn = ttk.Button(
            conn_row, text="Connect", command=self._on_ssh_connect
        )
        self._ssh_connect_btn.pack(side="left", padx=(0, 4))
        self._ssh_disconnect_btn = ttk.Button(
            conn_row, text="Disconnect", command=self._on_ssh_disconnect
        )
        self._ssh_disconnect_btn.pack(side="left", padx=(0, 16))
        self._ssh_disconnect_btn.state(["disabled"])

        ttk.Label(conn_row, text="Status:").pack(side="left")
        self._ssh_status_var = tk.StringVar(value="Not connected")
        self._ssh_status_lbl = ttk.Label(
            conn_row, textvariable=self._ssh_status_var, foreground=_RED
        )
        self._ssh_status_lbl.pack(side="left", padx=(4, 0))

        ttk.Button(conn_row, text="Refresh", command=self._on_ssh_refresh).pack(
            side="right"
        )

        # Key file row
        key_row = ttk.Frame(ssh_frame)
        key_row.pack(fill="x", pady=(0, 6))
        ttk.Label(key_row, text="Key file:").pack(side="left")
        self._ssh_key_var = tk.StringVar(value=ssh_key)
        ttk.Entry(key_row, textvariable=self._ssh_key_var, width=45).pack(
            side="left", padx=(4, 4)
        )
        ttk.Button(key_row, text="Browse…", command=self._on_ssh_browse_key).pack(side="left")
        ttk.Label(
            key_row,
            text="(leave blank for default ~/.ssh/ keys)",
            foreground=_GRAY,
        ).pack(side="left", padx=(8, 0))

        ttk.Separator(ssh_frame, orient="horizontal").pack(fill="x", pady=(0, 6))

        # Server selector + deploy row — pack before content so it anchors to the bottom
        deploy_row = ttk.Frame(ssh_frame)
        deploy_row.pack(fill="x", side="bottom", pady=(6, 0))

        ttk.Label(deploy_row, text="Target server:").pack(side="left")
        self._ssh_server_var = tk.StringVar()
        self._ssh_server_combo = ttk.Combobox(
            deploy_row,
            textvariable=self._ssh_server_var,
            state="readonly",
            width=32,
        )
        self._ssh_server_combo.pack(side="left", padx=(6, 12))
        self._ssh_server_combo.bind("<<ComboboxSelected>>", self._on_server_selected)
        self._ssh_deploy_btn = ttk.Button(
            deploy_row, text="Deploy to Server", command=self._on_ssh_deploy
        )
        self._ssh_deploy_btn.pack(side="left")
        self._ssh_deploy_btn.state(["disabled"])

        # Two-column content area: share (left) | server management (right)
        columns = ttk.Frame(ssh_frame)
        columns.pack(fill="both", expand=True)
        columns.grid_rowconfigure(0, weight=1)
        columns.grid_columnconfigure(0, weight=1)
        columns.grid_columnconfigure(1, weight=1)

        # Left: content available on the share
        share_col = ttk.LabelFrame(columns, text="From Share", padding=4)
        share_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._ssh_content_frame = share_col
        self._ssh_placeholder = ttk.Label(
            share_col, text="Connect to browse content on the share", foreground=_GRAY
        )
        self._ssh_placeholder.pack(expand=True)

        # Right: content on the selected server
        server_col = ttk.LabelFrame(columns, text="On Server", padding=4)
        server_col.grid(row=0, column=1, sticky="nsew")
        server_col.grid_rowconfigure(2, weight=1)
        server_col.grid_rowconfigure(3, weight=1)
        server_col.grid_columnconfigure(0, weight=1)

        self._server_mgmt_placeholder = ttk.Label(
            server_col, text="Select a server to manage content.", foreground=_GRAY
        )
        self._server_mgmt_placeholder.grid(row=0, column=0, rowspan=5, pady=20)

        # Service control row (row=0, hidden until a server is selected)
        svc_row = ttk.Frame(server_col)
        ttk.Button(svc_row, text="Start", command=self._on_start_service).pack(side="left")
        ttk.Button(svc_row, text="Stop", command=self._on_stop_service).pack(
            side="left", padx=(4, 0)
        )
        ttk.Button(svc_row, text="Restart", command=self._on_restart_service).pack(
            side="left", padx=(4, 0)
        )
        ttk.Separator(svc_row, orient="vertical").pack(side="left", fill="y", padx=(10, 8))
        ttk.Label(svc_row, text="Status:").pack(side="left")
        self._svc_status_var = tk.StringVar(value="—")
        self._svc_status_label = ttk.Label(svc_row, textvariable=self._svc_status_var)
        self._svc_status_label.pack(side="left", padx=(4, 0))
        self._server_svc_row = svc_row

        # Cars management (row=1, hidden until a server is selected)
        cars_lf = ttk.LabelFrame(server_col, text="Cars", padding=4)
        cars_lf.grid_rowconfigure(0, weight=1)
        cars_lf.grid_columnconfigure(0, weight=1)
        self._server_cars_panel = _ChecklistPanel(cars_lf, "", [])
        self._server_cars_panel.grid(row=0, column=0, sticky="nsew")
        car_btns = ttk.Frame(cars_lf)
        car_btns.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(
            car_btns, text="Fix Permissions",
            command=lambda: self._on_fix_permissions("cars"),
        ).pack(side="left")
        ttk.Button(
            car_btns, text="Delete",
            command=lambda: self._on_delete_content("cars"),
        ).pack(side="left", padx=(4, 0))
        self._server_cars_lf = cars_lf

        # Tracks management (row=2, hidden until a server is selected)
        tracks_lf = ttk.LabelFrame(server_col, text="Tracks", padding=4)
        tracks_lf.grid_rowconfigure(1, weight=1)
        tracks_lf.grid_columnconfigure(0, weight=1)
        active_row = ttk.Frame(tracks_lf)
        active_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(active_row, text="Active:").pack(side="left")
        self._active_track_var = tk.StringVar(value="—")
        ttk.Label(active_row, textvariable=self._active_track_var, foreground=_GREEN).pack(
            side="left", padx=(4, 8)
        )
        ttk.Button(
            active_row, text="Change…", command=self._on_change_active_track
        ).pack(side="left")
        self._server_tracks_panel = _ChecklistPanel(tracks_lf, "", [])
        self._server_tracks_panel.grid(row=1, column=0, sticky="nsew")
        track_btns = ttk.Frame(tracks_lf)
        track_btns.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(
            track_btns, text="Fix Permissions",
            command=lambda: self._on_fix_permissions("tracks"),
        ).pack(side="left")
        ttk.Button(
            track_btns, text="Delete",
            command=lambda: self._on_delete_content("tracks"),
        ).pack(side="left", padx=(4, 0))
        self._server_tracks_lf = tracks_lf

    def _build_nextcloud_tab(self, parent: ttk.Frame) -> None:
        conn_frame = ttk.LabelFrame(parent, text="Connection", padding=10)
        conn_frame.pack(fill="x", pady=(0, 14))

        status_row = ttk.Frame(conn_frame)
        status_row.pack(fill="x")
        ttk.Label(status_row, text="Status:").pack(side="left")
        self._nc_status_var = tk.StringVar(value="Not connected")
        self._nc_status_label = ttk.Label(
            status_row, textvariable=self._nc_status_var, foreground=_RED
        )
        self._nc_status_label.pack(side="left", padx=(6, 16))
        self._nc_connect_btn = ttk.Button(
            status_row, text="Connect...", command=self._on_nc_connect
        )
        self._nc_connect_btn.pack(side="left", padx=(0, 6))
        self._nc_disconnect_btn = ttk.Button(
            status_row, text="Disconnect", command=self._on_nc_disconnect
        )
        self._nc_disconnect_btn.pack(side="left")
        self._nc_disconnect_btn.state(["disabled"])

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(0, 12))

        ttk.Label(
            parent,
            text="Create an archive from the current Content Browser selection"
            " and upload it to Nextcloud.",
            wraplength=500,
            foreground=_GRAY,
        ).pack(anchor="w", pady=(0, 8))
        self._upload_btn = ttk.Button(
            parent,
            text="Create & Upload to Nextcloud",
            command=self._on_create_upload,
        )
        self._upload_btn.pack(anchor="w")

    def _build_archive_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text="Create a .7z archive from the current Content Browser selection"
            " and save it locally.",
            wraplength=500,
            foreground=_GRAY,
        ).pack(anchor="w", pady=(0, 10))

        self._archive_btn = ttk.Button(
            parent, text="Create Archive...", command=self._on_create_archive
        )
        self._archive_btn.pack(anchor="w")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(16, 12))

        last_row = ttk.Frame(parent)
        last_row.pack(fill="x")
        ttk.Label(last_row, text="Last archive:", font=("", 9, "bold")).pack(side="left")
        self._last_archive_var = tk.StringVar(value="—")
        ttk.Label(last_row, textvariable=self._last_archive_var, foreground=_GRAY).pack(
            side="left", padx=(6, 0)
        )

    # ------------------------------------------------------------------
    # Layout — footer (shared status bar)
    # ------------------------------------------------------------------

    def _build_footer(self) -> None:
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(4, 0))
        footer = ttk.Frame(self, padding=(10, 5))
        footer.pack(fill="x", side="bottom")

        self._status_var = tk.StringVar()
        self._status_label = ttk.Label(
            footer, textvariable=self._status_var, foreground=_GRAY
        )
        self._status_label.pack(side="left")

        self._progress = ttk.Progressbar(footer, mode="indeterminate", length=160)

    # ------------------------------------------------------------------
    # Status / progress helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str, color: str = _GRAY) -> None:
        self._status_var.set(text)
        self._status_label.configure(foreground=color)

    def _start_progress(self, message: str) -> None:
        """Indeterminate spinner — use for operations with unknown duration."""
        self._progress.configure(mode="indeterminate")
        self._set_status(message, _ORANGE)
        self._progress.pack(side="left", padx=(10, 0))
        self._progress.start(12)

    def _start_progress_determinate(self, message: str, total: int) -> None:
        """Determinate bar — use when total steps are known (archive creation)."""
        self._progress.stop()
        self._progress.configure(mode="determinate", maximum=total, value=0)
        self._set_status(message, _ORANGE)
        self._progress.pack(side="left", padx=(10, 0))

    def _update_progress(self, done: int, total: int, message: str) -> None:
        self._progress.configure(value=done)
        self._set_status(message, _ORANGE)

    def _stop_progress(self) -> None:
        self._progress.stop()
        self._progress.pack_forget()
        self._progress.configure(mode="indeterminate", value=0)

    def _disable_buttons(self) -> None:
        for btn in (self._archive_btn, self._upload_btn, self._server_btn):
            btn.state(["disabled"])
        self._nc_connect_btn.state(["disabled"])
        self._nc_disconnect_btn.state(["disabled"])

    def _enable_buttons(self) -> None:
        for btn in (self._archive_btn, self._upload_btn, self._server_btn):
            btn.state(["!disabled"])
        self._update_nc_status()

    # ------------------------------------------------------------------
    # Nextcloud connection state
    # ------------------------------------------------------------------

    def _update_nc_status(self) -> None:
        if self._nc_client is not None:
            self._nc_status_var.set(f"Connected as  {self._nc_client.username}")
            self._nc_status_label.configure(foreground=_GREEN)
            self._nc_connect_btn.state(["disabled"])
            self._nc_disconnect_btn.state(["!disabled"])
        else:
            self._nc_status_var.set("Not connected")
            self._nc_status_label.configure(foreground=_RED)
            self._nc_connect_btn.state(["!disabled"])
            self._nc_disconnect_btn.state(["disabled"])

    def _on_nc_connect(self) -> None:
        log.info("User opened Nextcloud connection dialog")
        client = open_connect_dialog(self)
        if client is not None:
            self._nc_client = client
            log.info("Nextcloud connected as '%s'", client.username)
        self._update_nc_status()

    def _on_nc_disconnect(self) -> None:
        if self._nc_client is not None:
            log.info("User disconnected from Nextcloud (was '%s')", self._nc_client.username)
        self._nc_client = None
        self._update_nc_status()

    # ------------------------------------------------------------------
    # Server results log helpers
    # ------------------------------------------------------------------

    def _append_server_result(self, text: str, tag: str = "") -> None:
        self._server_result.configure(state="normal")
        self._server_result.insert("end", text + "\n", tag if tag else ())
        self._server_result.see("end")
        self._server_result.configure(state="disabled")

    def _clear_server_results(self) -> None:
        self._server_result.configure(state="normal")
        self._server_result.delete("1.0", "end")
        self._server_result.configure(state="disabled")

    # ------------------------------------------------------------------
    # Actions — header
    # ------------------------------------------------------------------

    def _on_tab_changed(self, event: object = None) -> None:
        self._refresh_selection_display()

    def _refresh_selection_display(self) -> None:
        lines: list[str] = []
        for category, panel in self._panels.items():
            selected = panel.get_selected()
            if selected:
                lines.append(f"{category.title()} ({len(selected)}): {', '.join(selected)}")
            else:
                lines.append(f"{category.title()} (0): none selected")
        text = "\n".join(lines) if lines else "No content loaded."
        self._selection_text.configure(state="normal")
        self._selection_text.delete("1.0", "end")
        self._selection_text.insert("end", text)
        self._selection_text.configure(state="disabled")

    def _on_change_dir(self) -> None:
        chosen = filedialog.askdirectory(
            title="Select Assetto Corsa install folder", mustexist=True
        )
        if not chosen:
            return
        new_dir = Path(chosen)
        log.info("User changed AC install dir: %s  →  %s", self._install_dir, new_dir)
        self._install_dir = new_dir
        save_install_dir(new_dir)
        self._install_path_label.configure(text=str(new_dir))
        for panel in self._panels.values():
            panel.destroy()
        self._panels.clear()
        self._build_panels(scan_content(new_dir))
        self._refresh_selection_display()
        self._set_status(f"Loaded content from {new_dir}", _GREEN)

    def _on_change_share(self) -> None:
        new = simpledialog.askstring(
            "Network Share",
            "Enter the network share path:",
            initialvalue=str(self._share_path),
            parent=self,
        )
        if not new or not new.strip():
            return
        old = self._share_path
        self._share_path = Path(new.strip())
        self._share_path_label.configure(text=str(self._share_path))
        save_share_path(self._share_path)
        log.info("User changed share path: %s  →  %s", old, self._share_path)
        self._set_status(f"Share path updated → {self._share_path}", _GREEN)

    # ------------------------------------------------------------------
    # Actions — Content Browser tab
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        selection = {cat: panel.get_selected() for cat, panel in self._panels.items()}
        total = sum(len(v) for v in selection.values())
        log.info("Saving selection: %d items", total)
        try:
            save_selection(_SELECTION_FILE, selection)
            self._set_status(f"Saved {total} items → {_SELECTION_FILE}", _GREEN)
        except OSError as exc:
            log.error("Failed to save selection: %s", exc)
            messagebox.showerror("Save failed", str(exc))

    def _get_selection(self) -> dict[str, list[str]] | None:
        selection = {cat: panel.get_selected() for cat, panel in self._panels.items()}
        if not any(selection.values()):
            messagebox.showwarning(
                "Nothing selected",
                "Tick at least one item on the Content Browser tab before proceeding.",
            )
            return None
        return selection

    # ------------------------------------------------------------------
    # Actions — Archive tab
    # ------------------------------------------------------------------

    def _on_create_archive(self) -> None:
        selection = self._get_selection()
        if selection is None:
            return
        output_str = filedialog.asksaveasfilename(
            title="Save archive as",
            defaultextension=".7z",
            filetypes=[("7-Zip archive", "*.7z"), ("All files", "*.*")],
        )
        if not output_str:
            return

        output_path = Path(output_str)
        install_dir = self._install_dir
        total_items = sum(len(v) for v in selection.values())
        log.info("Create Archive initiated: output=%s  items=%d", output_path, total_items)
        self._start_progress_determinate(
            f"Creating archive… 0 / {total_items} items", total_items
        )
        self._disable_buttons()

        def on_progress(done: int, total: int) -> None:
            msg = f"Creating archive… {done} / {total} items"
            self.after(0, lambda: self._update_progress(done, total, msg))

        def _worker() -> None:
            try:
                create_archive(install_dir, selection, output_path, on_progress=on_progress)
                self.after(0, self._stop_progress)
                self.after(0, lambda: self._last_archive_var.set(str(output_path)))
                self.after(
                    0, lambda: self._set_status(f"Archive saved → {output_path}", _GREEN)
                )
            except FileNotFoundError as exc:
                err = str(exc)
                log.error("Create Archive failed — 7-Zip not found: %s", exc)
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("7-Zip not found", err))
                self.after(
                    0, lambda: self._set_status("Archive failed — 7-Zip not found", _RED)
                )
            except subprocess.CalledProcessError as exc:
                msg = f"7-Zip exited with code {exc.returncode}"
                log.error("Create Archive failed: %s", msg)
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("Archive failed", msg))
                self.after(0, lambda: self._set_status("Archive failed", _RED))
            finally:
                self.after(0, self._enable_buttons)

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Actions — Nextcloud tab
    # ------------------------------------------------------------------

    def _on_create_upload(self) -> None:
        selection = self._get_selection()
        if selection is None:
            return

        if self._nc_client is None:
            log.info("No Nextcloud client — opening connection dialog from upload flow")
            self._nc_client = open_connect_dialog(self)
            self._update_nc_status()
        if self._nc_client is None:
            log.info("Nextcloud connect dialog cancelled")
            return

        install_dir = self._install_dir
        nc_client = self._nc_client
        default_name = _default_archive_name(selection)
        total_items = sum(len(v) for v in selection.values())

        # mkstemp atomically reserves a unique path; unlink so 7-zip creates fresh
        _fd, _tmp = tempfile.mkstemp(suffix=".7z")
        os.close(_fd)
        os.unlink(_tmp)
        tmp_path = Path(_tmp)

        log.info(
            "Create & Upload initiated: tmp=%s  items=%d  default_name=%s",
            tmp_path, total_items, default_name,
        )
        self._start_progress_determinate(
            f"Creating archive… 0 / {total_items} items", total_items
        )
        self._disable_buttons()

        def on_progress(done: int, total: int) -> None:
            msg = f"Creating archive… {done} / {total} items"
            self.after(0, lambda: self._update_progress(done, total, msg))

        def _worker() -> None:
            try:
                create_archive(
                    install_dir, selection, tmp_path, on_progress=on_progress
                )
                self.after(0, lambda: self._on_archive_ready(nc_client, tmp_path, default_name))
            except FileNotFoundError as exc:
                err = str(exc)
                log.error("Create & Upload — archive failed (7-Zip not found): %s", exc)
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("7-Zip not found", err))
                self.after(
                    0, lambda: self._set_status("Archive failed — 7-Zip not found", _RED)
                )
                self.after(0, self._enable_buttons)
            except subprocess.CalledProcessError as exc:
                msg = f"7-Zip exited with code {exc.returncode}"
                log.error("Create & Upload — archive failed: %s", msg)
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("Archive failed", msg))
                self.after(0, lambda: self._set_status("Archive failed", _RED))
                self.after(0, self._enable_buttons)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_archive_ready(
        self, nc_client: NextcloudClient, tmp_path: Path, archive_name: str
    ) -> None:
        self._stop_progress()
        log.info("Archive ready for upload: %s  (as '%s')", tmp_path, archive_name)
        self._set_status("Archive ready — select upload destination…", _ORANGE)
        uploaded = open_file_browser(
            self, nc_client, archive_path=tmp_path, archive_name=archive_name
        )
        if uploaded:
            log.info("Upload completed successfully")
            self._set_status("Upload complete", _GREEN)
        else:
            log.info("Upload cancelled by user")
            self._set_status("Upload cancelled", _GRAY)
        try:
            tmp_path.unlink(missing_ok=True)
            log.debug("Temp archive cleaned up: %s", tmp_path)
        except OSError as exc:
            log.warning("Could not clean up temp archive %s: %s", tmp_path, exc)
        self._enable_buttons()

    # ------------------------------------------------------------------
    # Actions — Server Update tab
    # ------------------------------------------------------------------

    def _on_server_update(self) -> None:
        selection = self._get_selection()
        if selection is None:
            return

        install_dir = self._install_dir
        share_path = self._share_path
        log.info("Server Content Update initiated: share=%s", share_path)
        self._start_progress(f"Copying to {share_path}…")
        self._disable_buttons()

        def _worker() -> None:
            result = copy_to_share(install_dir, selection, share_path)
            self.after(0, self._stop_progress)
            self.after(0, lambda: self._on_copy_done(result, share_path))
            self.after(0, self._enable_buttons)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_copy_done(self, result: CopyResult, share_path: Path) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        summary = f"[{ts}]  Copied {result.copied} file(s) to {share_path}"

        if result.errors:
            self._append_server_result(
                f"{summary}  —  {len(result.errors)} error(s)", "error"
            )
            for err in result.errors:
                self._append_server_result(f"    {err}", "error")
            self._set_status(
                f"Copied {result.copied} file(s), {len(result.errors)} error(s)", _RED
            )
        elif result.skipped:
            self._append_server_result(
                f"{summary}  —  {result.skipped} not found", "warn"
            )
            self._set_status(
                f"Copied {result.copied} file(s) ({result.skipped} not found)", _ORANGE
            )
        else:
            self._append_server_result(summary, "ok")
            self._set_status(f"Copied {result.copied} file(s) to {share_path}", _GREEN)

    # ------------------------------------------------------------------
    # Actions — SSH Deploy section
    # ------------------------------------------------------------------

    def _update_ssh_status(self, text: str, color: str = _GRAY) -> None:
        self._ssh_status_var.set(text)
        self._ssh_status_lbl.configure(foreground=color)

    def _on_ssh_connect(self) -> None:
        host = self._ssh_host_var.get().strip()
        user = self._ssh_user_var.get().strip()
        if not host or not user:
            messagebox.showwarning("Missing fields", "Enter host and username first.", parent=self)
            return
        key_path = self._ssh_key_var.get().strip() or None
        save_ssh_config(host, user, key_path or "")
        self._ssh_connect_btn.state(["disabled"])
        self._update_ssh_status("Connecting…", _ORANGE)
        self._set_status(f"Connecting to {user}@{host}…", _ORANGE)
        log.info(
            "SSH connect initiated: user=%s  host=%s  key=%s", user, host, key_path or "(default)"
        )

        def _try_key() -> None:
            try:
                client = SshClient(host, user)
                client.connect(key_path=key_path)
                self._ssh_client = client
                content = client.list_share_content()
                servers = client.list_ac_servers()
                self.after(0, lambda: self._on_ssh_connected(content, servers))
            except paramiko.PasswordRequiredException:
                if key_path:
                    self.after(0, lambda: self._on_ssh_need_passphrase(host, user, key_path))
                else:
                    err = (
                        "A key in ~/.ssh/ is passphrase-protected. "
                        "Specify the key file above or unlock it with ssh-agent."
                    )
                    self.after(0, lambda: self._on_ssh_connect_failed(err))
            except paramiko.AuthenticationException:
                if key_path:
                    err = (
                        f"Key file was rejected by {host}. "
                        "Check that the public key is in authorized_keys."
                    )
                    self.after(0, lambda: self._on_ssh_connect_failed(err))
                else:
                    self.after(0, self._on_ssh_need_password)
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda: self._on_ssh_connect_failed(err))

        threading.Thread(target=_try_key, daemon=True).start()

    def _on_ssh_browse_key(self) -> None:
        initial = str(Path.home() / ".ssh")
        path = filedialog.askopenfilename(
            title="Select SSH private key file",
            initialdir=initial if Path(initial).exists() else str(Path.home()),
            filetypes=[("All files", "*.*")],
            parent=self,
        )
        if path:
            self._ssh_key_var.set(path)

    def _on_ssh_need_passphrase(self, host: str, user: str, key_path: str) -> None:
        log.info("Key file is passphrase-protected, prompting: %s", key_path)
        passphrase = simpledialog.askstring(
            "Key Passphrase",
            f"Passphrase for {Path(key_path).name}:",
            show="●",
            parent=self,
        )
        if passphrase is None:
            self._ssh_connect_btn.state(["!disabled"])
            self._update_ssh_status("Not connected", _RED)
            self._set_status("SSH connection cancelled", _GRAY)
            return

        def _try_passphrase() -> None:
            try:
                client = SshClient(host, user)
                client.connect(key_path=key_path, passphrase=passphrase)
                self._ssh_client = client
                content = client.list_share_content()
                servers = client.list_ac_servers()
                self.after(0, lambda: self._on_ssh_connected(content, servers))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda: self._on_ssh_connect_failed(err))

        threading.Thread(target=_try_passphrase, daemon=True).start()

    def _on_ssh_need_password(self) -> None:
        host = self._ssh_host_var.get()
        user = self._ssh_user_var.get()
        log.info("Key auth failed for %s@%s — prompting for password", user, host)
        pwd = simpledialog.askstring(
            "SSH Password",
            f"Key authentication failed.\nPassword for {user}@{host}:",
            show="●",
            parent=self,
        )
        if pwd is None:
            self._ssh_connect_btn.state(["!disabled"])
            self._update_ssh_status("Not connected", _RED)
            self._set_status("SSH connection cancelled", _GRAY)
            return

        def _try_password() -> None:
            try:
                client = SshClient(host, user)
                client.connect(password=pwd)
                self._ssh_client = client
                content = client.list_share_content()
                servers = client.list_ac_servers()
                self.after(0, lambda: self._on_ssh_connected(content, servers))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda: self._on_ssh_connect_failed(err))

        threading.Thread(target=_try_password, daemon=True).start()

    def _on_ssh_connected(
        self, content: dict[str, list[str]], servers: list[str]
    ) -> None:
        host = self._ssh_host_var.get()
        log.info("SSH connected: host=%s  servers=%s", host, servers)
        self._update_ssh_status(f"Connected to {host}", _GREEN)
        self._ssh_connect_btn.state(["disabled"])
        self._ssh_disconnect_btn.state(["!disabled"])

        # Rebuild share content panels
        self._ssh_placeholder.pack_forget()
        for panel in self._ssh_panels.values():
            panel.destroy()
        self._ssh_panels.clear()

        has_content = any(content.values())
        if has_content:
            for category, items in content.items():
                if items:
                    panel = _ChecklistPanel(
                        self._ssh_content_frame, title=category.title(), items=items
                    )
                    panel.pack(side="left", fill="both", expand=True, padx=(0, 4))
                    self._ssh_panels[category] = panel
        else:
            self._ssh_placeholder.configure(text="No content found on the share")
            self._ssh_placeholder.pack(expand=True)

        # Populate server dropdown
        self._ssh_server_map.clear()
        display_list: list[str] = []
        for srv in servers:
            label = f"{get_display_name(srv)}  [{srv}]"
            self._ssh_server_map[label] = srv
            display_list.append(label)
        self._ssh_server_combo["values"] = display_list
        if display_list:
            self._ssh_server_combo.set(display_list[0])
            self._ssh_deploy_btn.state(["!disabled"])
            self._on_server_selected()
        else:
            self._ssh_server_combo.set("")
            self._ssh_deploy_btn.state(["disabled"])

        self._set_status(f"SSH connected to {host}", _GREEN)

    def _on_ssh_connect_failed(self, err: str) -> None:
        log.error("SSH connection failed: %s", err)
        self._ssh_connect_btn.state(["!disabled"])
        self._update_ssh_status("Connection failed", _RED)
        messagebox.showerror("SSH Connection Failed", err, parent=self)
        self._set_status("SSH connection failed", _RED)

    def _on_ssh_disconnect(self) -> None:
        if self._ssh_client is not None:
            host = self._ssh_host_var.get()
            log.info("User disconnecting SSH from %s", host)
            self._ssh_client.disconnect()
            self._ssh_client = None

        self._update_ssh_status("Not connected", _RED)
        self._ssh_connect_btn.state(["!disabled"])
        self._ssh_disconnect_btn.state(["disabled"])
        self._ssh_deploy_btn.state(["disabled"])

        for panel in self._ssh_panels.values():
            panel.destroy()
        self._ssh_panels.clear()
        self._ssh_server_map.clear()
        self._current_server_name = ""
        self._ssh_server_combo["values"] = []
        self._ssh_server_combo.set("")
        self._ssh_placeholder.configure(text="Connect to browse content on the share")
        self._ssh_placeholder.pack(expand=True)
        self._clear_server_mgmt_panel()
        self._set_status("SSH disconnected", _GRAY)

    def _on_ssh_refresh(self) -> None:
        if self._ssh_client is None or not self._ssh_client.is_connected:
            messagebox.showinfo("Not connected", "Connect to the server first.", parent=self)
            return
        self._update_ssh_status("Refreshing…", _ORANGE)
        client = self._ssh_client

        def _worker() -> None:
            try:
                content = client.list_share_content()
                servers = client.list_ac_servers()
                self.after(0, lambda: self._on_ssh_connected(content, servers))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda: self._on_ssh_connect_failed(err))

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Server content management
    # ------------------------------------------------------------------

    def _clear_server_mgmt_panel(self) -> None:
        self._server_svc_row.grid_remove()
        self._server_cars_lf.grid_remove()
        self._server_tracks_lf.grid_remove()
        self._server_mgmt_placeholder.grid(row=0, column=0, rowspan=5, pady=20)
        self._active_track_var.set("—")
        self._svc_status_var.set("—")
        self._svc_status_label.configure(foreground=_GRAY)

    def _on_server_selected(self, event: object = None) -> None:
        display = self._ssh_server_var.get()
        server_name = self._ssh_server_map.get(display, "")
        if not server_name or self._ssh_client is None:
            return
        self._current_server_name = server_name
        client = self._ssh_client
        server_dir = f"{_AC_HOME}/{server_name}"

        def _worker() -> None:
            try:
                cars = client.list_server_cars(server_dir)
                tracks = client.list_server_tracks(server_dir)
                active = client.read_active_track(server_dir)
                status = client.get_service_status(f"{server_name}.service")
                self.after(
                    0,
                    lambda: self._on_server_mgmt_loaded(
                        server_name, cars, tracks, active, status
                    ),
                )
            except Exception as exc:
                log.error("Failed to load server content for %s: %s", server_name, exc)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_server_mgmt_loaded(
        self,
        server_name: str,
        cars: list[str],
        tracks: list[str],
        active_track: str,
        service_status: str = "unknown",
    ) -> None:
        if server_name != self._current_server_name:
            return
        self._server_mgmt_placeholder.grid_remove()

        self._server_svc_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._update_svc_status(service_status)
        self._server_cars_panel.set_items(cars)
        self._server_cars_lf.grid(row=1, column=0, sticky="nsew", pady=(0, 4))

        self._active_track_var.set(active_track or "—")
        self._server_tracks_panel.set_items(tracks)
        self._server_tracks_lf.grid(row=2, column=0, sticky="nsew")

        log.info(
            "Server management panel loaded: %s — %d cars, %d tracks, status=%s",
            server_name, len(cars), len(tracks), service_status,
        )

    def _update_svc_status(self, status: str) -> None:
        self._svc_status_var.set(status)
        color = {
            "active": _GREEN,
            "activating": _ORANGE,
            "deactivating": _ORANGE,
            "failed": _RED,
        }.get(status, _GRAY)
        self._svc_status_label.configure(foreground=color)

    def _on_start_service(self) -> None:
        self._run_service_command("start")

    def _on_stop_service(self) -> None:
        self._run_service_command("stop")

    def _on_restart_service(self) -> None:
        self._run_service_command("restart")

    def _run_service_command(self, action: str) -> None:
        if self._ssh_client is None or not self._current_server_name:
            return
        service = f"{self._current_server_name}.service"
        client = self._ssh_client
        self._start_progress(f"{action.capitalize()}ing {service}…")

        def _worker() -> None:
            error: str | None = None
            try:
                if action == "start":
                    client.start_service(service)
                elif action == "stop":
                    client.stop_service(service)
                else:
                    client.restart_service(service)
            except RuntimeError as exc:
                error = str(exc)
            new_status = client.get_service_status(service)
            self.after(0, self._stop_progress)
            self.after(0, lambda: self._update_svc_status(new_status))
            ts = datetime.now().strftime("%H:%M:%S")
            if error:
                self.after(0, lambda: self._append_server_result(f"[{ts}]  {error}", "error"))
                self.after(0, lambda: self._set_status(error, _RED))
            else:
                msg = f"{action.capitalize()}ed {service}"
                self.after(0, lambda: self._append_server_result(f"[{ts}]  {msg}", "ok"))
                self.after(0, lambda: self._set_status(msg, _GREEN))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_fix_permissions(self, category: str) -> None:
        if self._ssh_client is None or not self._current_server_name:
            return
        panel = self._server_cars_panel if category == "cars" else self._server_tracks_panel
        selected = panel.get_selected()
        if not selected:
            messagebox.showwarning("Nothing selected", f"Select {category} to fix.", parent=self)
            return
        client = self._ssh_client
        server_dir = f"{_AC_HOME}/{self._current_server_name}"
        self._start_progress(f"Fixing permissions on {len(selected)} {category}…")

        def _worker() -> None:
            errors: list[str] = []
            for name in selected:
                try:
                    client.fix_permissions(server_dir, category, [name])
                except RuntimeError as exc:
                    errors.append(f"{name}: {exc}")
            self.after(0, self._stop_progress)
            ts = datetime.now().strftime("%H:%M:%S")
            if errors:
                for e in errors:
                    self.after(
                        0,
                        functools.partial(self._append_server_result, f"[{ts}]  {e}", "error"),
                    )
                self.after(0, lambda: self._set_status("Permission fix failed (see results)", _RED))
            else:
                n = len(selected)
                self.after(0, lambda: self._append_server_result(
                    f"[{ts}]  Fixed permissions on {n} {category}", "ok"
                ))
                self.after(0, lambda: self._set_status(
                    f"Permissions fixed on {n} {category}", _GREEN
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_delete_content(self, category: str) -> None:
        if self._ssh_client is None or not self._current_server_name:
            return
        panel = self._server_cars_panel if category == "cars" else self._server_tracks_panel
        selected = panel.get_selected()
        if not selected:
            messagebox.showwarning("Nothing selected", f"Select {category} to delete.", parent=self)
            return
        server_name = self._current_server_name
        server_label = get_display_name(server_name)
        service = f"{server_name}.service"
        active_track = self._active_track_var.get()
        active_deleted = category == "tracks" and active_track in selected and active_track != "—"

        # Only cars and active-track deletion need a service stop/start cycle
        needs_service_cycle = category == "cars" or active_deleted
        if needs_service_cycle:
            detail = (
                "\n\nentry_list.ini will be rebuilt and the service restarted."
                if category == "cars"
                else (
                    f"\n\nActive track '{active_track}' will be deleted — "
                    "the next available track will be set and the service restarted."
                )
            )
            confirm_msg = (
                f"Delete {len(selected)} {category} from {server_label}?\n"
                f"This will stop {service}.{detail}"
            )
        else:
            confirm_msg = f"Delete {len(selected)} {category} from {server_label}?"

        if not messagebox.askyesno("Confirm Delete", confirm_msg, parent=self):
            return

        client = self._ssh_client
        server_dir = f"{_AC_HOME}/{server_name}"
        self._start_progress(
            f"Stopping {service}…" if needs_service_cycle else f"Deleting {category}…"
        )

        def _worker() -> None:
            error: str | None = None

            if needs_service_cycle:
                try:
                    client.stop_service(service)
                    ts = datetime.now().strftime("%H:%M:%S")
                    self.after(0, lambda: self._append_server_result(
                        f"[{ts}]  Stopped {service}", "ok"
                    ))
                except RuntimeError as exc:
                    error = f"Failed to stop {service}: {exc}"

            if error is None:
                try:
                    client.delete_content(server_dir, category, selected)
                    ts = datetime.now().strftime("%H:%M:%S")
                    n = len(selected)
                    self.after(0, lambda: self._append_server_result(
                        f"[{ts}]  Deleted {n} {category}", "ok"
                    ))
                except RuntimeError as exc:
                    error = f"Delete failed: {exc}"

            if error is None and category == "cars":
                try:
                    remaining = client.list_server_cars(server_dir)
                    cars_with_skins = [
                        (car, _get_skin_for_car(self._install_dir, car))
                        for car in remaining
                    ]
                    client.write_entry_list(server_dir, cars_with_skins)
                    ts = datetime.now().strftime("%H:%M:%S")
                    n = len(remaining)
                    self.after(0, lambda: self._append_server_result(
                        f"[{ts}]  entry_list.ini rebuilt ({n} car(s))", "ok"
                    ))
                except Exception as exc:
                    error = f"Failed to rebuild entry_list.ini: {exc}"

            if error is None and active_deleted:
                remaining_tracks = client.list_server_tracks(server_dir)
                if remaining_tracks:
                    next_track = remaining_tracks[0]
                    try:
                        client.write_active_track(server_dir, next_track)
                        self.after(0, lambda: self._active_track_var.set(next_track))
                        ts = datetime.now().strftime("%H:%M:%S")
                        self.after(0, lambda: self._append_server_result(
                            f"[{ts}]  Active track updated to {next_track}", "ok"
                        ))
                    except Exception as exc:
                        error = f"Failed to update active track: {exc}"

            if error is None and needs_service_cycle:
                action = "restart" if active_deleted else "start"
                try:
                    if action == "restart":
                        client.restart_service(service)
                    else:
                        client.start_service(service)
                    ts = datetime.now().strftime("%H:%M:%S")
                    verb = "Restarted" if action == "restart" else "Started"
                    self.after(0, lambda: self._append_server_result(
                        f"[{ts}]  {verb} {service}", "ok"
                    ))
                except RuntimeError as exc:
                    error = f"Failed to {action} {service}: {exc}"

            self.after(0, self._stop_progress)
            if error:
                self.after(0, lambda: self._append_server_result(f"    {error}", "error"))
                self.after(0, lambda: self._set_status(error, _RED))
            else:
                self.after(0, lambda: self._set_status(
                    f"Deleted {len(selected)} {category} from {server_label}", _GREEN
                ))
            self.after(0, lambda: self._on_server_selected())

        threading.Thread(target=_worker, daemon=True).start()

    def _on_change_active_track(self) -> None:
        if self._ssh_client is None or not self._current_server_name:
            return
        client = self._ssh_client
        server_dir = f"{_AC_HOME}/{self._current_server_name}"
        available = list(self._server_tracks_panel._vars.keys())
        if not available:
            messagebox.showinfo("No tracks", "No tracks found on the server.", parent=self)
            return
        track = simpledialog.askstring(
            "Set Active Track",
            "Available tracks:\n  " + "\n  ".join(available) + "\n\nEnter track name:",
            initialvalue=self._active_track_var.get()
            if self._active_track_var.get() != "—"
            else "",
            parent=self,
        )
        if not track or track.strip() not in available:
            if track is not None:
                messagebox.showwarning(
                    "Invalid track",
                    f"'{track}' is not in the server's tracks list.",
                    parent=self,
                )
            return
        track = track.strip()

        service = f"{self._current_server_name}.service"

        def _worker() -> None:
            error: str | None = None
            try:
                client.write_active_track(server_dir, track)
                self.after(0, lambda: self._active_track_var.set(track))
                ts = datetime.now().strftime("%H:%M:%S")
                self.after(0, lambda: self._append_server_result(
                    f"[{ts}]  Active track set to {track}", "ok"
                ))
            except Exception as exc:
                error = str(exc)

            if error is None:
                try:
                    client.restart_service(service)
                    ts = datetime.now().strftime("%H:%M:%S")
                    self.after(0, lambda: self._append_server_result(
                        f"[{ts}]  Restarted {service}", "ok"
                    ))
                    self.after(0, lambda: self._set_status(
                        f"Active track: {track} — {service} restarted", _GREEN
                    ))
                except RuntimeError as exc:
                    error = str(exc)

            if error:
                self.after(0, lambda: self._set_status(error, _RED))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_ssh_deploy(self) -> None:
        if self._ssh_client is None:
            return
        selection = {cat: panel.get_selected() for cat, panel in self._ssh_panels.items()}
        if not any(selection.values()):
            messagebox.showwarning(
                "Nothing selected", "Select at least one item to deploy.", parent=self
            )
            return
        label = self._ssh_server_var.get()
        server_name = self._ssh_server_map.get(label, "")
        if not server_name:
            messagebox.showwarning("No server", "Select a target server.", parent=self)
            return

        total = sum(len(v) for v in selection.values())
        if not messagebox.askyesno(
            "Confirm Deploy",
            f"Deploy {total} item(s) to {label}?\n\nExisting files will be overwritten.",
            parent=self,
        ):
            return

        client = self._ssh_client
        self._ssh_deploy_btn.state(["disabled"])
        self._start_progress_determinate(f"Deploying to {server_name}…", total)
        log.info("Deploy initiated: server=%s  items=%d", server_name, total)

        def on_progress(done: int, t: int) -> None:
            msg = f"Deploying… {done} / {t} items"
            self.after(0, lambda: self._update_progress(done, t, msg))

        def _worker() -> None:
            result = client.deploy(server_name, selection, on_progress=on_progress)
            self.after(0, self._stop_progress)
            self.after(0, lambda: self._on_deploy_done(result, label, server_name))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_deploy_done(
        self, result: DeployResult, server_label: str, server_name: str
    ) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        summary = f"[{ts}]  Deployed {result.deployed} item(s) to {server_label}"

        if result.errors:
            self._append_server_result(
                f"{summary}  —  {len(result.errors)} error(s)", "error"
            )
            for err in result.errors:
                self._append_server_result(f"    {err}", "error")
            self._set_status(
                f"Deployed {result.deployed}, {len(result.errors)} error(s)", _RED
            )
        elif result.skipped:
            self._append_server_result(
                f"{summary}  —  {result.skipped} not found on share", "warn"
            )
            self._set_status(
                f"Deployed {result.deployed} ({result.skipped} not found)", _ORANGE
            )
        else:
            self._append_server_result(summary, "ok")
            self._set_status(f"Deployed {result.deployed} item(s) to {server_label}", _GREEN)

        deployed_cars = [name for cat, name in result.deployed_items if cat == "cars"]
        if not deployed_cars:
            self._ssh_deploy_btn.state(["!disabled"])
            return

        service = f"{server_name}.service"
        if messagebox.askyesno(
            "Update Server Config",
            f"{len(deployed_cars)} car(s) were deployed to {server_label}.\n\n"
            f"Stop {service} and rebuild entry_list.ini from all cars currently on the server?",
            parent=self,
        ):
            self._on_stop_and_update(server_name, server_label, service)
        else:
            self._ssh_deploy_btn.state(["!disabled"])

    def _on_stop_and_update(
        self,
        server_name: str,
        server_label: str,
        service: str,
    ) -> None:
        client = self._ssh_client
        if client is None:
            self._ssh_deploy_btn.state(["!disabled"])
            return
        server_dir = f"{_AC_HOME}/{server_name}"
        self._start_progress(f"Stopping {service}…")
        log.info("Stopping %s and rebuilding entry_list.ini", service)

        def _worker() -> None:
            stopped = False
            updated = False
            error: str | None = None

            try:
                client.stop_service(service)
                stopped = True
                ts = datetime.now().strftime("%H:%M:%S")
                self.after(0, lambda: self._append_server_result(
                    f"[{ts}]  Stopped {service}", "ok"
                ))
            except RuntimeError as exc:
                error = f"Failed to stop {service}: {exc}"
                log.error("Stop service failed: %s", exc)

            if stopped:
                try:
                    all_cars = client.list_server_cars(server_dir)
                    cars_with_skins = [
                        (car, _get_skin_for_car(self._install_dir, car))
                        for car in all_cars
                    ]
                    client.write_entry_list(server_dir, cars_with_skins)
                    updated = True
                    ts2 = datetime.now().strftime("%H:%M:%S")
                    n = len(cars_with_skins)
                    self.after(0, lambda: self._append_server_result(
                        f"[{ts2}]  entry_list.ini rebuilt ({n} car(s))", "ok"
                    ))
                except Exception as exc:
                    error = f"Failed to rebuild entry_list.ini: {exc}"
                    log.error("entry_list rebuild failed: %s", exc)

            started = False
            if updated:
                try:
                    client.start_service(service)
                    started = True
                    ts3 = datetime.now().strftime("%H:%M:%S")
                    self.after(0, lambda: self._append_server_result(
                        f"[{ts3}]  Started {service}", "ok"
                    ))
                except RuntimeError as exc:
                    error = f"Failed to start {service}: {exc}"
                    log.error("Start service failed: %s", exc)

            self.after(0, self._stop_progress)
            self.after(
                0, lambda: self._on_post_deploy_done(service, stopped, updated, started, error)
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _on_post_deploy_done(
        self,
        service: str,
        stopped: bool,
        updated: bool,
        started: bool,
        error: str | None,
    ) -> None:
        self._ssh_deploy_btn.state(["!disabled"])
        if error:
            self._append_server_result(f"    {error}", "error")
            self._set_status(error, _RED)
        elif started:
            self._set_status(
                f"Done — entry_list.ini rebuilt and {service} started", _GREEN
            )
        elif stopped and updated:
            self._set_status(
                f"Done — {service} stopped and entry_list.ini rebuilt", _ORANGE
            )
        elif stopped:
            self._set_status(f"{service} stopped (entry_list.ini not updated)", _ORANGE)
        self._on_server_selected()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _get_skin_for_car(install_dir: Path, car_name: str) -> str:
    """Return the first available skin name for a car, or empty string if none found."""
    skins_dir = install_dir / "content" / "cars" / car_name / "skins"
    try:
        skins = sorted(p.name for p in skins_dir.iterdir() if p.is_dir())
        return skins[0] if skins else ""
    except OSError:
        return ""


def _default_archive_name(selection: dict[str, list[str]]) -> str:
    non_empty = sorted(cat for cat, items in selection.items() if items)
    if len(non_empty) == 1:
        return f"{non_empty[0]}.7z"
    return "content.7z"


def run() -> None:
    setup_logging()
    log.info("run() called")

    install_dir = load_install_dir() or find_ac_install()
    if install_dir is None:
        log.info("AC install not auto-detected — prompting user")
        root = tk.Tk()
        root.withdraw()
        chosen = filedialog.askdirectory(
            title="Locate Assetto Corsa install folder", mustexist=True
        )
        root.destroy()
        if not chosen:
            log.info("User cancelled install dir selection — exiting")
            return
        install_dir = Path(chosen)
        save_install_dir(install_dir)

    log.info("AC install dir: %s", install_dir)
    content = scan_content(install_dir)
    log.info(
        "Content scan: %s",
        "  ".join(f"{cat}={len(items)}" for cat, items in content.items()),
    )
    app = _App(install_dir, content)
    app.mainloop()
    log.info("App exited")
