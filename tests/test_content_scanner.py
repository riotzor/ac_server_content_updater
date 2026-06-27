from pathlib import Path

import pytest

from ac_updater.content_scanner import scan_content


def _make_ac_tree(base: Path, cars: list[str], tracks: list[str]) -> Path:
    """Create a minimal AC install directory tree under base."""
    for car in cars:
        (base / "content" / "cars" / car).mkdir(parents=True)
    for track in tracks:
        (base / "content" / "tracks" / track).mkdir(parents=True)
    return base


def test_returns_car_and_track_names(tmp_path: Path) -> None:
    _make_ac_tree(tmp_path, cars=["ferrari_458", "bmw_m3_e30"], tracks=["monza", "spa"])

    result = scan_content(tmp_path)

    assert result["cars"] == ["bmw_m3_e30", "ferrari_458"]
    assert result["tracks"] == ["monza", "spa"]


def test_results_are_sorted_alphabetically(tmp_path: Path) -> None:
    _make_ac_tree(tmp_path, cars=["zzz_car", "aaa_car", "mmm_car"], tracks=[])

    result = scan_content(tmp_path)

    assert result["cars"] == ["aaa_car", "mmm_car", "zzz_car"]


def test_missing_category_dir_returns_empty_list(tmp_path: Path) -> None:
    # Only cars dir exists — tracks dir absent entirely
    (tmp_path / "content" / "cars" / "some_car").mkdir(parents=True)

    result = scan_content(tmp_path)

    assert result["tracks"] == []
    assert result["cars"] == ["some_car"]


def test_empty_category_dir_returns_empty_list(tmp_path: Path) -> None:
    (tmp_path / "content" / "cars").mkdir(parents=True)
    (tmp_path / "content" / "tracks").mkdir(parents=True)

    result = scan_content(tmp_path)

    assert result["cars"] == []
    assert result["tracks"] == []


def test_files_inside_category_dir_are_ignored(tmp_path: Path) -> None:
    cars_dir = tmp_path / "content" / "cars"
    (cars_dir / "real_car").mkdir(parents=True)
    (cars_dir / "readme.txt").write_text("ignored")

    result = scan_content(tmp_path)

    assert result["cars"] == ["real_car"]


def test_custom_categories_are_respected(tmp_path: Path) -> None:
    (tmp_path / "content" / "skins" / "red_skin").mkdir(parents=True)

    result = scan_content(tmp_path, categories=["skins"])

    assert list(result.keys()) == ["skins"]
    assert result["skins"] == ["red_skin"]


def test_all_default_categories_present_in_result(tmp_path: Path) -> None:
    _make_ac_tree(tmp_path, cars=[], tracks=[])

    result = scan_content(tmp_path)

    assert "cars" in result
    assert "tracks" in result


@pytest.mark.parametrize(
    "car_names",
    [
        ["bdc_streetspec_350z_v4"],
        ["ferrari_458_italia", "bmw_m3_e30_drift", "ks_porsche_911"],
    ],
)
def test_real_world_style_names(tmp_path: Path, car_names: list[str]) -> None:
    _make_ac_tree(tmp_path, cars=car_names, tracks=[])

    result = scan_content(tmp_path)

    assert result["cars"] == sorted(car_names)
