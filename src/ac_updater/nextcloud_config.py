"""Credential persistence for the Nextcloud connection.

Credentials are stored in plain JSON at ~/.ac_updater/nextcloud.json.
This is suitable for a local-only tool; a future phase could swap in
the OS keyring via the keyring package.
"""

import json
from pathlib import Path

_CONFIG_PATH = Path.home() / ".ac_updater" / "nextcloud.json"


def load_credentials() -> tuple[str, str, str] | None:
    """Return (url, username, password) from saved config, or None."""
    if not _CONFIG_PATH.exists():
        return None
    try:
        data: dict[str, str] = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return data.get("url", ""), data.get("username", ""), data.get("password", "")
    except (json.JSONDecodeError, OSError):
        return None


def save_credentials(url: str, username: str, password: str) -> None:
    """Persist credentials to disk."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps({"url": url, "username": username, "password": password}),
        encoding="utf-8",
    )


def clear_credentials() -> None:
    """Remove saved credentials."""
    if _CONFIG_PATH.exists():
        _CONFIG_PATH.unlink()
