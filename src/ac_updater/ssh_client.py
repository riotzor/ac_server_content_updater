from __future__ import annotations

import logging
import shlex
import stat as stat_module
from collections.abc import Callable
from dataclasses import dataclass, field

import paramiko

log = logging.getLogger(__name__)

_ProgressCallback = Callable[[int, int], None]

_SHARE_PATH = "/mnt/ac-share"
_AC_HOME = "/home/acserver"


@dataclass
class DeployResult:
    deployed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


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

    def connect(self, password: str | None = None) -> None:
        """Connect to the remote host.

        With no password, tries SSH agent and ~/.ssh key files.
        With a password, uses only password auth (no key lookup).
        Raises paramiko.AuthenticationException on auth failure.
        Raises socket.timeout / OSError on network failure.
        """
        log.info("SSH connect: user=%s  host=%s", self._username, self._host)
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
            dst_parent = f"{home}/{server_name}/content/{category}"
            try:
                if not self._path_exists(src):
                    log.debug("Skipped (not on share): %s/%s", category, name)
                    result.skipped += 1
                else:
                    self._exec(
                        f"mkdir -p {shlex.quote(dst_parent)} && "
                        f"cp -r {shlex.quote(src)} {shlex.quote(dst_parent)}/"
                    )
                    log.info("Deployed %s/%s → %s", category, name, server_name)
                    result.deployed += 1
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
