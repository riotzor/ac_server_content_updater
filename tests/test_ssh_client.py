from __future__ import annotations

import stat
from unittest.mock import MagicMock, patch

import paramiko

from ac_updater.ssh_client import SshClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_ssh() -> MagicMock:
    ssh = MagicMock(spec=paramiko.SSHClient)
    sftp = MagicMock()
    ssh.open_sftp.return_value = sftp
    return ssh


def _make_channel(exit_code: int = 0) -> MagicMock:
    ch = MagicMock()
    ch.recv_exit_status.return_value = exit_code
    return ch


def _make_stdout(text: str = "", exit_code: int = 0) -> MagicMock:
    m = MagicMock()
    m.channel = _make_channel(exit_code)
    m.read.return_value = text.encode()
    return m


def _make_stderr(text: str = "") -> MagicMock:
    m = MagicMock()
    m.read.return_value = text.encode()
    return m


def _dir_stat() -> MagicMock:
    m = MagicMock()
    m.st_mode = stat.S_IFDIR | 0o755
    return m


def _file_stat() -> MagicMock:
    m = MagicMock()
    m.st_mode = stat.S_IFREG | 0o644
    return m


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


def test_connect_calls_paramiko_with_host_and_user() -> None:
    mock_ssh = _make_mock_ssh()
    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("192.168.1.215", "acserver")
        client.connect()
    mock_ssh.connect.assert_called_once_with(
        "192.168.1.215", username="acserver", timeout=10
    )


def test_connect_with_password_disables_key_lookup() -> None:
    mock_ssh = _make_mock_ssh()
    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("host", "user")
        client.connect(password="secret")
    mock_ssh.connect.assert_called_once_with(
        "host",
        username="user",
        timeout=10,
        password="secret",
        allow_agent=False,
        look_for_keys=False,
    )


def test_connect_with_key_path_uses_key_filename() -> None:
    mock_ssh = _make_mock_ssh()
    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("host", "user")
        client.connect(key_path="/home/user/.ssh/id_ed25519")
    mock_ssh.connect.assert_called_once_with(
        "host",
        username="user",
        timeout=10,
        key_filename="/home/user/.ssh/id_ed25519",
        look_for_keys=False,
    )


def test_connect_with_key_path_does_not_set_password() -> None:
    mock_ssh = _make_mock_ssh()
    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("host", "user")
        client.connect(key_path="/path/to/key")
    call_kwargs = mock_ssh.connect.call_args[1]
    assert "password" not in call_kwargs
    assert call_kwargs["look_for_keys"] is False


def test_connect_opens_sftp() -> None:
    mock_ssh = _make_mock_ssh()
    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("host", "user")
        client.connect()
    mock_ssh.open_sftp.assert_called_once()
    assert client.is_connected is True


def test_disconnect_closes_ssh_and_sftp() -> None:
    mock_ssh = _make_mock_ssh()
    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("host", "user")
        client.connect()
        client.disconnect()
    mock_ssh.open_sftp.return_value.close.assert_called_once()
    mock_ssh.close.assert_called_once()
    assert client.is_connected is False


def test_is_connected_false_before_connect() -> None:
    assert SshClient("h", "u").is_connected is False


# ---------------------------------------------------------------------------
# list_share_content
# ---------------------------------------------------------------------------


def test_list_share_content_returns_dirs_only() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value

    def _stat(path: str) -> MagicMock:
        return _file_stat() if path.endswith(".txt") else _dir_stat()

    sftp.listdir.return_value = ["ferrari_458", "readme.txt", "bmw_m3"]
    sftp.stat.side_effect = _stat

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    result = client.list_share_content()

    assert result["cars"] == ["bmw_m3", "ferrari_458"]


def test_list_share_content_returns_empty_on_oserror() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.side_effect = OSError("not found")

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    result = client.list_share_content()

    assert result == {"cars": [], "tracks": []}


def test_list_share_content_returns_sorted() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.return_value = ["zonda", "alfa", "bmw"]
    sftp.stat.return_value = _dir_stat()

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    result = client.list_share_content()

    assert result["cars"] == ["alfa", "bmw", "zonda"]


# ---------------------------------------------------------------------------
# list_ac_servers
# ---------------------------------------------------------------------------


def test_list_ac_servers_filters_ac_prefix_dirs() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.return_value = ["ac-drift", "ac-srp", "logs", "config"]

    def _stat(path: str) -> MagicMock:
        return _dir_stat()  # everything a directory

    sftp.stat.side_effect = _stat

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    servers = client.list_ac_servers()

    assert servers == ["ac-drift", "ac-srp"]
    assert "logs" not in servers
    assert "config" not in servers


def test_list_ac_servers_returns_empty_on_oserror() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.side_effect = OSError("permission denied")

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.list_ac_servers() == []


def test_list_ac_servers_excludes_non_dirs() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.return_value = ["ac-drift", "ac-readme.txt"]

    def _stat(path: str) -> MagicMock:
        return _file_stat() if path.endswith(".txt") else _dir_stat()

    sftp.stat.side_effect = _stat

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.list_ac_servers() == ["ac-drift"]


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------


def _exec_for_deploy(path_exists: bool = True) -> MagicMock:
    """Return an exec_command side_effect that simulates successful copy."""
    def _exec(cmd: str):  # type: ignore[return]
        if "[ -d" in cmd:
            # Source existence check
            ch = _make_channel(0 if path_exists else 1)
            stdout = MagicMock()
            stdout.channel = ch
            return MagicMock(), stdout, MagicMock()
        # mkdir + cp command
        stdout = _make_stdout("", 0)
        return MagicMock(), stdout, _make_stderr()
    return _exec


def test_deploy_runs_cp_for_each_item() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.side_effect = _exec_for_deploy(True)

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    result = client.deploy("ac-drift", {"cars": ["ferrari_458", "bmw_m3"]})

    assert result.deployed == 2
    assert result.skipped == 0
    assert result.errors == []


def test_deploy_counts_skipped_when_source_missing() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.side_effect = _exec_for_deploy(False)

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    result = client.deploy("ac-drift", {"cars": ["missing_car"]})

    assert result.skipped == 1
    assert result.deployed == 0


def test_deploy_records_error_on_exec_failure() -> None:
    mock_ssh = _make_mock_ssh()

    def _exec(cmd: str):  # type: ignore[return]
        if "[ -d" in cmd:
            ch = _make_channel(0)
            stdout = MagicMock()
            stdout.channel = ch
            return MagicMock(), stdout, MagicMock()
        # cp fails
        stdout = _make_stdout("", 1)
        return MagicMock(), stdout, _make_stderr("permission denied")

    mock_ssh.exec_command.side_effect = _exec

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    result = client.deploy("ac-drift", {"cars": ["car_a"]})

    assert result.deployed == 0
    assert len(result.errors) == 1
    assert "cars/car_a" in result.errors[0]


def test_deploy_calls_on_progress_for_each_item() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.side_effect = _exec_for_deploy(True)

    calls: list[tuple[int, int]] = []

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.deploy(
        "ac-drift",
        {"cars": ["a", "b", "c"]},
        on_progress=lambda d, t: calls.append((d, t)),
    )

    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_deploy_empty_selection_returns_zero_counts() -> None:
    mock_ssh = _make_mock_ssh()

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    result = client.deploy("ac-drift", {"cars": [], "tracks": []})

    assert result.deployed == 0
    assert result.skipped == 0
    mock_ssh.exec_command.assert_not_called()


def test_deploy_tracks_deployed_items() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.side_effect = _exec_for_deploy(True)

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    result = client.deploy("ac-drift", {"cars": ["ferrari", "bmw"], "tracks": ["monza"]})

    assert ("cars", "ferrari") in result.deployed_items
    assert ("cars", "bmw") in result.deployed_items
    assert ("tracks", "monza") in result.deployed_items
    assert len(result.deployed_items) == 3


def test_deploy_includes_chown_and_chmod() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.side_effect = _exec_for_deploy(True)

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.deploy("ac-drift", {"cars": ["ferrari_458"]})

    cp_cmds = [
        c[0][0] for c in mock_ssh.exec_command.call_args_list if "cp -r" in c[0][0]
    ]
    assert len(cp_cmds) == 1
    assert "chown" in cp_cmds[0]
    assert "chmod" in cp_cmds[0]
    assert "775" in cp_cmds[0]


def test_deploy_skipped_item_not_in_deployed_items() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.side_effect = _exec_for_deploy(False)

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    result = client.deploy("ac-drift", {"cars": ["missing_car"]})

    assert result.deployed_items == []
    assert result.skipped == 1


# ---------------------------------------------------------------------------
# stop_service
# ---------------------------------------------------------------------------


def test_stop_service_calls_systemctl_stop() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.stop_service("ac-drift.service")

    cmd: str = mock_ssh.exec_command.call_args[0][0]
    assert "systemctl stop" in cmd
    assert "ac-drift.service" in cmd


def test_stop_service_raises_on_failure() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (
        MagicMock(), _make_stdout("", 1), _make_stderr("Failed to stop")
    )

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()

    import pytest
    with pytest.raises(RuntimeError, match="Failed to stop"):
        client.stop_service("ac-drift.service")


# ---------------------------------------------------------------------------
# update_entry_list
# ---------------------------------------------------------------------------


def _sftp_file(content: bytes = b"") -> MagicMock:
    fh = MagicMock()
    fh.__enter__ = lambda s: s
    fh.__exit__ = MagicMock(return_value=False)
    fh.read.return_value = content
    fh.write = MagicMock()
    return fh


def test_update_entry_list_appends_from_next_index() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value

    existing = b"[CAR_0]\nMODEL=old_car\nSKIN=\nSPECTATOR_MODE=0\n"
    read_fh = _sftp_file(existing)
    write_fh = _sftp_file()
    sftp.open.side_effect = [read_fh, write_fh]

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.update_entry_list("/home/acserver/ac-drift", [("ferrari_458", "red_skin")])

    written: str = write_fh.write.call_args[0][0].decode("utf-8")
    assert "[CAR_1]" in written
    assert "MODEL=ferrari_458" in written
    assert "SKIN=red_skin" in written


def test_update_entry_list_starts_at_zero_for_empty_file() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value

    read_fh = MagicMock()
    read_fh.__enter__ = lambda s: s
    read_fh.__exit__ = MagicMock(return_value=False)
    read_fh.read.side_effect = OSError("not found")

    write_fh = _sftp_file()
    sftp.open.side_effect = [OSError("not found"), write_fh]

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.update_entry_list("/home/acserver/ac-drift", [("ferrari_458", "")])

    written: str = write_fh.write.call_args[0][0].decode("utf-8")
    assert "[CAR_0]" in written
    assert "MODEL=ferrari_458" in written


def test_update_entry_list_continues_from_highest_car_index() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value

    existing = (
        b"[CAR_0]\nMODEL=car_a\n"
        b"[CAR_3]\nMODEL=car_d\n"
        b"[CAR_1]\nMODEL=car_b\n"
    )
    read_fh = _sftp_file(existing)
    write_fh = _sftp_file()
    sftp.open.side_effect = [read_fh, write_fh]

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.update_entry_list("/home/acserver/ac-drift", [("new_car", "default")])

    written: str = write_fh.write.call_args[0][0].decode("utf-8")
    assert "[CAR_4]" in written
