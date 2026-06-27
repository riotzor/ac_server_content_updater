from pathlib import Path

import pytest

from ac_updater.selection_store import load_selection, save_selection


def test_roundtrip_preserves_all_items(tmp_path: Path) -> None:
    selection = {
        "cars": ["ferrari_458_italia", "bmw_m3_e30"],
        "tracks": ["monza", "spa"],
    }
    out = tmp_path / "sel" / "selection.txt"

    save_selection(out, selection)
    result = load_selection(out)

    assert result == selection


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    out = tmp_path / "deeply" / "nested" / "selection.txt"

    save_selection(out, {"cars": ["some_car"]})

    assert out.exists()


def test_load_returns_empty_dict_when_file_missing(tmp_path: Path) -> None:
    result = load_selection(tmp_path / "nonexistent.txt")

    assert result == {}


def test_save_empty_selection(tmp_path: Path) -> None:
    out = tmp_path / "selection.txt"

    save_selection(out, {"cars": [], "tracks": []})
    result = load_selection(out)

    assert result == {"cars": [], "tracks": []}


def test_roundtrip_preserves_category_order(tmp_path: Path) -> None:
    selection = {"tracks": ["spa"], "cars": ["ferrari_458"]}
    out = tmp_path / "selection.txt"

    save_selection(out, selection)
    result = load_selection(out)

    assert list(result.keys()) == ["tracks", "cars"]


def test_roundtrip_preserves_item_order(tmp_path: Path) -> None:
    # Items are stored as-is — scanner sorts them, but the store must not re-sort
    cars = ["zzz_car", "aaa_car", "mmm_car"]
    out = tmp_path / "selection.txt"

    save_selection(out, {"cars": cars})
    result = load_selection(out)

    assert result["cars"] == cars


def test_file_content_is_human_readable(tmp_path: Path) -> None:
    out = tmp_path / "selection.txt"

    save_selection(out, {"cars": ["ferrari_458"], "tracks": ["monza"]})
    raw = out.read_text(encoding="utf-8")

    assert "[cars]" in raw
    assert "[tracks]" in raw
    assert "ferrari_458" in raw
    assert "monza" in raw


@pytest.mark.parametrize(
    "category,items",
    [
        ("cars", ["bdc_streetspec_350z_v4"]),
        ("tracks", ["ks_nordschleife", "monza"]),
    ],
)
def test_single_category_roundtrip(
    tmp_path: Path, category: str, items: list[str]
) -> None:
    out = tmp_path / "selection.txt"

    save_selection(out, {category: items})
    result = load_selection(out)

    assert result[category] == items
