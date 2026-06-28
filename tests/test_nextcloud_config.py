"""Tests for nextcloud_config — credential persistence via OS keyring."""

import json
from pathlib import Path
from unittest.mock import patch

import keyring.errors

from ac_updater.nextcloud_config import (
    clear_credentials,
    load_credentials,
    save_credentials,
)

_SERVICE = "ac_updater_nextcloud"


def _write_json(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# save_credentials
# ---------------------------------------------------------------------------


def test_save_stores_password_in_keyring(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch("ac_updater.nextcloud_config.keyring.set_password") as mock_set:
            save_credentials("https://cloud.example.com", "alice", "s3cr3t")
    mock_set.assert_called_once_with(_SERVICE, "alice", "s3cr3t")


def test_save_json_contains_no_password(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch("ac_updater.nextcloud_config.keyring.set_password"):
            save_credentials("https://cloud.example.com", "alice", "s3cr3t")
    data = json.loads(cfg.read_text())
    assert "password" not in data
    assert data["url"] == "https://cloud.example.com"
    assert data["username"] == "alice"


def test_save_survives_keyring_unavailable(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch(
            "ac_updater.nextcloud_config.keyring.set_password",
            side_effect=keyring.errors.KeyringError(),
        ):
            save_credentials("https://cloud.example.com", "alice", "s3cr3t")
    assert cfg.exists()  # JSON still written; password silently not persisted


# ---------------------------------------------------------------------------
# load_credentials
# ---------------------------------------------------------------------------


def test_load_returns_none_when_no_file(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        assert load_credentials() is None


def test_load_reads_password_from_keyring(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    _write_json(cfg, {"url": "https://cloud.example.com", "username": "alice"})
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch(
            "ac_updater.nextcloud_config.keyring.get_password", return_value="s3cr3t"
        ):
            result = load_credentials()
    assert result == ("https://cloud.example.com", "alice", "s3cr3t")


def test_load_returns_none_when_password_absent_from_keyring(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    _write_json(cfg, {"url": "https://cloud.example.com", "username": "alice"})
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch("ac_updater.nextcloud_config.keyring.get_password", return_value=None):
            result = load_credentials()
    assert result is None


def test_load_returns_none_for_empty_url(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    _write_json(cfg, {"url": "", "username": "alice"})
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        assert load_credentials() is None


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


def test_legacy_password_in_json_is_migrated_to_keyring(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    _write_json(
        cfg,
        {"url": "https://cloud.example.com", "username": "alice", "password": "oldpass"},
    )
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch(
            "ac_updater.nextcloud_config.keyring.get_password", return_value=None
        ):
            with patch(
                "ac_updater.nextcloud_config.keyring.set_password"
            ) as mock_set:
                result = load_credentials()

    assert result == ("https://cloud.example.com", "alice", "oldpass")
    mock_set.assert_called_once_with(_SERVICE, "alice", "oldpass")


def test_legacy_migration_removes_password_from_json(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    _write_json(
        cfg,
        {"url": "https://cloud.example.com", "username": "alice", "password": "oldpass"},
    )
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch("ac_updater.nextcloud_config.keyring.get_password", return_value=None):
            with patch("ac_updater.nextcloud_config.keyring.set_password"):
                load_credentials()

    data = json.loads(cfg.read_text())
    assert "password" not in data


def test_legacy_migration_survives_keyring_failure(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    _write_json(
        cfg,
        {"url": "https://cloud.example.com", "username": "alice", "password": "oldpass"},
    )
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch("ac_updater.nextcloud_config.keyring.get_password", return_value=None):
            with patch(
                "ac_updater.nextcloud_config.keyring.set_password",
                side_effect=keyring.errors.KeyringError(),
            ):
                result = load_credentials()

    # Password still returned from JSON even though migration to keyring failed
    assert result is not None
    assert result[2] == "oldpass"
    # JSON NOT rewritten (migration failed before that step)
    assert "password" in json.loads(cfg.read_text())


# ---------------------------------------------------------------------------
# clear_credentials
# ---------------------------------------------------------------------------


def test_clear_removes_config_file(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    _write_json(cfg, {"url": "https://cloud.example.com", "username": "alice"})
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch("ac_updater.nextcloud_config.keyring.delete_password"):
            clear_credentials()
    assert not cfg.exists()


def test_clear_deletes_keyring_entry(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    _write_json(cfg, {"url": "https://cloud.example.com", "username": "alice"})
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        with patch(
            "ac_updater.nextcloud_config.keyring.delete_password"
        ) as mock_del:
            clear_credentials()
    mock_del.assert_called_once_with(_SERVICE, "alice")


def test_clear_is_safe_when_no_file(tmp_path: Path) -> None:
    cfg = tmp_path / "nextcloud.json"
    with patch("ac_updater.nextcloud_config._CONFIG_PATH", cfg):
        clear_credentials()  # must not raise
