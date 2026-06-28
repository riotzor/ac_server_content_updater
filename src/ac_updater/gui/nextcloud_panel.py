"""Nextcloud connection dialog and file browser panel."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from ac_updater.nextcloud_client import NextcloudClient, NextcloudError, RemoteFile
from ac_updater.nextcloud_config import load_credentials, save_credentials

_GREEN = "#27ae60"
_RED = "#c0392b"
_ORANGE = "#e67e00"


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
        self._status_var.set("Testing connection…")
        self._status_lbl.configure(foreground="gray")
        self._connect_btn.state(["disabled"])

        def _check() -> None:
            ok = client.test_connection()
            if ok:
                self.after(0, lambda: self._status_var.set("Connected ✓"))
                self.after(0, lambda: self._status_lbl.configure(foreground=_GREEN))
                self.after(0, lambda: self._connect_btn.state(["!disabled"]))
            else:
                self.after(0, lambda: self._status_var.set("Failed — check URL and credentials"))
                self.after(0, lambda: self._status_lbl.configure(foreground=_RED))

        threading.Thread(target=_check, daemon=True).start()

    def _on_connect(self) -> None:
        client = self._make_client()
        if client is None:
            return
        save_credentials(
            self._url_var.get().strip(),
            self._user_var.get().strip(),
            self._pass_var.get(),
        )
        self.result = client
        self.destroy()


# ---------------------------------------------------------------------------
# File browser dialog
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
        self._client = client
        self._archive_path = archive_path
        self._archive_name = archive_name or (archive_path.name if archive_path else "upload.7z")
        self._current_path = ""
        self.upload_successful = False
        self._build()
        self.grab_set()
        self._refresh()

    def _build(self) -> None:
        # Toolbar
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")
        self._path_var = tk.StringVar(value="/")
        ttk.Label(bar, textvariable=self._path_var, font=("", 9, "bold")).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self._refresh).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="↑  Up", command=self._go_up).pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # Treeview
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self._tree = ttk.Treeview(
            tree_frame, columns=("icon", "name", "size"), show="headings", selectmode="browse"
        )
        self._tree.heading("icon", text="")
        self._tree.heading("name", text="Name")
        self._tree.heading("size", text="Size")
        self._tree.column("icon", width=28, stretch=False, anchor="center")
        self._tree.column("name", width=460)
        self._tree.column("size", width=100, anchor="e")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-1>", self._on_double_click)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # CRUD toolbar
        crud = ttk.Frame(self, padding=(8, 5))
        crud.pack(fill="x")
        ttk.Button(crud, text="New Folder", command=self._on_new_folder).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(crud, text="Rename", command=self._on_rename).pack(side="left", padx=(0, 4))
        ttk.Button(crud, text="Delete", command=self._on_delete).pack(side="left")
        self._status_var = tk.StringVar()
        self._status_lbl = ttk.Label(crud, textvariable=self._status_var, foreground="gray")
        self._status_lbl.pack(side="left", padx=(16, 0))

        # Upload footer (only when an archive is being queued for upload)
        if self._archive_path:
            ttk.Separator(self, orient="horizontal").pack(fill="x")
            dest_row = ttk.Frame(self, padding=(8, 4, 8, 0))
            dest_row.pack(fill="x")
            self._dest_var = tk.StringVar(value="Destination: /")
            ttk.Label(dest_row, textvariable=self._dest_var, foreground="gray").pack(side="left")

            name_row = ttk.Frame(self, padding=(8, 4, 8, 6))
            name_row.pack(fill="x")
            ttk.Label(name_row, text="Filename:").pack(side="left")
            self._upload_name_var = tk.StringVar(value=self._archive_name)
            ttk.Entry(name_row, textvariable=self._upload_name_var, width=28).pack(
                side="left", padx=(6, 0)
            )
            ttk.Button(name_row, text="Cancel", command=self.destroy).pack(
                side="right", padx=(6, 0)
            )
            self._upload_btn = ttk.Button(
                name_row, text="Upload Here", command=self._on_upload
            )
            self._upload_btn.pack(side="right")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str, color: str = "gray") -> None:
        self._status_var.set(text)
        self._status_lbl.configure(foreground=color)

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
        self._tree.delete(*self._tree.get_children())
        self._set_status("Loading…")
        path = self._current_path

        def _load() -> None:
            try:
                files = self._client.list_files(path)
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
            size_str = _fmt_size(f.size_bytes) if not f.is_dir and f.size_bytes is not None else ""
            tag = "dir" if f.is_dir else "file"
            self._tree.insert("", "end", iid=f.path, values=(icon, f.name, size_str), tags=(tag,))

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
        self._set_status("Creating…", _ORANGE)

        def _do() -> None:
            try:
                self._client.create_directory(remote)
                self.after(0, lambda: self._set_status(f"Created '{name}'", _GREEN))
                self.after(0, self._refresh)
            except NextcloudError as exc:
                err = str(exc)
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

        def _do() -> None:
            try:
                self._client.rename(current_path, new_path)
                self.after(0, lambda: self._set_status(f"Renamed to '{new_name}'", _GREEN))
                self.after(0, self._refresh)
            except NextcloudError as exc:
                err = str(exc)
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
        self._set_status("Deleting…", _ORANGE)
        target = f.path
        name = f.name

        def _do() -> None:
            try:
                self._client.delete(target)
                self.after(0, lambda: self._set_status(f"Deleted '{name}'", _GREEN))
                self.after(0, self._refresh)
            except NextcloudError as exc:
                err = str(exc)
                self.after(0, lambda: self._set_status(f"Error: {err}", _RED))

        threading.Thread(target=_do, daemon=True).start()

    def _on_upload(self) -> None:
        if not self._archive_path:
            return
        archive_path = self._archive_path
        archive_name = self._upload_name_var.get().strip() or self._archive_name
        remote = f"{self._current_path}/{archive_name}".lstrip("/")
        self._set_status(f"Uploading {archive_name}…", _ORANGE)
        self._upload_btn.state(["disabled"])

        def _do() -> None:
            try:
                self._client.upload_file(archive_path, remote)
                self.upload_successful = True
                self.after(0, lambda: self._set_status(f"Uploaded ✓  →  /{remote}", _GREEN))
                self.after(0, self._refresh)
            except (NextcloudError, OSError) as exc:
                err = str(exc)
                self.after(0, lambda: self._set_status(f"Upload failed: {err}", _RED))
                self.after(0, lambda: self._upload_btn.state(["!disabled"]))

        threading.Thread(target=_do, daemon=True).start()


# ---------------------------------------------------------------------------
# Public helpers called from app.py
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
    """Open the file browser. Returns True if an upload completed."""
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
