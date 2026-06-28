from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_CAR_FILES: tuple[str, ...] = ("data.acd",)
_TRACK_FILES: tuple[str, ...] = ("modes.ini", "data/surfaces.ini")


@dataclass
class CopyResult:
    copied: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def copy_to_share(
    install_dir: Path,
    selection: dict[str, list[str]],
    share_path: Path,
    *,
    _copy2: Callable[[Path, Path], object] = shutil.copy2,
) -> CopyResult:
    """Copy selected AC content files to a network share.

    Copies only the server-relevant files:
      cars   — <car>/data.acd
      tracks — <track>/modes.ini  and  <track>/data/surfaces.ini

    Files not present in the AC install are counted as skipped (not errors).
    OS-level copy failures are recorded in CopyResult.errors.
    """
    result = CopyResult()
    content_dir = install_dir / "content"
    total_items = sum(len(v) for v in selection.values())
    log.info(
        "Starting server content copy: share=%s  items=%d", share_path, total_items
    )

    for car in selection.get("cars", []):
        for rel in _CAR_FILES:
            _copy_file(
                src=content_dir / "cars" / car / rel,
                dst=share_path / "content" / "cars" / car / rel,
                result=result,
                copy2=_copy2,
            )

    for track in selection.get("tracks", []):
        for rel in _TRACK_FILES:
            _copy_file(
                src=content_dir / "tracks" / track / rel,
                dst=share_path / "content" / "tracks" / track / rel,
                result=result,
                copy2=_copy2,
            )

    log.info(
        "Copy complete: copied=%d  skipped=%d  errors=%d",
        result.copied, result.skipped, len(result.errors),
    )
    for err in result.errors:
        log.error("Copy error: %s", err)
    return result


def _copy_file(
    src: Path,
    dst: Path,
    result: CopyResult,
    copy2: Callable[[Path, Path], object],
) -> None:
    if not src.exists():
        log.debug("Skipped (not found): %s", src)
        result.skipped += 1
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        copy2(src, dst)
        log.debug("Copied: %s  →  %s", src, dst)
        result.copied += 1
    except OSError as exc:
        log.error("Failed to copy %s → %s: %s", src, dst, exc)
        result.errors.append(f"{src.name}: {exc}")
