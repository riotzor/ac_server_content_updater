from pathlib import Path
from unittest.mock import patch

from ac_updater.share_config import DEFAULT_SHARE_PATH, load_share_path, save_share_path


def test_load_returns_default_when_no_config(tmp_path: Path) -> None:
    fake_cfg = tmp_path / "nonexistent.json"
    with patch("ac_updater.share_config._CONFIG_PATH", fake_cfg):
        result = load_share_path()
    assert result == DEFAULT_SHARE_PATH


def test_load_returns_default_on_malformed_json(tmp_path: Path) -> None:
    cfg = tmp_path / "share.json"
    cfg.write_text("not json", encoding="utf-8")
    with patch("ac_updater.share_config._CONFIG_PATH", cfg):
        result = load_share_path()
    assert result == DEFAULT_SHARE_PATH


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cfg = tmp_path / "share.json"
    expected = Path(r"\\myserver\myshare")
    with patch("ac_updater.share_config._CONFIG_PATH", cfg):
        save_share_path(expected)
        result = load_share_path()
    assert result == expected


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    cfg = tmp_path / "deeply" / "nested" / "share.json"
    with patch("ac_updater.share_config._CONFIG_PATH", cfg):
        save_share_path(Path(r"\\server\share"))
    assert cfg.exists()


def test_load_returns_default_when_key_missing(tmp_path: Path) -> None:
    cfg = tmp_path / "share.json"
    cfg.write_text('{"other_key": "value"}', encoding="utf-8")
    with patch("ac_updater.share_config._CONFIG_PATH", cfg):
        result = load_share_path()
    assert result == DEFAULT_SHARE_PATH
