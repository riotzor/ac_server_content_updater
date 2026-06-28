from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from ac_updater.nextcloud_client import (
    NextcloudClient,
    NextcloudError,
    _parse_propfind,
)

_SERVER = "https://cloud.example.com"
_USER = "testuser"
_PASS = "secret"

_PROPFIND_XML = """\
<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/testuser/</d:href>
    <d:propstat>
      <d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/testuser/AC_Content/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>AC_Content</d:displayname>
        <d:resourcetype><d:collection/></d:resourcetype>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/testuser/archive.7z</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>archive.7z</d:displayname>
        <d:resourcetype/>
        <d:getcontentlength>1024</d:getcontentlength>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""


def _client() -> NextcloudClient:
    return NextcloudClient(_SERVER, _USER, _PASS)


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.text = text
    return m


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


def test_connection_returns_true_on_207() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(207)):
        assert _client().test_connection() is True


def test_connection_returns_false_on_401() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(401)):
        assert _client().test_connection() is False


def test_connection_returns_false_on_network_error() -> None:
    with patch(
        "ac_updater.nextcloud_client.requests.request",
        side_effect=requests.ConnectionError(),
    ):
        assert _client().test_connection() is False


# ---------------------------------------------------------------------------
# list_files / _parse_propfind
# ---------------------------------------------------------------------------


def test_parse_propfind_returns_dirs_before_files() -> None:
    dav_base = f"{_SERVER}/remote.php/dav/files/{_USER}/"
    files = _parse_propfind(_PROPFIND_XML, dav_base)
    assert files[0].is_dir is True
    assert files[0].name == "AC_Content"
    assert files[1].is_dir is False
    assert files[1].name == "archive.7z"
    assert files[1].size_bytes == 1024


def test_parse_propfind_skips_root_entry() -> None:
    dav_base = f"{_SERVER}/remote.php/dav/files/{_USER}/"
    files = _parse_propfind(_PROPFIND_XML, dav_base)
    assert len(files) == 2


def test_list_files_returns_parsed_files() -> None:
    with patch(
        "ac_updater.nextcloud_client.requests.request",
        return_value=_mock_response(207, _PROPFIND_XML),
    ):
        files = _client().list_files()
    assert len(files) == 2
    assert files[0].name == "AC_Content"


def test_list_files_raises_on_404() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(404)):
        with pytest.raises(NextcloudError, match="not found"):
            _client().list_files("missing/")


def test_list_files_raises_on_401() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(401)):
        with pytest.raises(NextcloudError, match="Authentication"):
            _client().list_files()


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------


def test_upload_file_succeeds_on_201(tmp_path: Path) -> None:
    archive = tmp_path / "test.7z"
    archive.write_bytes(b"fake")
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(207)):
        with patch("ac_updater.nextcloud_client.requests.put", return_value=_mock_response(201)):
            _client().upload_file(archive, "AC_Content/test.7z")


def test_upload_file_raises_on_500(tmp_path: Path) -> None:
    archive = tmp_path / "test.7z"
    archive.write_bytes(b"fake")
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(207)):
        with patch(
            "ac_updater.nextcloud_client.requests.put", return_value=_mock_response(500, "err")
        ):
            with pytest.raises(NextcloudError, match="Upload failed"):
                _client().upload_file(archive, "AC_Content/test.7z")


# ---------------------------------------------------------------------------
# create_directory
# ---------------------------------------------------------------------------


def test_create_directory_succeeds_on_201() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(201)):
        _client().create_directory("new_folder")


def test_create_directory_no_error_on_405() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(405)):
        _client().create_directory("existing_folder")


def test_create_directory_raises_on_403() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(403)):
        with pytest.raises(NextcloudError, match="Create directory failed"):
            _client().create_directory("forbidden")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_succeeds_on_204() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(204)):
        _client().delete("old_file.7z")


def test_delete_raises_on_403() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(403)):
        with pytest.raises(NextcloudError, match="Delete failed"):
            _client().delete("protected.7z")


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


def test_rename_succeeds_on_201() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(201)):
        _client().rename("old.7z", "new.7z")


def test_rename_raises_on_409() -> None:
    with patch("ac_updater.nextcloud_client.requests.request", return_value=_mock_response(409)):
        with pytest.raises(NextcloudError, match="Rename failed"):
            _client().rename("a.7z", "b.7z")
