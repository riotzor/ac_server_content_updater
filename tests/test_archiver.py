import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ac_updater.archiver import create_archive, find_7zip

# ---------------------------------------------------------------------------
# find_7zip
# ---------------------------------------------------------------------------


def test_find_7zip_returns_none_when_no_common_path_and_not_on_path() -> None:
    with patch("ac_updater.archiver.shutil.which", return_value=None):
        result = find_7zip(_is_file=lambda _: False)
    assert result is None


def test_find_7zip_finds_common_install_path(tmp_path: Path) -> None:
    fake_exe = tmp_path / "7z.exe"
    fake_exe.touch()

    with patch(
        "ac_updater.archiver._SEVENZIP_COMMON_PATHS", (fake_exe,)
    ):
        result = find_7zip()

    assert result == fake_exe


def test_find_7zip_falls_back_to_path_when_no_common_path(tmp_path: Path) -> None:
    fake_exe = str(tmp_path / "7z.exe")
    with patch("ac_updater.archiver.shutil.which", return_value=fake_exe):
        result = find_7zip(_is_file=lambda _: False)
    assert result == Path(fake_exe)


def test_find_7zip_prefers_common_path_over_path_env(tmp_path: Path) -> None:
    fake_common = tmp_path / "common" / "7z.exe"
    fake_common.parent.mkdir()
    fake_common.touch()
    fake_path = str(tmp_path / "path" / "7z.exe")

    with (
        patch("ac_updater.archiver._SEVENZIP_COMMON_PATHS", (fake_common,)),
        patch("ac_updater.archiver.shutil.which", return_value=fake_path),
    ):
        result = find_7zip()

    assert result == fake_common


# ---------------------------------------------------------------------------
# create_archive
# ---------------------------------------------------------------------------


def test_create_archive_raises_when_7zip_not_found(tmp_path: Path) -> None:
    with patch("ac_updater.archiver.find_7zip", return_value=None):
        with pytest.raises(FileNotFoundError, match="7-Zip"):
            create_archive(
                tmp_path,
                {"cars": ["some_car"]},
                tmp_path / "out.7z",
            )


def test_create_archive_does_nothing_for_empty_selection(tmp_path: Path) -> None:
    fake_exe = tmp_path / "7z.exe"
    with patch("ac_updater.archiver.subprocess.run") as mock_run:
        create_archive(
            tmp_path, {"cars": [], "tracks": []}, tmp_path / "out.7z", sevenzip_exe=fake_exe
        )
    mock_run.assert_not_called()


def test_create_archive_calls_7zip_with_correct_command(tmp_path: Path) -> None:
    fake_exe = tmp_path / "7z.exe"
    output = tmp_path / "archive.7z"

    with patch("ac_updater.archiver.subprocess.run") as mock_run:
        create_archive(
            tmp_path,
            {"cars": ["ferrari_458"], "tracks": ["monza"]},
            output,
            sevenzip_exe=fake_exe,
        )

    mock_run.assert_called_once()
    cmd: list[str] = mock_run.call_args[0][0]
    assert cmd[0] == str(fake_exe)
    assert cmd[1] == "a"
    assert cmd[2] == "-t7z"
    assert cmd[3] == str(output)
    assert any("ferrari_458" in arg for arg in cmd)
    assert any("monza" in arg for arg in cmd)


def test_create_archive_runs_from_content_dir(tmp_path: Path) -> None:
    fake_exe = tmp_path / "7z.exe"

    with patch("ac_updater.archiver.subprocess.run") as mock_run:
        create_archive(
            tmp_path,
            {"cars": ["some_car"]},
            tmp_path / "out.7z",
            sevenzip_exe=fake_exe,
        )

    assert mock_run.call_args[1]["cwd"] == tmp_path / "content"


def test_create_archive_passes_check_true(tmp_path: Path) -> None:
    fake_exe = tmp_path / "7z.exe"

    with patch("ac_updater.archiver.subprocess.run") as mock_run:
        create_archive(
            tmp_path,
            {"cars": ["some_car"]},
            tmp_path / "out.7z",
            sevenzip_exe=fake_exe,
        )

    assert mock_run.call_args[1]["check"] is True


def test_create_archive_propagates_subprocess_error(tmp_path: Path) -> None:
    fake_exe = tmp_path / "7z.exe"
    with patch(
        "ac_updater.archiver.subprocess.run",
        side_effect=subprocess.CalledProcessError(2, "7z"),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            create_archive(
                tmp_path,
                {"cars": ["some_car"]},
                tmp_path / "out.7z",
                sevenzip_exe=fake_exe,
            )
