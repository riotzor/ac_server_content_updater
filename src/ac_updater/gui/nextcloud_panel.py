"""Nextcloud connection dialog, embeddable file browser, log handler, and tooltip helper."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from urllib.parse import urlparse

from ac_updater.nextcloud_client import NextcloudClient, NextcloudError, RemoteFile
from ac_updater.nextcloud_config import load_credentials, save_credentials

log = logging.getLogger(__name__)

_GREEN = "#27ae60"
_RED = "#c0392b"
_ORANGE = "#e67e00"


# ---------------------------------------------------------------------------
# Tooltip helper
# ---------------------------------------------------------------------------


def add_tooltip(widget: tk.Widget, text: str) -> None:
    """Attach a simple hover tooltip to a widget."""
    _tip: list[tk.Toplevel | None] = [None]

    def _enter(_event: object) -> None:
        if _tip[0] is not None:
            return
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        x = widget.winfo_rootx() + 20
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tip.wm_geometry(f"+{x}+{y}")
        ttk.Label(
            tip, text=text, background="#ffffe0", relief="solid",
            borderwidth=1, padding=(6, 3), wraplength=320,
        ).pack()
        _tip[0] = tip

    def _leave(_event: object) -> None:
        if _tip[0]:
            _tip[0].destroy()
            _tip[0] = None

    widget.bind("<Enter>", _enter, add="+")
    widget.bind("<Leave>", _leave, add="+")


# ---------------------------------------------------------------------------
# Live-log handler for tk.Text
# ---------------------------------------------------------------------------


class TkLogHandler(logging.Handler):
    """Logging handler that appends formatted records to a read-only tk.Text widget."""

    def __init__(self, text_widget: tk.Text) -> None:
        super().__init__(level=logging.INFO)
        self._widget = text_widget
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        try:
            self._widget.after(0, lambda: self._append(msg))
        except Exception:
            self.handleError(record)

    def _append(self, msg: str) -> None:
        try:
            self._widget.configure(state="normal")
            self._widget.insert("end", msg)
            self._widget.see("end")
            self._widget.configure(state="disabled")
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# Connection dialog
# ---------------------------------------------------------------------------


class _ConnectDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("Connect to Nextcloud")
        self.resizable(False, False)
        self.result: NextcloudClient | None = None
        self._build()
        self.grab_set()
        self._load_saved()

    def _build(self) -> None:
        f = ttk.Frame(self, padding=20)
        f.pack(fill="both", expand=True)

        labels = ("Server URL:", "Username:", "Password:")
        self._url_var = tk.StringVar()
        self._user_var = tk.StringVar()
        self._pass_var = tk.StringVar()
        entries = (
            ttk.Entry(f, textvariable=self._url_var, width=42),
            ttk.Entry(f, textvariable=self._user_var, width=42),
            ttk.Entry(f, textvariable=self._pass_var, show="●", width=42),
        )
        for row, (lbl, ent) in enumerate(zip(labels, entries)):
            ttk.Label(f, text=lbl).grid(row=row, column=0, sticky="e", pady=5)
            ent.grid(row=row, column=1, padx=(10, 0), pady=5)

        self._status_var = tk.StringVar()
        self._status_lbl = ttk.Label(f, textvariable=self._status_var)
        self._status_lbl.grid(row=3, column=0, columnspan=2, pady=(10, 0))

        btns = ttk.Frame(f)
        btns.grid(row=4, column=0, columnspan=2, pady=(14, 0))
        ttk.Button(btns, text="Test Connection", command=self._on_test).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        self._connect_btn = ttk.Button(btns, text="Save & Connect", command=self._on_connect)
        self._connect_btn.pack(side="left", padx=4)
        self._connect_btn.state(["disabled"])

    def _load_saved(self) -> None:
        creds = load_credentials()
        if creds:
            url, user, pwd = creds
            self._url_var.set(url)
            self._user_var.set(user)
            self._pass_var.set(pwd)

    def _make_client(self) -> NextcloudClient | None:
        url = self._url_var.get().strip()
        user = self._user_var.get().strip()
        pwd = self._pass_var.get()
        if not url or not user or not pwd:
            messagebox.showwarning("Missing fields", "Please fill in all fields.", parent=self)
            return None
        return NextcloudClient(url, user, pwd)

    def _on_test(self) -> None:
        client = self._make_client()
        if client is None:
            return
        url = self._url_var.get().strip()
        scheme = urlparse(url).scheme.lower()
        if scheme != "https":
            log.warning("Connection test requested over non-HTTPS URL: %s", url)
            if not messagebox.askyesno(
                "Insecure connection",
                "The URL does not use HTTPS.\n\n"
                "Your credentials will be sent without encryption.\n\n"
                "Continue anyway?",
                icon="warning",
                parent=self,
            ):
                return
        log.info("Testing Nextcloud connection: %s", url)
        self._status_var.set("Testing connection…")
        self._status_lbl.configure(foreground="gray")
        self._connect_btn.state(["disabled"])

        def _check() -> None:
            ok = client.test_connection()
            if ok:
                log.info("Nextcloud connection test succeeded")
                self.after(0, lambda: self._status_var.set("Connected ✓"))
                self.after(0, lambda: self._status_lbl.configure(foreground=_GREEN))
                self.after(0, lambda: self._connect_btn.state(["!disabled"]))
            else:
                log.warning("Nextcloud connection test failed")
                self.after(0, lambda: self._status_var.set("Failed — check URL and credentials"))
                self.after(0, lambda: self._status_lbl.configure(foreground=_RED))

        threading.Thread(target=_check, daemon=True).start()

    def _on_connect(self) -> None:
        client = self._make_client()
        if client is None:
            return
        url = self._url_var.get().strip()
        username = self._user_var.get().strip()
        save_credentials(url, username, self._pass_var.get())
        log.info("Nextcloud credentials saved and client connected: user='%s'", username)
        self.result = client
        self.destroy()


# ---------------------------------------------------------------------------
# Embeddable file browser panel
# ---------------------------------------------------------------------------


class FileBrowserPanel(ttk.Frame):
    """Nextcloud file browser suitable for embedding directly in a parent frame.

    Call set_client() after connecting.  Call set_archive() to expose the
    upload controls for a locally-created archive; clear_archive() hides them.
    """

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self._client: NextcloudClient | None = None
        self._current_path = ""
        self._archive_path: Path | None = None
        self._archive_name = "upload.7z"
        self._on_upload_done: Callable[[bool], None] | None = None
        self._on_upload_progress: Callable[[int, int], None] | None = None
        self._build()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_client(self, client: NextcloudClient) -> None:
        self._client = client
        self._current_path = ""
        self._update_path_display()
        self._refresh()

    def set_archive(
        self,
        path: Path,
        name: str,
        on_done: Callable[[bool], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Show the upload area for an archive that is ready to upload."""
        self._archive_path = path
        self._archive_name = name
        self._on_upload_done = on_done
        self._on_upload_progress = on_progress
        self._upload_name_var.set(name)
        self._update_path_display()
        self._upload_btn.state(["!disabled"])
        self._upload_footer.pack(fill="x")

    def clear_archive(self) -> None:
        """Hide the upload area without affecting navigation."""
        self._archive_path = None
        self._on_upload_done = None
        self._on_upload_progress = None
        self._upload_footer.pack_forget()
        self._hide_upload_progress()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        # Toolbar
        bar = ttk.Frame(self, padding=(4, 4, 4, 2))
        bar.pack(fill="x")
        self._path_var = tk.StringVar(value="/")
        ttk.Label(bar, textvariable=self._path_var, font=("", 9, "bold")).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self._refresh).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="↑  Up", command=self._go_up).pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # Treeview
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self._tree = ttk.Treeview(
            tree_frame, columns=("icon", "name", "size"), show="headings", selectmode="browse"
        )
        self._tree.heading("icon", text="")
        self._tree.heading("name", text="Name")
        self._tree.heading("size", text="Size")
        self._tree.column("icon", width=28, stretch=False, anchor="center")
        self._tree.column("name", width=380)
        self._tree.column("size", width=90, anchor="e")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-1>", self._on_double_click)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # CRUD toolbar
        crud = ttk.Frame(self, padding=(4, 4))
        crud.pack(fill="x")
        ttk.Button(crud, text="New Folder", command=self._on_new_folder).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(crud, text="Rename", command=self._on_rename).pack(side="left", padx=(0, 4))
        ttk.Button(crud, text="Delete", command=self._on_delete).pack(side="left")
        self._status_var = tk.StringVar()
        self._status_lbl = ttk.Label(crud, textvariable=self._status_var, foreground="gray")
        self._status_lbl.pack(side="left", padx=(12, 0))

        # Upload footer — hidden until set_archive() is called
        self._upload_footer = ttk.Frame(self, padding=(4, 0, 4, 4))

        ttk.Separator(self._upload_footer, orient="horizontal").pack(fill="x", pady=(0, 6))

        dest_row = ttk.Frame(self._upload_footer)
        dest_row.pack(fill="x", pady=(0, 4))
        self._dest_var = tk.StringVar(value="Destination: /")
        ttk.Label(dest_row, textvariable=self._dest_var, foreground="gray").pack(side="left")

        name_row = ttk.Frame(self._upload_footer)
        name_row.pack(fill="x")
        ttk.Label(name_row, text="Filename:").pack(side="left")
        self._upload_name_var = tk.StringVar()
        ttk.Entry(name_row, textvariable=self._upload_name_var, width=32).pack(
            side="left", padx=(6, 0)
        )
        self._upload_btn = ttk.Button(name_row, text="Upload Here", command=self._on_upload)
        self._upload_btn.pack(side="right")

        # Upload progress (inside footer, hidden until upload starts)
        self._prog_frame = ttk.Frame(self._upload_footer)
        self._prog_bar = ttk.Progressbar(self._prog_frame, mode="determinate", maximum=100)
        self._prog_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._prog_label_var = tk.StringVar()
        ttk.Label(
            self._prog_frame, textvariable=self._prog_label_var, width=22, anchor="e"
        ).pack(side="left")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str, color: str = "gray") -> None:
        self._status_var.set(text)
        self._status_lbl.configure(foreground=color)

    def _show_upload_progress(self, sent: int, total: int) -> None:
        pct = int(sent / total * 100) if total else 100
        self._prog_bar.configure(value=pct)
        self._prog_label_var.set(f"{sent / 1_048_576:.1f} / {total / 1_048_576:.1f} MB")
        if not self._prog_frame.winfo_ismapped():
            self._prog_frame.pack(fill="x", pady=(4, 0))

    def _hide_upload_progress(self) -> None:
        self._prog_frame.pack_forget()
        self._prog_bar.configure(value=0)
        self._prog_label_var.set("")

    def _selected(self) -> RemoteFile | None:
        sel = self._tree.selection()
        if not sel:
            return None
        iid = sel[0]
        values = self._tree.item(iid, "values")
        tags = self._tree.item(iid, "tags")
        return RemoteFile(
            name=str(values[1]),
            path=iid,
            is_dir="dir" in tags,
            size_bytes=None,
        )

    def _update_path_display(self) -> None:
        display = f"/{self._current_path}"
        self._path_var.set(display)
        if self._archive_path:
            self._dest_var.set(f"Destination: {display}")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        if self._client is None:
            return
        self._tree.delete(*self._tree.get_children())
        self._set_status("Loading…")
        path = self._current_path
        client = self._client

        def _load() -> None:
            try:
                files = client.list_files(path)
                self.after(0, lambda: self._populate(files))
                self.after(0, lambda: self._set_status(""))
            except NextcloudError as exc:
                err = str(exc)
                self.after(0, lambda: self._set_status(f"Error: {err}", _RED))

        threading.Thread(target=_load, daemon=True).start()

    def _populate(self, files: list[RemoteFile]) -> None:
        self._tree.delete(*self._tree.get_children())
        for f in files:
            icon = "📁" if f.is_dir else "📄"
            size_str = (
                _fmt_size(f.size_bytes) if not f.is_dir and f.size_bytes is not None else ""
            )
            tag = "dir" if f.is_dir else "file"
            self._tree.insert(
                "", "end", iid=f.path, values=(icon, f.name, size_str), tags=(tag,)
            )

    def _on_double_click(self, _event: object) -> None:
        f = self._selected()
        if f and f.is_dir:
            self._current_path = f.path
            self._update_path_display()
            self._refresh()

    def _go_up(self) -> None:
        stripped = self._current_path.rstrip("/")
        self._current_path = stripped.rsplit("/", 1)[0] if "/" in stripped else ""
        self._update_path_display()
        self._refresh()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def _on_new_folder(self) -> None:
        name = simpledialog.askstring("New Folder", "Folder name:", parent=self)
        if not name:
            return
        remote = f"{self._current_path}/{name}".lstrip("/")
        log.info("Creating remote directory: %s", remote)
        self._set_status("Creating…", _ORANGE)
        client = self._client

        def _do() -> None:
            try:
                client.create_directory(remote)  # type: ignore[union-attr]
                log.info("Directory created: %s", remote)
                self.after(0, lambda: self._set_status(f"Created '{name}'", _GREEN))
                self.after(0, self._refresh)
            except NextcloudError as exc:
                err = str(exc)
                log.error("Failed to create directory '%s': %s", remote, exc)
                self.after(0, lambda: self._set_status(f"Error: {err}", _RED))

        threading.Thread(target=_do, daemon=True).start()

    def _on_rename(self) -> None:
        f = self._selected()
        if not f:
            messagebox.showwarning("Nothing selected", "Select an item first.", parent=self)
            return
        new_name = simpledialog.askstring(
            "Rename", f"Rename '{f.name}' to:", initialvalue=f.name, parent=self
        )
        if not new_name or new_name == f.name:
            return
        parent_dir = f.path.rsplit("/", 1)[0] if "/" in f.path else ""
        new_path = f"{parent_dir}/{new_name}".lstrip("/")
        self._set_status("Renaming…", _ORANGE)
        current_path = f.path
        log.info("Renaming: %s  →  %s", current_path, new_path)
        client = self._client

        def _do() -> None:
            try:
                client.rename(current_path, new_path)  # type: ignore[union-attr]
                log.info("Renamed: %s  →  %s", current_path, new_path)
                self.after(0, lambda: self._set_status(f"Renamed to '{new_name}'", _GREEN))
                self.after(0, self._refresh)
            except NextcloudError as exc:
                err = str(exc)
                log.error("Rename failed (%s → %s): %s", current_path, new_path, exc)
                self.after(0, lambda: self._set_status(f"Error: {err}", _RED))

        threading.Thread(target=_do, daemon=True).start()

    def _on_delete(self) -> None:
        f = self._selected()
        if not f:
            messagebox.showwarning("Nothing selected", "Select an item first.", parent=self)
            return
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete '{f.name}'?\nThis cannot be undone.",
            parent=self,
        ):
            return
        log.info("Deleting remote item: %s", f.path)
        self._set_status("Deleting…", _ORANGE)
        target = f.path
        name = f.name
        client = self._client

        def _do() -> None:
            try:
                client.delete(target)  # type: ignore[union-attr]
                log.info("Deleted: %s", target)
                self.after(0, lambda: self._set_status(f"Deleted '{name}'", _GREEN))
                self.after(0, self._refresh)
            except NextcloudError as exc:
                err = str(exc)
                log.error("Delete failed (%s): %s", target, exc)
                self.after(0, lambda: self._set_status(f"Error: {err}", _RED))

        threading.Thread(target=_do, daemon=True).start()

    def _on_upload(self) -> None:
        if not self._archive_path or self._client is None:
            return
        archive_path = self._archive_path
        archive_name = self._upload_name_var.get().strip() or self._archive_name
        remote = f"{self._current_path}/{archive_name}".lstrip("/")
        log.info("Upload initiated: local=%s  remote=%s", archive_path, remote)
        self._set_status(f"Uploading {archive_name}…", _ORANGE)
        self._upload_btn.state(["disabled"])
        client = self._client
        callback = self._on_upload_done
        ext_progress = self._on_upload_progress

        def on_progress(sent: int, total: int) -> None:
            self.after(0, lambda: self._show_upload_progress(sent, total))
            if ext_progress is not None:
                ep = ext_progress
                self.after(0, lambda: ep(sent, total))

        def _do() -> None:
            success = False
            try:
                client.upload_file(archive_path, remote, on_progress=on_progress)
                success = True
                log.info("Upload succeeded: %s", remote)
                self.after(0, self._hide_upload_progress)
                self.after(0, lambda: self._set_status(f"Uploaded ✓  →  /{remote}", _GREEN))
                self.after(0, self._refresh)
            except (NextcloudError, OSError) as exc:
                err = str(exc)
                log.error("Upload failed: %s", exc)
                self.after(0, self._hide_upload_progress)
                self.after(0, lambda: self._set_status(f"Upload failed: {err}", _RED))
                self.after(0, lambda: self._upload_btn.state(["!disabled"]))
            finally:
                if callback is not None:
                    done = success
                    self.after(0, lambda: callback(done))

        threading.Thread(target=_do, daemon=True).start()


# ---------------------------------------------------------------------------
# Standalone dialog wrapper (kept for archive-tab compatibility)
# ---------------------------------------------------------------------------


class _FileBrowserDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        client: NextcloudClient,
        archive_path: Path | None = None,
        archive_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Nextcloud Files")
        self.geometry("740x540")
        self.upload_successful = False
        self._panel = FileBrowserPanel(self)
        self._panel.pack(fill="both", expand=True)
        self._panel.set_client(client)
        if archive_path is not None:
            eff_name = archive_name or archive_path.name

            def _done(success: bool) -> None:
                self.upload_successful = success

            self._panel.set_archive(archive_path, eff_name, on_done=_done)
        self.grab_set()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def open_connect_dialog(parent: tk.Misc) -> NextcloudClient | None:
    dlg = _ConnectDialog(parent)
    parent.wait_window(dlg)
    return dlg.result


def open_file_browser(
    parent: tk.Misc,
    client: NextcloudClient,
    *,
    archive_path: Path | None = None,
    archive_name: str | None = None,
) -> bool:
    """Open the file browser as a standalone dialog. Returns True if upload completed."""
    dlg = _FileBrowserDialog(
        parent, client, archive_path=archive_path, archive_name=archive_name
    )
    parent.wait_window(dlg)
    return dlg.upload_successful


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _fmt_size(size_bytes: int) -> str:
    value: float = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"
