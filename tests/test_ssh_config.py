from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ac_updater.ssh_config import load_ssh_config, save_ssh_config


def test_load_returns_defaults_when_no_file() -> None:
    with patch("ac_updater.ssh_config._CONFIG_PATH", Path("/nonexistent/path/ssh.json")):
        host, user, key_path = load_ssh_config()
    assert host == "192.168.1.215"
    assert user == "acserver"
    assert key_path == ""


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "ssh.json"
    with patch("ac_updater.ssh_config._CONFIG_PATH", config_path):
        save_ssh_config("10.0.0.1", "admin")
        host, user, key_path = load_ssh_config()
    assert host == "10.0.0.1"
    assert user == "admin"
    assert key_path == ""


def test_save_and_load_round_trip_with_key_path(tmp_path: Path) -> None:
    config_path = tmp_path / "ssh.json"
    with patch("ac_updater.ssh_config._CONFIG_PATH", config_path):
        save_ssh_config("10.0.0.1", "admin", "/home/user/.ssh/id_ed25519")
        host, user, key_path = load_ssh_config()
    assert host == "10.0.0.1"
    assert user == "admin"
    assert key_path == "/home/user/.ssh/id_ed25519"


def test_load_falls_back_to_defaults_on_corrupt_json(tmp_path: Path) -> None:
    config_path = tmp_path / "ssh.json"
    config_path.write_text("not json", encoding="utf-8")
    with patch("ac_updater.ssh_config._CONFIG_PATH", config_path):
        host, user, key_path = load_ssh_config()
    assert host == "192.168.1.215"
    assert user == "acserver"
    assert key_path == ""


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "dir" / "ssh.json"
    with patch("ac_updater.ssh_config._CONFIG_PATH", config_path):
        save_ssh_config("host", "user")
    assert config_path.exists()
