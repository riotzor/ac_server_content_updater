from pathlib import Path

import pytest

from ac_updater.ac_finder import find_ac_install


def test_returns_default_path_when_it_exists(tmp_path: Path) -> None:
    ac_dir = tmp_path / "assettocorsa"
    ac_dir.mkdir()

    result = find_ac_install(
        path_exists=lambda p: p == ac_dir,
        default_path=ac_dir,
        _steam_path_reader=lambda: None,
    )

    assert result == ac_dir


def test_falls_back_to_registry_steam_path(tmp_path: Path) -> None:
    ac_dir = tmp_path / "steamapps" / "common" / "assettocorsa"
    ac_dir.mkdir(parents=True)

    result = find_ac_install(
        path_exists=lambda p: p == ac_dir,
        default_path=tmp_path / "nonexistent",
        _steam_path_reader=lambda: str(tmp_path),
    )

    assert result == ac_dir


def test_returns_none_when_ac_missing_from_steam_library(tmp_path: Path) -> None:
    result = find_ac_install(
        path_exists=lambda p: False,
        default_path=tmp_path / "nonexistent",
        _steam_path_reader=lambda: str(tmp_path),
    )

    assert result is None


def test_returns_none_when_registry_unavailable(tmp_path: Path) -> None:
    result = find_ac_install(
        path_exists=lambda p: False,
        default_path=tmp_path / "nonexistent",
        _steam_path_reader=lambda: None,
    )

    assert result is None


def test_default_path_takes_priority_over_registry(tmp_path: Path) -> None:
    default_ac = tmp_path / "default" / "assettocorsa"
    default_ac.mkdir(parents=True)
    registry_ac = tmp_path / "registry" / "steamapps" / "common" / "assettocorsa"
    registry_ac.mkdir(parents=True)

    result = find_ac_install(
        path_exists=lambda p: p in (default_ac, registry_ac),
        default_path=default_ac,
        _steam_path_reader=lambda: str(tmp_path / "registry"),
    )

    assert result == default_ac


@pytest.mark.parametrize("bad_path", ["", "   "])
def test_empty_steam_path_returns_none(tmp_path: Path, bad_path: str) -> None:
    result = find_ac_install(
        path_exists=lambda p: False,
        default_path=tmp_path / "nonexistent",
        _steam_path_reader=lambda: bad_path,
    )

    assert result is None
