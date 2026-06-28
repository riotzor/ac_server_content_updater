from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".ac_updater" / "ssh.json"
_DEFAULT_HOST = "192.168.1.215"
_DEFAULT_USERNAME = "acserver"


def load_ssh_config() -> tuple[str, str]:
    """Return (host, username), falling back to defaults."""
    try:
        data: dict[str, str] = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        host = data.get("host", _DEFAULT_HOST)
        username = data.get("username", _DEFAULT_USERNAME)
        log.debug("SSH config loaded: user=%s  host=%s", username, host)
        return host, username
    except (OSError, json.JSONDecodeError):
        log.debug("No SSH config found, using defaults")
        return _DEFAULT_HOST, _DEFAULT_USERNAME


def save_ssh_config(host: str, username: str) -> None:
    log.info("Saving SSH config: user=%s  host=%s", username, host)
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps({"host": host, "username": username}, indent=2),
        encoding="utf-8",
    )
