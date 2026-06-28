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


def test_connect_with_key_path_and_passphrase_sets_passphrase_kwarg() -> None:
    mock_ssh = _make_mock_ssh()
    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("host", "user")
        client.connect(key_path="/path/to/key", passphrase="s3cr3t")
    mock_ssh.connect.assert_called_once_with(
        "host",
        username="user",
        timeout=10,
        key_filename="/path/to/key",
        look_for_keys=False,
        passphrase="s3cr3t",
    )


def test_connect_without_passphrase_does_not_set_passphrase_kwarg() -> None:
    mock_ssh = _make_mock_ssh()
    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("host", "user")
        client.connect(key_path="/path/to/key")
    call_kwargs = mock_ssh.connect.call_args[1]
    assert "passphrase" not in call_kwargs


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
    assert "sudo systemctl stop" in cmd
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


def test_start_service_calls_systemctl_start() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.start_service("ac-drift.service")

    cmd: str = mock_ssh.exec_command.call_args[0][0]
    assert "sudo systemctl start" in cmd
    assert "ac-drift.service" in cmd


def test_start_service_raises_on_failure() -> None:
    import pytest

    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (
        MagicMock(), _make_stdout("", 1), _make_stderr("Failed to start")
    )

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()

    with pytest.raises(RuntimeError, match="Failed to start"):
        client.start_service("ac-drift.service")


def test_restart_service_calls_systemctl_restart() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.restart_service("ac-drift.service")

    cmd: str = mock_ssh.exec_command.call_args[0][0]
    assert "sudo systemctl restart" in cmd
    assert "ac-drift.service" in cmd


def test_get_service_status_returns_active() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("active", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.get_service_status("ac-drift.service") == "active"


def test_get_service_status_returns_inactive() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("inactive", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.get_service_status("ac-drift.service") == "inactive"


def test_get_service_status_uses_or_true_to_suppress_exit_code() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("inactive", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.get_service_status("ac-drift.service")

    cmd: str = mock_ssh.exec_command.call_args[0][0]
    assert "|| true" in cmd


def test_restart_service_raises_on_failure() -> None:
    import pytest

    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (
        MagicMock(), _make_stdout("", 1), _make_stderr("Failed to restart")
    )

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()

    with pytest.raises(RuntimeError, match="Failed to restart"):
        client.restart_service("ac-drift.service")


# ---------------------------------------------------------------------------
# list_server_cars
# ---------------------------------------------------------------------------


def test_list_server_cars_returns_sorted_dirs() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.return_value = ["ferrari_458", "bmw_m3", "alfa_romeo"]
    sftp.stat.return_value = _dir_stat()

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    cars = client.list_server_cars("/home/acserver/ac-drift")

    assert cars == ["alfa_romeo", "bmw_m3", "ferrari_458"]
    sftp.listdir.assert_called_once_with("/home/acserver/ac-drift/content/cars")


def test_list_server_cars_excludes_files() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.return_value = ["ferrari_458", "readme.txt"]

    def _stat(path: str) -> MagicMock:
        return _file_stat() if path.endswith(".txt") else _dir_stat()

    sftp.stat.side_effect = _stat

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    cars = client.list_server_cars("/home/acserver/ac-drift")

    assert cars == ["ferrari_458"]


def test_list_server_cars_returns_empty_on_oserror() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.side_effect = OSError("not found")

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.list_server_cars("/home/acserver/ac-drift") == []


# ---------------------------------------------------------------------------
# write_entry_list
# ---------------------------------------------------------------------------


def _sftp_file(content: bytes = b"") -> MagicMock:
    fh = MagicMock()
    fh.__enter__ = lambda s: s
    fh.__exit__ = MagicMock(return_value=False)
    fh.read.return_value = content
    fh.write = MagicMock()
    return fh


def test_write_entry_list_numbers_from_zero() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    write_fh = _sftp_file()
    sftp.open.return_value = write_fh

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.write_entry_list(
        "/home/acserver/ac-drift",
        [("ferrari_458", "red_skin"), ("bmw_m3", "white")],
    )

    written: str = write_fh.write.call_args[0][0].decode("utf-8")
    assert "[CAR_0]" in written
    assert "[CAR_1]" in written
    assert "MODEL=ferrari_458" in written
    assert "SKIN=red_skin" in written
    assert "MODEL=bmw_m3" in written
    assert "SKIN=white" in written


def test_write_entry_list_uses_write_mode() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.open.return_value = _sftp_file()

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.write_entry_list("/home/acserver/ac-drift", [("car_a", "")])

    sftp.open.assert_called_once()
    mode: str = sftp.open.call_args[0][1]
    assert mode == "w"


def test_write_entry_list_empty_cars_writes_empty_file() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    write_fh = _sftp_file()
    sftp.open.return_value = write_fh

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.write_entry_list("/home/acserver/ac-drift", [])

    written: bytes = write_fh.write.call_args[0][0]
    assert written == b""


# ---------------------------------------------------------------------------
# deploy — tracks csp path fix
# ---------------------------------------------------------------------------


def test_deploy_tracks_uses_csp_subdir() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.side_effect = _exec_for_deploy(True)

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.deploy("ac-drift", {"tracks": ["monza_2023"]})

    cp_cmds = [
        c[0][0] for c in mock_ssh.exec_command.call_args_list if "cp -r" in c[0][0]
    ]
    assert len(cp_cmds) == 1
    assert "content/tracks/csp" in cp_cmds[0]


def test_deploy_cars_uses_cars_subdir_not_csp() -> None:
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
    assert "content/cars" in cp_cmds[0]
    assert "content/cars/csp" not in cp_cmds[0]


# ---------------------------------------------------------------------------
# list_server_tracks
# ---------------------------------------------------------------------------


def test_list_server_tracks_returns_sorted_dirs() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.return_value = ["zandvoort", "monza", "brands_hatch"]
    sftp.stat.return_value = _dir_stat()

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    tracks = client.list_server_tracks("/home/acserver/ac-drift")

    assert tracks == ["brands_hatch", "monza", "zandvoort"]
    sftp.listdir.assert_called_once_with("/home/acserver/ac-drift/content/tracks/csp")


def test_list_server_tracks_excludes_files() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.return_value = ["monza", "readme.txt"]

    def _stat(path: str) -> MagicMock:
        return _file_stat() if path.endswith(".txt") else _dir_stat()

    sftp.stat.side_effect = _stat

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.list_server_tracks("/home/acserver/ac-drift") == ["monza"]


def test_list_server_tracks_returns_empty_on_oserror() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.listdir.side_effect = OSError("not found")

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.list_server_tracks("/home/acserver/ac-drift") == []


# ---------------------------------------------------------------------------
# delete_content
# ---------------------------------------------------------------------------


def test_delete_content_cars_runs_rm_rf() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.delete_content("/home/acserver/ac-drift", "cars", ["ferrari_458", "bmw_m3"])

    cmds = [c[0][0] for c in mock_ssh.exec_command.call_args_list]
    assert all("rm -rf" in cmd for cmd in cmds)
    assert any("content/cars/ferrari_458" in cmd for cmd in cmds)
    assert any("content/cars/bmw_m3" in cmd for cmd in cmds)


def test_delete_content_tracks_uses_csp_path() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.delete_content("/home/acserver/ac-drift", "tracks", ["monza"])

    cmd: str = mock_ssh.exec_command.call_args[0][0]
    assert "content/tracks/csp/monza" in cmd


def test_delete_content_raises_on_failure() -> None:
    import pytest

    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (
        MagicMock(), _make_stdout("", 1), _make_stderr("permission denied")
    )

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    with pytest.raises(RuntimeError):
        client.delete_content("/home/acserver/ac-drift", "cars", ["ferrari"])


# ---------------------------------------------------------------------------
# fix_permissions
# ---------------------------------------------------------------------------


def test_fix_permissions_runs_chown_and_chmod() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.fix_permissions("/home/acserver/ac-drift", "cars", ["ferrari_458"])

    cmd: str = mock_ssh.exec_command.call_args[0][0]
    assert "sudo chown -R" in cmd
    assert "sudo chmod -R 775" in cmd
    assert "content/cars/ferrari_458" in cmd


def test_fix_permissions_tracks_uses_csp_path() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.fix_permissions("/home/acserver/ac-drift", "tracks", ["monza"])

    cmd: str = mock_ssh.exec_command.call_args[0][0]
    assert "content/tracks/csp/monza" in cmd


def test_fix_permissions_multiple_items_calls_once_each() -> None:
    mock_ssh = _make_mock_ssh()
    mock_ssh.exec_command.return_value = (MagicMock(), _make_stdout("", 0), _make_stderr())

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.fix_permissions("/home/acserver/ac-drift", "cars", ["car_a", "car_b"])

    assert mock_ssh.exec_command.call_count == 2


# ---------------------------------------------------------------------------
# read_active_track
# ---------------------------------------------------------------------------


def test_read_active_track_returns_name_from_csp_format() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    ini = b"NAME=drift\nTRACK=csp/2144/../E/../monza_2023\nPORT=9600\n"
    sftp.open.return_value = _sftp_file(ini)

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.read_active_track("/home/acserver/ac-drift") == "monza_2023"


def test_read_active_track_returns_empty_when_no_track_line() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    ini = b"NAME=drift\nPORT=9600\n"
    sftp.open.return_value = _sftp_file(ini)

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.read_active_track("/home/acserver/ac-drift") == ""


def test_read_active_track_returns_empty_on_oserror() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.open.side_effect = OSError("not found")

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    assert client.read_active_track("/home/acserver/ac-drift") == ""


# ---------------------------------------------------------------------------
# write_active_track
# ---------------------------------------------------------------------------


def test_write_active_track_preserves_csp_prefix() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    ini = b"NAME=drift\nTRACK=csp/2144/../E/../monza_2023\nPORT=9600\n"
    read_fh = _sftp_file(ini)
    write_fh = _sftp_file()

    call_count = [0]

    def _open(path: str, mode: str) -> MagicMock:
        call_count[0] += 1
        return read_fh if mode == "r" else write_fh

    sftp.open.side_effect = _open

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.write_active_track("/home/acserver/ac-drift", "brands_hatch")

    written: str = write_fh.write.call_args[0][0].decode("utf-8")
    assert "TRACK=csp/2144/../E/../brands_hatch" in written
    assert "monza_2023" not in written


def test_write_active_track_appends_when_no_existing_track_line() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    ini = b"NAME=drift\nPORT=9600\n"
    read_fh = _sftp_file(ini)
    write_fh = _sftp_file()

    def _open(path: str, mode: str) -> MagicMock:
        return read_fh if mode == "r" else write_fh

    sftp.open.side_effect = _open

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.write_active_track("/home/acserver/ac-drift", "monza")

    written: str = write_fh.write.call_args[0][0].decode("utf-8")
    assert "TRACK=csp/2144/../E/../monza" in written
    assert "NAME=drift" in written


def test_write_active_track_uses_write_mode() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    ini = b"TRACK=csp/2144/../E/../old_track\n"
    write_fh = _sftp_file()
    modes: list[str] = []

    def _open(path: str, mode: str) -> MagicMock:
        modes.append(mode)
        return _sftp_file(ini) if mode == "r" else write_fh

    sftp.open.side_effect = _open

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.write_active_track("/home/acserver/ac-drift", "new_track")

    assert "w" in modes


# ---------------------------------------------------------------------------
# patch_surfaces_ini
# ---------------------------------------------------------------------------


def test_patch_surfaces_ini_replaces_surface_0() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    original = b"[SURFACE_0]\nKEY=VALUE\n"
    written: list[bytes] = []
    write_fh = _sftp_file()
    write_fh.write.side_effect = written.append

    def _open(path: str, mode: str) -> MagicMock:
        return _sftp_file(original) if mode == "r" else write_fh

    sftp.open.side_effect = _open

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.patch_surfaces_ini("/home/acserver/ac-drift", "ks_vallelunga")

    assert written and b"[CSPFACE_0]" in written[0]
    assert b"[SURFACE_0]" not in written[0]


def test_patch_surfaces_ini_only_first_occurrence() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    original = b"[SURFACE_0]\n[SURFACE_0]\n"
    written: list[bytes] = []
    write_fh = _sftp_file()
    write_fh.write.side_effect = written.append

    sftp.open.side_effect = lambda path, mode: _sftp_file(original) if mode == "r" else write_fh

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.patch_surfaces_ini("/home/acserver/ac-drift", "ks_vallelunga")

    assert written[0] == b"[CSPFACE_0]\n[SURFACE_0]\n"


def test_patch_surfaces_ini_noop_when_already_patched() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    original = b"[CSPFACE_0]\nKEY=VALUE\n"

    sftp.open.return_value = _sftp_file(original)

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    client.patch_surfaces_ini("/home/acserver/ac-drift", "ks_vallelunga")

    # open should only have been called once (read), not twice (read+write)
    assert sftp.open.call_count == 1


def test_patch_surfaces_ini_noop_when_file_missing() -> None:
    mock_ssh = _make_mock_ssh()
    sftp = mock_ssh.open_sftp.return_value
    sftp.open.side_effect = OSError("no such file")

    with patch("ac_updater.ssh_client.paramiko.SSHClient", return_value=mock_ssh):
        client = SshClient("h", "u")
        client.connect()
    # Should not raise
    client.patch_surfaces_ini("/home/acserver/ac-drift", "missing_track")
