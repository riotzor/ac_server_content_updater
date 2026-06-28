from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path.home() / ".ac_updater" / "install.json"


def load_install_dir() -> Path | None:
    """Return the saved AC install directory, or None if not set or no longer exists."""
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        path = Path(data["install_dir"])
        return path if path.exists() else None
    except (OSError, KeyError, json.JSONDecodeError):
        return None


def save_install_dir(path: Path) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps({"install_dir": str(path)}, indent=2),
        encoding="utf-8",
    )
