from __future__ import annotations

import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ac_updater.ac_finder import find_ac_install
from ac_updater.archiver import create_archive
from ac_updater.content_scanner import scan_content
from ac_updater.gui.nextcloud_panel import open_connect_dialog, open_file_browser
from ac_updater.nextcloud_client import NextcloudClient
from ac_updater.selection_store import save_selection

_SELECTION_FILE = Path("selections") / "selection.txt"
_WINDOW_TITLE = "AC Server Content Updater"
_WINDOW_SIZE = "980x640"

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
        self._panels: dict[str, _ChecklistPanel] = {}
        self._nc_client: NextcloudClient | None = None

        self._build_header(install_dir)
        self._panel_area = ttk.Frame(self, padding=(10, 0, 10, 0))
        self._panel_area.pack(fill="both", expand=True)
        self._build_panels(content)
        self._build_footer()

    # ------------------------------------------------------------------
    # Layout builders
    # ------------------------------------------------------------------

    def _build_header(self, install_dir: Path) -> None:
        header = ttk.Frame(self, padding=(10, 8))
        header.pack(fill="x")
        ttk.Label(header, text="AC Install:", font=("", 9, "bold")).pack(side="left")
        self._install_path_label = ttk.Label(header, text=str(install_dir))
        self._install_path_label.pack(side="left", padx=(6, 12))
        ttk.Button(header, text="Change...", command=self._on_change_dir).pack(side="left")

    def _build_panels(self, content: dict[str, list[str]]) -> None:
        for category, items in content.items():
            panel = _ChecklistPanel(self._panel_area, title=category.title(), items=items)
            panel.pack(side="left", fill="both", expand=True, padx=(0, 6))
            self._panels[category] = panel

    def _build_footer(self) -> None:
        footer = ttk.Frame(self, padding=(10, 6))
        footer.pack(fill="x", side="bottom")

        # Status label (left)
        self._status_var = tk.StringVar()
        self._status_label = ttk.Label(footer, textvariable=self._status_var, foreground="gray")
        self._status_label.pack(side="left")

        # Indeterminate progress bar (hidden until an operation starts)
        self._progress = ttk.Progressbar(footer, mode="indeterminate", length=160)

        # Buttons (right, declared right-to-left so they appear left-to-right)
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
        self._upload_btn.pack(side="right")

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

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_change_dir(self) -> None:
        chosen = filedialog.askdirectory(
            title="Select Assetto Corsa install folder", mustexist=True
        )
        if not chosen:
            return
        new_dir = Path(chosen)
        self._install_dir = new_dir
        self._install_path_label.configure(text=str(new_dir))
        for panel in self._panels.values():
            panel.destroy()
        self._panels.clear()
        self._build_panels(scan_content(new_dir))
        self._set_status(f"Loaded content from {new_dir}", _GREEN)

    def _on_save(self) -> None:
        selection = {cat: panel.get_selected() for cat, panel in self._panels.items()}
        try:
            save_selection(_SELECTION_FILE, selection)
            total = sum(len(v) for v in selection.values())
            self._set_status(f"Saved {total} items → {_SELECTION_FILE}", _GREEN)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))

    def _get_selection(self) -> dict[str, list[str]] | None:
        selection = {cat: panel.get_selected() for cat, panel in self._panels.items()}
        if not any(selection.values()):
            messagebox.showwarning(
                "Nothing selected", "Tick at least one item before creating an archive."
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
        self._start_progress("Creating archive…")
        self._archive_btn.state(["disabled"])
        self._upload_btn.state(["disabled"])

        def _worker() -> None:
            try:
                create_archive(install_dir, selection, output_path)
                self.after(0, self._stop_progress)
                self.after(0, lambda: self._set_status(f"Archive saved → {output_path}", _GREEN))
            except FileNotFoundError as exc:
                err = str(exc)
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("7-Zip not found", err))
                self.after(0, lambda: self._set_status("Archive failed — 7-Zip not found", _RED))
            except subprocess.CalledProcessError as exc:
                msg = f"7-Zip exited with code {exc.returncode}"
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("Archive failed", msg))
                self.after(0, lambda: self._set_status("Archive failed", _RED))
            finally:
                self.after(0, lambda: self._archive_btn.state(["!disabled"]))
                self.after(0, lambda: self._upload_btn.state(["!disabled"]))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_create_upload(self) -> None:
        selection = self._get_selection()
        if selection is None:
            return

        # Ensure we have a Nextcloud connection
        if self._nc_client is None:
            self._nc_client = open_connect_dialog(self)
        if self._nc_client is None:
            return  # User cancelled

        install_dir = self._install_dir
        nc_client = self._nc_client

        # Create archive in a temp file, then open file browser for upload
        tmp_path = Path(tempfile.mktemp(suffix=".7z"))
        self._start_progress("Creating archive…")
        self._archive_btn.state(["disabled"])
        self._upload_btn.state(["disabled"])

        def _worker() -> None:
            try:
                create_archive(install_dir, selection, tmp_path)
                self.after(0, lambda: self._on_archive_ready(nc_client, tmp_path))
            except FileNotFoundError as exc:
                err = str(exc)
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("7-Zip not found", err))
                self.after(0, lambda: self._set_status("Archive failed — 7-Zip not found", _RED))
                self.after(0, lambda: self._archive_btn.state(["!disabled"]))
                self.after(0, lambda: self._upload_btn.state(["!disabled"]))
            except subprocess.CalledProcessError as exc:
                msg = f"7-Zip exited with code {exc.returncode}"
                self.after(0, self._stop_progress)
                self.after(0, lambda: messagebox.showerror("Archive failed", msg))
                self.after(0, lambda: self._set_status("Archive failed", _RED))
                self.after(0, lambda: self._archive_btn.state(["!disabled"]))
                self.after(0, lambda: self._upload_btn.state(["!disabled"]))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_archive_ready(self, nc_client: NextcloudClient, tmp_path: Path) -> None:
        self._stop_progress()
        self._set_status("Archive ready — select upload destination…", _ORANGE)
        uploaded = open_file_browser(self, nc_client, archive_path=tmp_path)
        if uploaded:
            self._set_status("Upload complete ✓", _GREEN)
        else:
            self._set_status("Upload cancelled", "gray")
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._archive_btn.state(["!disabled"])
        self._upload_btn.state(["!disabled"])


def run() -> None:
    install_dir = find_ac_install()
    if install_dir is None:
        root = tk.Tk()
        root.withdraw()
        chosen = filedialog.askdirectory(
            title="Locate Assetto Corsa install folder", mustexist=True
        )
        root.destroy()
        if not chosen:
            return
        install_dir = Path(chosen)

    content = scan_content(install_dir)
    app = _App(install_dir, content)
    app.mainloop()
