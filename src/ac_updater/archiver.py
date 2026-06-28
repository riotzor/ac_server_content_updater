from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

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
            log.debug("7-Zip found at common path: %s", candidate)
            return candidate
    found = shutil.which("7z") or shutil.which("7za")
    if found:
        log.debug("7-Zip found on PATH: %s", found)
        return Path(found)
    log.warning("7-Zip executable not found")
    return None


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
        log.error("Cannot create archive — 7-Zip not found")
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
        log.debug("create_archive called with empty selection — nothing to do")
        return

    content_dir = install_dir / "content"
    log.info(
        "Creating archive: output=%s  items=%d  cwd=%s  exe=%s",
        output_path, len(items), content_dir, exe,
    )
    cmd = [str(exe), "a", "-t7z", str(output_path), *items]
    try:
        subprocess.run(cmd, cwd=content_dir, check=True, capture_output=True)
        log.info("Archive created successfully: %s", output_path)
    except subprocess.CalledProcessError as exc:
        log.error(
            "7-Zip failed (exit %d): stdout=%s  stderr=%s",
            exc.returncode,
            exc.stdout.decode(errors="replace")[:500] if exc.stdout else "",
            exc.stderr.decode(errors="replace")[:500] if exc.stderr else "",
        )
        raise
