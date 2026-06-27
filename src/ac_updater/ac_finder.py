from collections.abc import Callable
from pathlib import Path

DEFAULT_AC_PATH = Path(r"C:\SteamLibrary\steamapps\common\assettocorsa")


def _default_path_exists(path: Path) -> bool:
    return path.exists()


def _read_steam_path_from_registry() -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        value, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)
        return str(value)
    except OSError:
        return None


def find_ac_install(
    *,
    path_exists: Callable[[Path], bool] = _default_path_exists,
    default_path: Path = DEFAULT_AC_PATH,
    _steam_path_reader: Callable[[], str | None] = _read_steam_path_from_registry,
) -> Path | None:
    """Return the AC installation directory, or None if it cannot be located.

    Detection order:
      1. default_path (C:\\SteamLibrary\\steamapps\\common\\assettocorsa)
      2. Steam install path read from the Windows registry
    Returns None if neither is found; the GUI will then prompt the user.
    """
    if path_exists(default_path):
        return default_path

    steam_path_str = _steam_path_reader()
    if not steam_path_str or not steam_path_str.strip():
        return None

    ac_via_registry = Path(steam_path_str) / "steamapps" / "common" / "assettocorsa"
    if path_exists(ac_via_registry):
        return ac_via_registry

    return None
