"""Credential persistence for the Nextcloud connection.

The Nextcloud password is stored in the OS credential store (Windows Credential
Manager on Windows, Keychain on macOS) via the keyring package.  The URL and
username — not secret — are stored in plain JSON at ~/.ac_updater/nextcloud.json.

If keyring is unavailable the password is not persisted; the user will be asked
to re-enter it on the next launch.

Migration: an existing `password` field in the JSON file (written by an older
version of this tool) is automatically moved into the keyring and removed from
disk on the next successful load.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import keyring
import keyring.errors

log = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".ac_updater" / "nextcloud.json"
_KEYRING_SERVICE = "ac_updater_nextcloud"


def load_credentials() -> tuple[str, str, str] | None:
    """Return (url, username, password), or None if no credentials are saved."""
    if not _CONFIG_PATH.exists():
        log.debug("No credentials file found at %s", _CONFIG_PATH)
        return None
    try:
        data: dict[str, str] = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        url = data.get("url", "").strip()
        username = data.get("username", "").strip()
        if not url or not username:
            log.warning("Credentials file missing url or username — ignoring")
            return None
        password = _load_password(username, data)
        if not password:
            log.warning("No password found for username '%s' in keyring or config", username)
            return None
        log.info("Credentials loaded for user '%s' at %s", username, url)
        return url, username, password
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Failed to read credentials: %s", exc)
        return None


def save_credentials(url: str, username: str, password: str) -> None:
    """Persist credentials. Password goes to the OS keyring; URL+username to JSON."""
    log.info("Saving credentials for user '%s' at %s", username, url)
    try:
        keyring.set_password(_KEYRING_SERVICE, username, password)
        log.debug("Password stored in OS keyring")
    except keyring.errors.KeyringError as exc:
        log.warning("Keyring unavailable — password will not persist across sessions: %s", exc)

    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps({"url": url, "username": username}, indent=2),
        encoding="utf-8",
    )
    log.debug("Config JSON written to %s (no password field)", _CONFIG_PATH)


def clear_credentials() -> None:
    """Remove all saved credentials."""
    log.info("Clearing Nextcloud credentials")
    if _CONFIG_PATH.exists():
        try:
            data: dict[str, str] = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            username = data.get("username", "")
            if username:
                try:
                    keyring.delete_password(_KEYRING_SERVICE, username)
                    log.debug("Keyring entry removed for '%s'", username)
                except keyring.errors.KeyringError as exc:
                    log.warning("Could not remove keyring entry: %s", exc)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read config before clearing: %s", exc)
        _CONFIG_PATH.unlink()
        log.debug("Credentials file deleted: %s", _CONFIG_PATH)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _load_password(username: str, data: dict[str, str]) -> str:
    """Return the password, preferring the keyring over the legacy JSON field."""
    try:
        stored = keyring.get_password(_KEYRING_SERVICE, username)
        if stored:
            log.debug("Password retrieved from OS keyring for '%s'", username)
            return stored
    except keyring.errors.KeyringError as exc:
        log.warning("Keyring unavailable when loading password: %s", exc)

    legacy = data.get("password", "")
    if legacy:
        log.info("Migrating legacy plaintext password for '%s' to OS keyring", username)
        _migrate_to_keyring(username, legacy)
    return legacy


def _migrate_to_keyring(username: str, password: str) -> None:
    """Move a legacy plaintext password from JSON into the OS keyring."""
    try:
        keyring.set_password(_KEYRING_SERVICE, username, password)
        data: dict[str, str] = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        data.pop("password", None)
        _CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.info("Migration to keyring successful — password removed from JSON")
    except (keyring.errors.KeyringError, OSError) as exc:
        log.warning("Migration to keyring failed — leaving legacy JSON intact: %s", exc)
