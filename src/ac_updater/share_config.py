from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path.home() / ".ac_updater" / "share.json"
DEFAULT_SHARE_PATH = Path(r"\\192.168.1.215\ac-share")


def load_share_path() -> Path:
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return Path(data["share_path"])
    except (OSError, KeyError, json.JSONDecodeError):
        return DEFAULT_SHARE_PATH


def save_share_path(path: Path) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps({"share_path": str(path)}, indent=2),
        encoding="utf-8",
    )
