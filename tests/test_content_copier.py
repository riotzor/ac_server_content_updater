from pathlib import Path
from unittest.mock import MagicMock

from ac_updater.content_copier import copy_to_share


def _make_ac_tree(root: Path) -> Path:
    """Create a minimal AC install tree with the server-relevant files."""
    content = root / "content"
    (content / "cars" / "ferrari_458" / "data.acd").parent.mkdir(parents=True)
    (content / "cars" / "ferrari_458" / "data.acd").write_bytes(b"acd")
    (content / "cars" / "bmw_m3").mkdir(parents=True)
    # bmw_m3 intentionally has no data.acd (simulates missing file)

    track = content / "tracks" / "monza"
    (track / "data").mkdir(parents=True)
    (track / "modes.ini").write_text("modes", encoding="utf-8")
    (track / "data" / "surfaces.ini").write_text("surfaces", encoding="utf-8")

    (content / "tracks" / "spa").mkdir(parents=True)
    # spa has modes.ini but no surfaces.ini
    (content / "tracks" / "spa" / "modes.ini").write_text("modes", encoding="utf-8")

    return root


# ---------------------------------------------------------------------------
# Cars
# ---------------------------------------------------------------------------


def test_copy_car_data_acd(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"

    result = copy_to_share(ac, {"cars": ["ferrari_458"]}, share)

    assert result.copied == 1
    assert result.skipped == 0
    dst = share / "content" / "cars" / "ferrari_458" / "data.acd"
    assert dst.exists()
    assert dst.read_bytes() == b"acd"


def test_copy_car_missing_data_acd_counted_as_skipped(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"

    result = copy_to_share(ac, {"cars": ["bmw_m3"]}, share)

    assert result.copied == 0
    assert result.skipped == 1
    assert result.errors == []


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------


def test_copy_track_copies_modes_ini(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"

    copy_to_share(ac, {"tracks": ["monza"]}, share)

    assert (share / "content" / "tracks" / "monza" / "modes.ini").exists()


def test_copy_track_copies_surfaces_ini(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"

    copy_to_share(ac, {"tracks": ["monza"]}, share)

    assert (share / "content" / "tracks" / "monza" / "data" / "surfaces.ini").exists()


def test_copy_track_skips_missing_surfaces_ini(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"

    result = copy_to_share(ac, {"tracks": ["spa"]}, share)

    assert result.copied == 1  # modes.ini copied
    assert result.skipped == 1  # surfaces.ini missing


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------


def test_copy_creates_destination_directories(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"

    copy_to_share(ac, {"cars": ["ferrari_458"]}, share)

    assert (share / "content" / "cars" / "ferrari_458").is_dir()


# ---------------------------------------------------------------------------
# Empty and multi-item
# ---------------------------------------------------------------------------


def test_empty_selection_returns_zero_copied(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"

    result = copy_to_share(ac, {"cars": [], "tracks": []}, share)

    assert result.copied == 0
    assert result.skipped == 0


def test_multiple_cars_and_tracks(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"

    result = copy_to_share(
        ac,
        {"cars": ["ferrari_458", "bmw_m3"], "tracks": ["monza", "spa"]},
        share,
    )

    # ferrari_458: 1 file; bmw_m3: 0 (skipped); monza: 2 files; spa: 1 copied + 1 skipped
    assert result.copied == 4
    assert result.skipped == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_copy_error_is_recorded_not_raised(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"

    def _bad_copy(src: Path, dst: Path) -> None:
        raise OSError("permission denied")

    result = copy_to_share(ac, {"cars": ["ferrari_458"]}, share, _copy2=_bad_copy)

    assert result.copied == 0
    assert len(result.errors) == 1
    assert "permission denied" in result.errors[0]


def test_injectable_copy_fn_called_with_correct_paths(tmp_path: Path) -> None:
    ac = _make_ac_tree(tmp_path / "ac")
    share = tmp_path / "share"
    mock_copy = MagicMock()

    copy_to_share(ac, {"cars": ["ferrari_458"]}, share, _copy2=mock_copy)

    expected_src = ac / "content" / "cars" / "ferrari_458" / "data.acd"
    expected_dst = share / "content" / "cars" / "ferrari_458" / "data.acd"
    mock_copy.assert_called_once_with(expected_src, expected_dst)
