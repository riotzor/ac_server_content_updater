import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ac_updater.ac_finder import find_ac_install
from ac_updater.content_scanner import scan_content
from ac_updater.selection_store import save_selection

_SELECTION_FILE = Path("selections") / "selection.txt"
_WINDOW_TITLE = "AC Server Content Updater"
_WINDOW_SIZE = "960x620"


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
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(win_id, width=e.width),
        )

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

        self._build_header(install_dir)
        self._build_panels(content)
        self._build_footer()

    def _build_header(self, install_dir: Path) -> None:
        header = ttk.Frame(self, padding=(10, 8))
        header.pack(fill="x")
        ttk.Label(header, text="AC Install:", font=("", 9, "bold")).pack(side="left")
        ttk.Label(header, text=str(install_dir)).pack(side="left", padx=(6, 0))

    def _build_panels(self, content: dict[str, list[str]]) -> None:
        panel_area = ttk.Frame(self, padding=(10, 0, 10, 0))
        panel_area.pack(fill="both", expand=True)
        for category, items in content.items():
            panel = _ChecklistPanel(panel_area, title=category.title(), items=items)
            panel.pack(side="left", fill="both", expand=True, padx=(0, 6))
            self._panels[category] = panel

    def _build_footer(self) -> None:
        footer = ttk.Frame(self, padding=(10, 6))
        footer.pack(fill="x", side="bottom")
        ttk.Button(footer, text="Save Selection", command=self._save).pack(side="right")
        self._status_var = tk.StringVar()
        ttk.Label(footer, textvariable=self._status_var, foreground="gray").pack(
            side="left"
        )

    def _save(self) -> None:
        selection = {cat: panel.get_selected() for cat, panel in self._panels.items()}
        try:
            save_selection(_SELECTION_FILE, selection)
            total = sum(len(v) for v in selection.values())
            self._status_var.set(f"Saved {total} items to {_SELECTION_FILE}")
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))


def run() -> None:
    install_dir = find_ac_install()

    if install_dir is None:
        root = tk.Tk()
        root.withdraw()
        chosen = filedialog.askdirectory(
            title="Locate Assetto Corsa install folder",
            mustexist=True,
        )
        root.destroy()
        if not chosen:
            return
        install_dir = Path(chosen)

    content = scan_content(install_dir)
    app = _App(install_dir, content)
    app.mainloop()
