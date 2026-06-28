from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import tkinter as tk
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
_WINDOW_SIZE = "1060x640"

_GREEN = "#27ae60"
_RED = "#c0392b"
_ORANGE = "#e67e00"


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
        self._panel_area = ttk.Frame(self, padding=(10, 0, 10, 0))
        self._panel_area.pack(fill="both", expand=True)
        self._build_panels(content)
        self._build_footer()

    # ------------------------------------------------------------------
    # Layout builders
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(10, 8))
        header.pack(fill="x")

        ttk.Label(header, text="AC Install:", font=("", 9, "bold")).pack(side="left")
        self._install_path_label = ttk.Label(header, text=str(self._install_dir))
        self._install_path_label.pack(side="left", padx=(6, 4))
        ttk.Button(header, text="Change...", command=self._on_change_dir).pack(
            side="left", padx=(0, 16)
        )

        ttk.Separator(header, orient="vertical").pack(side="left", fill="y", padx=(0, 16))

        ttk.Label(header, text="Share:", font=("", 9, "bold")).pack(side="left")
        self._share_path_label = ttk.Label(header, text=str(self._share_path))
        self._share_path_label.pack(side="left", padx=(6, 4))
        ttk.Button(header, text="Change...", command=self._on_change_share).pack(side="left")

    def _build_panels(self, content: dict[str, list[str]]) -> None:
        for category, items in content.items():
            panel = _ChecklistPanel(self._panel_area, title=category.title(), items=items)
            panel.pack(side="left", fill="both", expand=True, padx=(0, 6))
            self._panels[category] = panel

    def _build_footer(self) -> None:
        footer = ttk.Frame(self, padding=(10, 6))
        footer.pack(fill="x", side="bottom")

        self._status_var = tk.StringVar()
        self._status_label = ttk.Label(footer, textvariable=self._status_var, foreground="gray")
        self._status_label.pack(side="left")

        self._progress = ttk.Progressbar(footer, mode="indeterminate", length=160)

        ttk.Button(footer, text="Save Selection", command=self._on_save).pack(
            side="right", padx=(6, 0)
        )
        self._archive_btn = ttk.Button(
            footer, text="Create Archive", command=self._on_create_archive
        )
        self._archive_btn.pack(side="right", padx=(6, 0))
        self._upload_btn = ttk.Button(
            footer, text="Create & Upload to Nextcloud", command=self._on_create_upload
        )
        self._upload_btn.pack(side="right", padx=(6, 0))
        self._server_btn = ttk.Button(
            footer, text="Server Content Update", command=self._on_server_update
        )
        self._server_btn.pack(side="right")

    # ------------------------------------------------------------------
    # Status / progress helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str, color: str = "gray") -> None:
        self._status_var.set(text)
        self._status_label.configure(foreground=color)

    def _start_progress(self, message: str) -> None:
        self._set_status(message, _ORANGE)
        self._progress.pack(side="left", padx=(10, 0))
        self._progress.start(12)

    def _stop_progress(self) -> None:
        self._progress.stop()
        self._progress.pack_forget()

    def _disable_buttons(self) -> None:
        for btn in (self._archive_btn, self._upload_btn, self._server_btn):
            btn.state(["disabled"])

    def _enable_buttons(self) -> None:
        for btn in (self._archive_btn, self._upload_btn, self._server_btn):
            btn.state(["!disabled"])

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
    # Actions — footer
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
                "Nothing selected", "Tick at least one item before proceeding."
            )
            return None
        return selection

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
        log.info("Create Archive initiated: output=%s", output_path)
        self._start_progress("Creating archive…")
        self._disable_buttons()

        def _worker() -> None:
            try:
                create_archive(install_dir, selection, output_path)
                self.after(0, self._stop_progress)
                self.after(0, lambda: self._set_status(f"Archive saved → {output_path}", _GREEN))
            except FileNotFoundError as exc:
                err = str(exc)
                log.error("Create Archive failed — 7-Zip not found: %s", exc)
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("7-Zip not found", err))
                self.after(0, lambda: self._set_status("Archive failed — 7-Zip not found", _RED))
            except subprocess.CalledProcessError as exc:
                msg = f"7-Zip exited with code {exc.returncode}"
                log.error("Create Archive failed: %s", msg)
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("Archive failed", msg))
                self.after(0, lambda: self._set_status("Archive failed", _RED))
            finally:
                self.after(0, self._enable_buttons)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_create_upload(self) -> None:
        selection = self._get_selection()
        if selection is None:
            return

        if self._nc_client is None:
            log.info("No Nextcloud client — opening connection dialog")
            self._nc_client = open_connect_dialog(self)
        if self._nc_client is None:
            log.info("Nextcloud connect dialog cancelled")
            return

        install_dir = self._install_dir
        nc_client = self._nc_client
        default_name = _default_archive_name(selection)

        # mkstemp atomically creates a unique file; unlink so 7-zip creates the archive fresh
        _fd, _tmp = tempfile.mkstemp(suffix=".7z")
        os.close(_fd)
        os.unlink(_tmp)
        tmp_path = Path(_tmp)

        log.info(
            "Create & Upload initiated: tmp=%s  default_name=%s", tmp_path, default_name
        )
        self._start_progress("Creating archive…")
        self._disable_buttons()

        def _worker() -> None:
            try:
                create_archive(install_dir, selection, tmp_path)
                self.after(0, lambda: self._on_archive_ready(nc_client, tmp_path, default_name))
            except FileNotFoundError as exc:
                err = str(exc)
                log.error("Create & Upload — archive failed (7-Zip not found): %s", exc)
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("7-Zip not found", err))
                self.after(0, lambda: self._set_status("Archive failed — 7-Zip not found", _RED))
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
            self._set_status("Upload cancelled", "gray")
        try:
            tmp_path.unlink(missing_ok=True)
            log.debug("Temp archive cleaned up: %s", tmp_path)
        except OSError as exc:
            log.warning("Could not clean up temp archive %s: %s", tmp_path, exc)
        self._enable_buttons()

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
        base = f"Copied {result.copied} file(s)"
        if result.errors:
            detail = "\n".join(result.errors[:15])
            if len(result.errors) > 15:
                detail += f"\n…and {len(result.errors) - 15} more"
            messagebox.showerror("Copy errors", detail)
            self._set_status(f"{base}, {len(result.errors)} error(s)", _RED)
        elif result.skipped:
            self._set_status(
                f"{base} to {share_path} ({result.skipped} not found in AC install)", _ORANGE
            )
        else:
            self._set_status(f"{base} to {share_path}", _GREEN)


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
