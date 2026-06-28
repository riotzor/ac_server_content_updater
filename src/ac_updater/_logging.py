"""Logging configuration for the AC Server Content Updater.

Call setup_logging() once at app startup (in run()).  All other modules
obtain their logger with logging.getLogger(__name__), which places them
under the 'ac_updater' hierarchy automatically:

    ac_updater                  — package root
    ac_updater.archiver         — 7-zip operations
    ac_updater.content_copier   — network-share copy
    ac_updater.nextcloud_client — WebDAV HTTP calls
    ac_updater.nextcloud_config — credential persistence
    ac_updater.share_config     — share-path persistence
    ac_updater.gui.app          — main window user actions
    ac_updater.gui.nextcloud_panel — Nextcloud dialogs

Log file: ~/.ac_updater/logs/ac_updater.log
Rotation: 2 MB max, 3 backups kept.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path.home() / ".ac_updater" / "logs"
_LOG_FILE = _LOG_DIR / "ac_updater.log"
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB per file
_BACKUP_COUNT = 3
_FMT = "%(asctime)s  %(levelname)-8s  %(name)-40s  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Configure rotating file logging for the ac_updater package.

    Safe to call multiple times; subsequent calls are no-ops because the
    root logger already has handlers attached.
    """
    root = logging.getLogger("ac_updater")
    if root.handlers:
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.info("=== AC Server Content Updater started ===")
