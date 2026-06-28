from __future__ import annotations

import logging

import keyring
import keyring.errors

log = logging.getLogger(__name__)

_SERVICE = "ac_updater"


def save_passphrase(key_path: str, passphrase: str) -> None:
    keyring.set_password(_SERVICE, key_path, passphrase)
    log.debug("Passphrase saved for key: %s", key_path)


def load_passphrase(key_path: str) -> str | None:
    try:
        return keyring.get_password(_SERVICE, key_path)
    except keyring.errors.KeyringError as exc:
        log.warning("Could not load passphrase for %s: %s", key_path, exc)
        return None


def delete_passphrase(key_path: str) -> None:
    try:
        keyring.delete_password(_SERVICE, key_path)
        log.debug("Passphrase forgotten for key: %s", key_path)
    except keyring.errors.PasswordDeleteError:
        pass  # already absent — not an error
    except keyring.errors.KeyringError as exc:
        log.warning("Could not delete passphrase for %s: %s", key_path, exc)
