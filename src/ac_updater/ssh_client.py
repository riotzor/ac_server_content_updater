from __future__ import annotations

import logging
import re
import shlex
import stat as stat_module
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import paramiko

log = logging.getLogger(__name__)

_ProgressCallback = Callable[[int, int], None]

_SHARE_PATH = "/mnt/ac-share"
_AC_HOME = "/home/acserver"

_DEFAULT_CAR_FIELDS: dict[str, str] = {
    "SKIN": "",
    "SPECTATOR_MODE": "0",
    "DRIVERNAME": "",
    "TEAM": "",
    "GUID": "",
    "BALLAST": "0",
    "RESTRICTOR": "0",
}


def _parse_entry_list(text: str) -> dict[str, dict[str, str]]:
    """Parse entry_list.ini text into ``{model: {field: value}}``.

    The MODEL key is used as the dict key and is NOT included in the inner dict.
    When a model appears multiple times (multiple slots), the first occurrence wins.
    Returns an empty dict for an empty or unparseable file.
    """
    result: dict[str, dict[str, str]] = {}
    sections: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[CAR_"):
            current = {}
            sections.append(current)
        elif current is not None and "=" in line:
            key, _, val = line.partition("=")
            current[key.strip().upper()] = val.strip()
    for section in sections:
        model = section.pop("MODEL", None)
        if model and model not in result:
            result[model] = section
    return result


def merge_entry_list(
    all_car_names: list[str],
    existing: dict[str, dict[str, str]],
    default_skin: Callable[[str], str] | None = None,
) -> list[dict[str, str]]:
    """Build ordered car entries, preserving settings for cars already in the file.

    For each name in all_car_names:
      - If the model exists in ``existing``, its fields are carried over unchanged.
      - If it is new, default fields are used, with SKIN from ``default_skin`` if given.

    Returns a list of per-car dicts each containing MODEL plus all other fields,
    in all_car_names order.  Sequential [CAR_N] numbering is applied by
    write_entry_list.
    """
    entries: list[dict[str, str]] = []
    for car_name in all_car_names:
        if car_name in existing:
            fields = dict(existing[car_name])
        else:
            fields = dict(_DEFAULT_CAR_FIELDS)
            if default_skin is not None:
                fields["SKIN"] = default_skin(car_name)
        entries.append({"MODEL": car_name, **fields})
    return entries


@dataclass
class DeployResult:
    deployed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    deployed_items: list[tuple[str, str]] = field(default_factory=list)  # (category, name)


class SshClient:
    """SSH client for browsing the AC share and deploying content to AC servers.

    connect() tries key-based auth (SSH agent + ~/.ssh keys) unless a password is
    supplied, in which case only password auth is attempted.
    """

    def __init__(self, host: str, username: str) -> None:
        self._host = host
        self._username = username
        self._ssh: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    @property
    def is_connected(self) -> bool:
        return self._ssh is not None

    def connect(
        self,
        password: str | None = None,
        key_path: str | None = None,
        passphrase: str | None = None,
    ) -> None:
        """Connect to the remote host.

        key_path: explicit path to a private key file; disables ~/.ssh/ fallback.
        passphrase: decryption passphrase for key_path (ignored when password is set).
        password: use password auth only (disables key lookup).
        No args: tries SSH agent and all ~/.ssh/id_* key files.
        Raises paramiko.AuthenticationException on auth failure.
        Raises paramiko.PasswordRequiredException if the key file needs a passphrase.
        Raises socket.timeout / OSError on network failure.
        """
        log.info(
            "SSH connect: user=%s  host=%s  key=%s",
            self._username, self._host, key_path or "(default)",
        )
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict[str, object] = {
            "username": self._username,
            "timeout": 10,
        }
        if password is not None:
            kwargs["password"] = password
            kwargs["allow_agent"] = False
            kwargs["look_for_keys"] = False
        elif key_path:
            kwargs["key_filename"] = key_path
            kwargs["look_for_keys"] = False
            if passphrase is not None:
                kwargs["passphrase"] = passphrase
        ssh.connect(self._host, **kwargs)
        self._ssh = ssh
        self._sftp = ssh.open_sftp()
        log.info("SSH connected to %s@%s", self._username, self._host)

    def disconnect(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._ssh is not None:
            self._ssh.close()
            self._ssh = None
        log.info("SSH disconnected from %s", self._host)

    def list_share_content(self, share_path: str = _SHARE_PATH) -> dict[str, list[str]]:
        """Return sorted dir names under share_path/content/{cars,tracks}, dirs only."""
        assert self._sftp is not None, "Not connected"
        result: dict[str, list[str]] = {}
        for category in ("cars", "tracks"):
            base = f"{share_path}/content/{category}"
            try:
                names = self._sftp.listdir(base)
            except OSError:
                result[category] = []
                continue
            dirs: list[str] = []
            for name in names:
                try:
                    st = self._sftp.stat(f"{base}/{name}")
                    if stat_module.S_ISDIR(st.st_mode):
                        dirs.append(name)
                except OSError:
                    pass
            result[category] = sorted(dirs)
            log.debug("Share %s: %d item(s)", category, len(dirs))
        return result

    def list_ac_servers(self, home: str = _AC_HOME) -> list[str]:
        """Return sorted names of directories under home that begin with 'ac'."""
        assert self._sftp is not None, "Not connected"
        try:
            names = self._sftp.listdir(home)
        except OSError:
            return []
        servers: list[str] = []
        for name in names:
            if not name.startswith("ac"):
                continue
            try:
                st = self._sftp.stat(f"{home}/{name}")
                if stat_module.S_ISDIR(st.st_mode):
                    servers.append(name)
            except OSError:
                pass
        result = sorted(servers)
        log.info("Found %d AC server(s): %s", len(result), result)
        return result

    def deploy(
        self,
        server_name: str,
        selection: dict[str, list[str]],
        on_progress: _ProgressCallback | None = None,
        share_path: str = _SHARE_PATH,
        home: str = _AC_HOME,
    ) -> DeployResult:
        """Copy selected content from the share into the target server directory.

        For each (category, name) pair, copies
          share_path/content/<category>/<name>/
        into
          home/<server_name>/content/<category>/

        Items absent from the share are counted as skipped, not errors.
        on_progress(done, total) is called after each item.
        """
        assert self._ssh is not None, "Not connected"
        result = DeployResult()
        items = [
            (cat, name)
            for cat, names in selection.items()
            for name in names
        ]
        total = len(items)
        log.info("Deploy: server=%s  items=%d", server_name, total)

        for i, (category, name) in enumerate(items):
            src = f"{share_path}/content/{category}/{name}"
            # Tracks are stored under content/tracks/csp/ on the AC server
            dst_parent = (
                f"{home}/{server_name}/content/tracks/csp"
                if category == "tracks"
                else f"{home}/{server_name}/content/{category}"
            )
            try:
                if not self._path_exists(src):
                    log.debug("Skipped (not on share): %s/%s", category, name)
                    result.skipped += 1
                else:
                    dst = f"{dst_parent}/{name}"
                    owner = f"{self._username}:{self._username}"
                    self._exec(
                        f"mkdir -p {shlex.quote(dst_parent)} && "
                        f"cp -r {shlex.quote(src)} {shlex.quote(dst_parent)}/ && "
                        f"chown -R {shlex.quote(owner)} {shlex.quote(dst)} && "
                        f"chmod -R 775 {shlex.quote(dst)}"
                    )
                    log.info("Deployed %s/%s → %s", category, name, server_name)
                    result.deployed += 1
                    result.deployed_items.append((category, name))
            except RuntimeError as exc:
                log.error("Deploy error %s/%s: %s", category, name, exc)
                result.errors.append(f"{category}/{name}: {exc}")
            if on_progress:
                on_progress(i + 1, total)

        log.info(
            "Deploy done: deployed=%d  skipped=%d  errors=%d",
            result.deployed, result.skipped, len(result.errors),
        )
        return result

    def stop_service(self, service_name: str) -> None:
        """Stop a systemd service on the remote host via sudo."""
        log.info("Stopping service: %s", service_name)
        self._exec(f"sudo systemctl stop {shlex.quote(service_name)}")
        log.info("Service stopped: %s", service_name)

    def get_service_status(self, service_name: str) -> str:
        """Return the systemd active state: 'active', 'inactive', 'failed', etc.

        systemctl is-active exits non-zero for inactive/failed states, so
        '|| true' is appended to prevent _exec from raising.
        """
        status = self._exec(
            f"systemctl is-active {shlex.quote(service_name)} || true"
        ).strip()
        return status or "unknown"

    def start_service(self, service_name: str) -> None:
        """Start a systemd service on the remote host via sudo."""
        log.info("Starting service: %s", service_name)
        self._exec(f"sudo systemctl start {shlex.quote(service_name)}")
        log.info("Service started: %s", service_name)

    def restart_service(self, service_name: str) -> None:
        """Restart a systemd service on the remote host via sudo."""
        log.info("Restarting service: %s", service_name)
        self._exec(f"sudo systemctl restart {shlex.quote(service_name)}")
        log.info("Service restarted: %s", service_name)

    def ensure_capacity(self, server_dir: str, car_count: int) -> int | None:
        """Ensure MAX_CLIENTS in server_cfg.ini >= car_count.

        If car_count exceeds the current value, updates it to car_count + 5
        and returns the new value.  Returns None if no update was needed.
        """
        assert self._sftp is not None, "Not connected"
        cfg_path = f"{server_dir}/cfg/server_cfg.ini"
        try:
            with self._sftp.open(cfg_path, "r") as fh:
                content = fh.read().decode("utf-8", errors="replace")
        except OSError as exc:
            log.warning("Could not read server_cfg.ini: %s", exc)
            return None

        match = re.search(r"(?im)^MAX_CLIENTS\s*=\s*(\d+)", content)
        if not match:
            log.warning("MAX_CLIENTS not found in %s", cfg_path)
            return None

        current = int(match.group(1))
        new_value = car_count + 5
        if new_value == current:
            log.debug("MAX_CLIENTS already %d, no change needed", current)
            return None
        new_content = re.sub(
            r"(?im)^(MAX_CLIENTS\s*=\s*)\d+",
            lambda m: m.group(1) + str(new_value),
            content,
            count=1,
        )
        try:
            with self._sftp.open(cfg_path, "w") as fh:
                fh.write(new_content.encode("utf-8"))
            log.info("MAX_CLIENTS updated %d → %d (cars=%d)", current, new_value, car_count)
            return new_value
        except OSError as exc:
            log.warning("Could not write server_cfg.ini: %s", exc)
            return None

    def delete_from_share(
        self,
        category: str,
        names: list[str],
        share_path: str = _SHARE_PATH,
    ) -> None:
        """Remove content directories from the network share via SSH exec."""
        base = f"{share_path}/content/{category}"
        for name in names:
            path = f"{base}/{name}"
            self._exec(f"sudo /usr/local/bin/ac-share-delete {shlex.quote(path)}")
            log.info("Deleted from share: %s/%s", category, name)

    def list_server_cars(self, server_dir: str) -> list[str]:
        """Return sorted car directory names from <server_dir>/content/cars/."""
        assert self._sftp is not None, "Not connected"
        cars_path = f"{server_dir}/content/cars"
        try:
            names = self._sftp.listdir(cars_path)
        except OSError:
            return []
        cars: list[str] = []
        for name in names:
            try:
                st = self._sftp.stat(f"{cars_path}/{name}")
                if stat_module.S_ISDIR(st.st_mode):
                    cars.append(name)
            except OSError:
                pass
        result = sorted(cars)
        log.info("Server cars at %s: %d found", server_dir, len(result))
        return result

    def read_entry_list(self, server_dir: str) -> dict[str, dict[str, str]]:
        """Parse <server_dir>/cfg/entry_list.ini into ``{model: {field: value}}``.

        Returns an empty dict if the file does not exist or cannot be read.
        """
        assert self._sftp is not None, "Not connected"
        path = f"{server_dir}/cfg/entry_list.ini"
        try:
            with self._sftp.open(path, "r") as fh:
                content: str = fh.read().decode("utf-8", errors="replace")
        except OSError:
            log.debug("entry_list.ini not found at %s — starting fresh", path)
            return {}
        return _parse_entry_list(content)

    def write_entry_list(
        self,
        server_dir: str,
        entries: list[dict[str, str]],
    ) -> None:
        """Write <server_dir>/cfg/entry_list.ini from a list of per-car dicts.

        Each dict must contain MODEL plus any other fields (SKIN, SPECTATOR_MODE,
        etc.).  Sections are numbered sequentially from CAR_0; all other field
        values and ordering are preserved exactly as supplied.
        """
        assert self._sftp is not None, "Not connected"
        path = f"{server_dir}/cfg/entry_list.ini"
        log.info("Writing entry_list.ini: %s  cars=%d", path, len(entries))

        sections: list[str] = []
        for n, car in enumerate(entries):
            lines = [f"[CAR_{n}]", f"MODEL={car.get('MODEL', '')}"]
            for key, val in car.items():
                if key != "MODEL":
                    lines.append(f"{key}={val}")
            lines.append("")  # produces a trailing newline when joined
            sections.append("\n".join(lines))

        content = "\n".join(sections).encode("utf-8")
        with self._sftp.open(path, "w") as fh:
            fh.write(content)

        log.info("entry_list.ini written: %d car(s)", len(entries))

    def list_server_tracks(self, server_dir: str) -> list[str]:
        """Return sorted track directory names from <server_dir>/content/tracks/csp/."""
        assert self._sftp is not None, "Not connected"
        tracks_path = f"{server_dir}/content/tracks/csp"
        try:
            names = self._sftp.listdir(tracks_path)
        except OSError:
            return []
        tracks: list[str] = []
        for name in names:
            try:
                st = self._sftp.stat(f"{tracks_path}/{name}")
                if stat_module.S_ISDIR(st.st_mode):
                    tracks.append(name)
            except OSError:
                pass
        result = sorted(tracks)
        log.info("Server tracks at %s: %d found", server_dir, len(result))
        return result

    def list_track_layouts(self, server_dir: str, track_name: str) -> list[str]:
        """Return sorted layout names for a track on the server.

        Layout names are derived from ``models_<layout>.ini`` files in the track
        directory — the same convention used by detect_track_layouts locally.
        Returns an empty list for single-layout tracks or on error.
        """
        assert self._sftp is not None, "Not connected"
        track_path = f"{server_dir}/content/tracks/csp/{track_name}"
        try:
            names = self._sftp.listdir(track_path)
        except OSError:
            return []
        layouts: list[str] = []
        for name in names:
            if name.startswith("models_") and name.endswith(".ini"):
                layout = name[len("models_"):-len(".ini")]
                if layout:
                    layouts.append(layout)
        return sorted(layouts)

    def delete_content(
        self,
        server_dir: str,
        category: str,
        names: list[str],
    ) -> None:
        """Remove content directories from the server.

        category must be "cars" or "tracks".
        Cars live at content/cars/<name>; tracks at content/tracks/csp/<name>.
        """
        base = (
            f"{server_dir}/content/tracks/csp"
            if category == "tracks"
            else f"{server_dir}/content/cars"
        )
        for name in names:
            path = f"{base}/{name}"
            self._exec(f"rm -rf {shlex.quote(path)}")
            log.info("Deleted %s/%s from %s", category, name, server_dir)

    def fix_permissions(
        self,
        server_dir: str,
        category: str,
        names: list[str],
    ) -> None:
        """Set ownership acserver:acserver and mode 775 on content directories.

        category must be "cars" or "tracks".
        """
        base = (
            f"{server_dir}/content/tracks/csp"
            if category == "tracks"
            else f"{server_dir}/content/cars"
        )
        owner = f"{self._username}:{self._username}"
        for name in names:
            path = f"{base}/{name}"
            self._exec(
                f"sudo chown -R {shlex.quote(owner)} {shlex.quote(path)} && "
                f"sudo chmod -R 775 {shlex.quote(path)}"
            )
            log.info("Fixed permissions on %s/%s", category, name)

    def patch_surfaces_ini(self, server_dir: str, track_name: str) -> None:
        """Replace [SURFACE_0] with [CSPFACE_0] on the first occurrence in surfaces.ini.

        The file is read via SFTP, patched in Python, and written back — no
        shell-side escaping required.  A no-op if the file is already patched
        or does not exist.
        """
        assert self._sftp is not None, "Not connected"
        path = f"{server_dir}/content/tracks/csp/{track_name}/data/surfaces.ini"
        try:
            with self._sftp.open(path, "r") as fh:
                content: str = fh.read().decode("utf-8", errors="replace")
        except OSError:
            log.warning("surfaces.ini not found for track %s — skipping patch", track_name)
            return
        new_content = content.replace("[SURFACE_0]", "[CSPFACE_0]", 1)
        if new_content == content:
            log.debug("surfaces.ini already patched for track %s", track_name)
            return
        with self._sftp.open(path, "w") as fh:
            fh.write(new_content.encode("utf-8"))
        log.info("Patched surfaces.ini [SURFACE_0] → [CSPFACE_0] for track %s", track_name)

    def read_active_track(self, server_dir: str) -> str:
        """Return the track name currently set in server_cfg.ini, or empty string."""
        assert self._sftp is not None, "Not connected"
        path = f"{server_dir}/cfg/server_cfg.ini"
        try:
            with self._sftp.open(path, "r") as fh:
                content: str = fh.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        for line in content.splitlines():
            if line.strip().startswith("TRACK="):
                track_val = line.strip()[6:]
                # CSP format: csp/<ver>/../<flags>/../<track_name>
                parts = track_val.split("/../")
                return parts[-1] if len(parts) > 1 else track_val
        return ""

    def write_active_track(
        self,
        server_dir: str,
        track_name: str,
        layout_name: str | None = None,
    ) -> None:
        """Update TRACK= (and optionally CONFIG_TRACK=) in server_cfg.ini.

        Preserves the existing CSP prefix (csp/<ver>/../<flags>/..) if present;
        falls back to csp/2144/../E/ if no TRACK line exists yet.

        layout_name: when provided, updates or inserts CONFIG_TRACK=<layout_name>
          immediately after the TRACK= line.  When None, any existing CONFIG_TRACK
          line is removed (tracks without layouts must not have this key).
        Requires a server restart to take effect.
        """
        assert self._sftp is not None, "Not connected"
        path = f"{server_dir}/cfg/server_cfg.ini"
        log.info(
            "Setting active track: %s → %s  layout=%s",
            server_dir, track_name, layout_name or "none",
        )
        try:
            with self._sftp.open(path, "r") as fh:
                content: str = fh.read().decode("utf-8", errors="replace")
        except OSError:
            content = ""

        def _replace(m: re.Match[str]) -> str:
            existing = m.group(1)
            parts = existing.split("/../")
            if len(parts) > 1:
                return "TRACK=" + "/../".join(parts[:-1]) + "/../" + track_name
            return f"TRACK=csp/2144/../E/../{track_name}"

        new_content, count = re.subn(
            r"^TRACK=(.+)$", _replace, content, flags=re.MULTILINE
        )
        if not count:
            new_content = content.rstrip("\n") + f"\nTRACK=csp/2144/../E/../{track_name}\n"

        if layout_name is not None:
            ct_line = f"CONFIG_TRACK={layout_name}"
            new_content, ct_count = re.subn(
                r"^CONFIG_TRACK=.*$", ct_line, new_content, flags=re.MULTILINE
            )
            if not ct_count:
                # Insert immediately after the TRACK= line
                new_content = re.sub(
                    r"(^TRACK=.+$)",
                    lambda m: m.group(1) + f"\nCONFIG_TRACK={layout_name}",
                    new_content,
                    count=1,
                    flags=re.MULTILINE,
                )
        else:
            # Remove CONFIG_TRACK when the track has no layouts
            new_content = re.sub(r"^CONFIG_TRACK=.*\n?", "", new_content, flags=re.MULTILINE)

        with self._sftp.open(path, "w") as fh:
            fh.write(new_content.encode("utf-8"))
        log.info("Active track set to %s (layout=%s)", track_name, layout_name or "none")

    def create_ai_directory(self, server_dir: str, track_name: str) -> None:
        """Create the ai/ subdirectory inside a track's content folder on the server.

        Sets ownership <username>:<username> and mode 775.  Safe to call if
        the directory already exists (mkdir -p).
        """
        ai_path = f"{server_dir}/content/tracks/csp/{track_name}/ai"
        owner = f"{self._username}:{self._username}"
        self._exec(
            f"mkdir -p {shlex.quote(ai_path)} && "
            f"chown {shlex.quote(owner)} {shlex.quote(ai_path)} && "
            f"chmod 775 {shlex.quote(ai_path)}"
        )
        log.info("Created AI directory: %s", ai_path)

    def upload_ai_spline(self, server_dir: str, track_name: str, local_path: Path) -> None:
        """Upload a local AI spline file to the track's ai/ directory on the server.

        Sets ownership <username>:<username> and mode 664 on the uploaded file.
        """
        assert self._sftp is not None, "Not connected"
        remote_dir = f"{server_dir}/content/tracks/csp/{track_name}/ai"
        remote_path = f"{remote_dir}/{local_path.name}"
        self._sftp.put(str(local_path), remote_path)
        owner = f"{self._username}:{self._username}"
        self._exec(
            f"chown {shlex.quote(owner)} {shlex.quote(remote_path)} && "
            f"chmod 664 {shlex.quote(remote_path)}"
        )
        log.info("Uploaded AI spline: %s → %s", local_path.name, remote_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _exec(self, cmd: str) -> str:
        """Run cmd on the remote host; raise RuntimeError on non-zero exit."""
        assert self._ssh is not None
        log.debug("SSH exec: %s", cmd)
        _, stdout, stderr = self._ssh.exec_command(cmd)
        exit_code: int = stdout.channel.recv_exit_status()
        out: str = stdout.read().decode("utf-8", errors="replace")
        err: str = stderr.read().decode("utf-8", errors="replace")
        if exit_code != 0:
            raise RuntimeError(err.strip() or f"exit code {exit_code}")
        return out

    def _path_exists(self, remote_path: str) -> bool:
        """Return True if the path is a directory on the remote host."""
        assert self._ssh is not None
        _, stdout, _ = self._ssh.exec_command(f"[ -d {shlex.quote(remote_path)} ]")
        exit_code: int = stdout.channel.recv_exit_status()
        return exit_code == 0
