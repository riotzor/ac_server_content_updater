from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ac_updater._logging import setup_logging
from ac_updater.ac_finder import find_ac_install
from ac_updater.archiver import create_archive
from ac_updater.content_copier import CopyResult, copy_to_share
from ac_updater.content_scanner import scan_content
from ac_updater.gui.nextcloud_panel import open_connect_dialog, open_file_browser
from ac_updater.nextcloud_client import NextcloudClient
from ac_updater.selection_store import save_selection
from ac_updater.share_config import load_share_path, save_share_path

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

        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)

        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        for item in items:
            var = tk.BooleanVar(value=True)
            self._vars[item] = var
            ttk.Checkbutton(inner, text=item, variable=var).pack(anchor="w", pady=1)

    def _select_all(self) -> None:
        for var in self._vars.values():
            var.set(True)

    def _deselect_all(self) -> None:
        for var in self._vars.values():
            var.set(False)

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
        self._nb.add(tab2, text="  Server Update  ")
        self._nb.add(tab3, text="  Nextcloud  ")
        self._nb.add(tab4, text="  Archive  ")

        self._build_content_tab(tab1, content)
        self._build_server_tab(tab2)
        self._build_nextcloud_tab(tab3)
        self._build_archive_tab(tab4)

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
        share_row = ttk.Frame(parent)
        share_row.pack(fill="x", pady=(0, 12))
        ttk.Label(share_row, text="Network Share:", font=("", 9, "bold")).pack(side="left")
        self._share_path_label = ttk.Label(share_row, text=str(self._share_path))
        self._share_path_label.pack(side="left", padx=(6, 4))
        ttk.Button(share_row, text="Change...", command=self._on_change_share).pack(side="left")

        self._server_btn = ttk.Button(
            parent, text="Server Content Update", command=self._on_server_update
        )
        self._server_btn.pack(anchor="w", pady=(0, 14))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(0, 8))

        lbl_row = ttk.Frame(parent)
        lbl_row.pack(fill="x", pady=(0, 4))
        ttk.Label(lbl_row, text="Results", font=("", 9, "bold")).pack(side="left")
        ttk.Button(lbl_row, text="Clear", command=self._clear_server_results).pack(side="right")

        result_frame = ttk.Frame(parent, relief="sunken", borderwidth=1)
        result_frame.pack(fill="both", expand=True)
        self._server_result = tk.Text(
            result_frame,
            height=8,
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

    def _on_change_dir(self) -> None:
        chosen = filedialog.askdirectory(
            title="Select Assetto Corsa install folder", mustexist=True
        )
        if not chosen:
            return
        new_dir = Path(chosen)
        log.info("User changed AC install dir: %s  →  %s", self._install_dir, new_dir)
        self._install_dir = new_dir
        self._install_path_label.configure(text=str(new_dir))
        for panel in self._panels.values():
            panel.destroy()
        self._panels.clear()
        self._build_panels(scan_content(new_dir))
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
# Helpers
# ------------------------------------------------------------------


def _default_archive_name(selection: dict[str, list[str]]) -> str:
    non_empty = sorted(cat for cat, items in selection.items() if items)
    if len(non_empty) == 1:
        return f"{non_empty[0]}.7z"
    return "content.7z"


def run() -> None:
    setup_logging()
    log.info("run() called")

    install_dir = find_ac_install()
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

    log.info("AC install dir: %s", install_dir)
    content = scan_content(install_dir)
    log.info(
        "Content scan: %s",
        "  ".join(f"{cat}={len(items)}" for cat, items in content.items()),
    )
    app = _App(install_dir, content)
    app.mainloop()
    log.info("App exited")
