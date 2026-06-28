"""Human-readable display names for AC server directories.

To add a new server, add an entry to _DISPLAY_NAMES:
    "ac-<dirname>": "Display Name",
"""

from __future__ import annotations

_DISPLAY_NAMES: dict[str, str] = {
    "ac-drift": "Nicks Drift Server",
    "ac-srp": "Nicks SRP Server",
}


def get_display_name(server_dir: str) -> str:
    """Return the human-readable name for a server directory, or the dir name if unknown."""
    return _DISPLAY_NAMES.get(server_dir, server_dir)
