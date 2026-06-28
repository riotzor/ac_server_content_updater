from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ac_updater.install_config import load_install_dir, save_install_dir


def test_load_returns_none_when_no_file() -> None:
    with patch("ac_updater.install_config._CONFIG_PATH", Path("/nonexistent/path/install.json")):
        assert load_install_dir() is None


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    install_path = tmp_path / "assettocorsa"
    install_path.mkdir()
    config_path = tmp_path / "install.json"
    with patch("ac_updater.install_config._CONFIG_PATH", config_path):
        save_install_dir(install_path)
        result = load_install_dir()
    assert result == install_path


def test_load_returns_none_when_path_no_longer_exists(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    config_path = tmp_path / "install.json"
    with patch("ac_updater.install_config._CONFIG_PATH", config_path):
        save_install_dir(gone)
        result = load_install_dir()
    assert result is None


def test_load_returns_none_on_corrupt_json(tmp_path: Path) -> None:
    config_path = tmp_path / "install.json"
    config_path.write_text("not json", encoding="utf-8")
    with patch("ac_updater.install_config._CONFIG_PATH", config_path):
        assert load_install_dir() is None


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    install_path = tmp_path / "ac"
    install_path.mkdir()
    config_path = tmp_path / "nested" / "dir" / "install.json"
    with patch("ac_updater.install_config._CONFIG_PATH", config_path):
        save_install_dir(install_path)
    assert config_path.exists()
