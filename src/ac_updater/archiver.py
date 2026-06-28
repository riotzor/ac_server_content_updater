import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

_SEVENZIP_COMMON_PATHS: tuple[Path, ...] = (
    Path(r"C:\Program Files\7-Zip\7z.exe"),
    Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
)


def find_7zip(
    *,
    _is_file: Callable[[Path], bool] = Path.is_file,
) -> Path | None:
    """Return the path to 7z.exe, or None if 7-Zip is not installed.

    Checks common install locations first, then falls back to PATH.
    """
    for candidate in _SEVENZIP_COMMON_PATHS:
        if _is_file(candidate):
            return candidate
    found = shutil.which("7z") or shutil.which("7za")
    return Path(found) if found else None


def create_archive(
    install_dir: Path,
    selection: dict[str, list[str]],
    output_path: Path,
    *,
    sevenzip_exe: Path | None = None,
) -> None:
    """Compress selected content into a .7z archive.

    The archive preserves the AC content layout (cars/<name>, tracks/<name>)
    so it can be extracted directly into a server's content directory.

    Raises:
        FileNotFoundError: if 7-Zip cannot be located.
        subprocess.CalledProcessError: if 7-Zip exits with a non-zero code.
    """
    exe = sevenzip_exe or find_7zip()
    if exe is None:
        raise FileNotFoundError(
            "7-Zip executable not found. "
            "Install 7-Zip (https://www.7-zip.org/) or pass sevenzip_exe explicitly."
        )

    items = [
        str(Path(category) / name)
        for category, names in selection.items()
        for name in names
    ]
    if not items:
        return

    content_dir = install_dir / "content"
    cmd = [str(exe), "a", "-t7z", str(output_path), *items]
    subprocess.run(cmd, cwd=content_dir, check=True, capture_output=True)
