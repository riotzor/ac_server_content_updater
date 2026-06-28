"""WebDAV client for Nextcloud.

Implements the same WebDAV operations as pyNextcloud (PUT, DELETE, MKCOL,
MOVE, PROPFIND via requests + HTTPBasicAuth) with typed return values and
exception-based error handling.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from requests.auth import HTTPBasicAuth

_DAV = "DAV:"
_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB — stays under Cloudflare's body-size limits


@dataclass(frozen=True)
class RemoteFile:
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None


class NextcloudError(Exception):
    pass


class NextcloudClient:
    """Nextcloud WebDAV client.

    server_url  — base URL of the Nextcloud instance (e.g. https://cloud.example.com)
    username    — Nextcloud username
    password    — Nextcloud password or app token
    """

    def __init__(self, server_url: str, username: str, password: str) -> None:
        base = server_url.rstrip("/")
        self._username = username
        self._dav_base = f"{base}/remote.php/dav/files/{username}/"
        self._uploads_base = f"{base}/remote.php/dav/uploads/{username}/"
        self._auth = HTTPBasicAuth(username, password)

    def _url(self, remote_path: str = "") -> str:
        return self._dav_base + remote_path.lstrip("/")

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        """Return True if credentials are valid and the server is reachable."""
        try:
            resp = requests.request(
                "PROPFIND",
                self._dav_base,
                headers={"Depth": "0"},
                auth=self._auth,
                timeout=10,
            )
            return resp.status_code == 207
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_files(self, remote_path: str = "") -> list[RemoteFile]:
        """Return files and folders at remote_path, sorted dirs-first."""
        resp = requests.request(
            "PROPFIND",
            self._url(remote_path),
            headers={"Depth": "1"},
            auth=self._auth,
            timeout=30,
        )
        if resp.status_code == 401:
            raise NextcloudError("Authentication failed — check credentials")
        if resp.status_code == 404:
            raise NextcloudError(f"Path not found: {remote_path!r}")
        if resp.status_code != 207:
            raise NextcloudError(f"List failed ({resp.status_code})")
        return _parse_propfind(resp.text, self._dav_base)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def upload_file(self, local_path: Path, remote_path: str) -> None:
        """Upload local_path to remote_path, creating parent dirs as needed.

        Files larger than _CHUNK_SIZE use Nextcloud's chunked-upload protocol
        so that no single HTTP body exceeds proxy size limits (e.g. Cloudflare).
        """
        parent = "/".join(remote_path.lstrip("/").split("/")[:-1])
        if parent:
            self._ensure_dirs(parent)
        if local_path.stat().st_size > _CHUNK_SIZE:
            self._upload_chunked(local_path, remote_path)
        else:
            self._upload_single(local_path, remote_path)

    def _upload_single(self, local_path: Path, remote_path: str) -> None:
        resp = requests.put(
            self._url(remote_path),
            data=local_path.open("rb"),
            auth=self._auth,
            timeout=600,
        )
        if resp.status_code not in (200, 201, 204):
            raise NextcloudError(f"Upload failed ({resp.status_code}): {resp.text[:300]}")

    def _upload_chunked(self, local_path: Path, remote_path: str) -> None:
        """Nextcloud chunked-upload protocol (dav/uploads).

        1. MKCOL  /remote.php/dav/uploads/{user}/{transfer_id}/
        2. PUT    .../uploads/{user}/{transfer_id}/{byte_offset}  (per chunk)
        3. MOVE   .../uploads/{user}/{transfer_id}/.file
                  Destination: .../files/{user}/{remote_path}
        """
        transfer_id = uuid.uuid4().hex
        upload_dir = f"{self._uploads_base}{transfer_id}/"

        resp = requests.request("MKCOL", upload_dir, auth=self._auth, timeout=30)
        if resp.status_code not in (201, 405):
            raise NextcloudError(f"Could not create upload session ({resp.status_code})")

        file_size = local_path.stat().st_size
        with local_path.open("rb") as fh:
            offset = 0
            while True:
                chunk = fh.read(_CHUNK_SIZE)
                if not chunk:
                    break
                chunk_url = f"{upload_dir}{offset}"
                resp = requests.put(chunk_url, data=chunk, auth=self._auth, timeout=300)
                if resp.status_code not in (200, 201, 204):
                    raise NextcloudError(
                        f"Chunk upload failed at offset {offset} ({resp.status_code})"
                    )
                offset += len(chunk)

        resp = requests.request(
            "MOVE",
            f"{upload_dir}.file",
            headers={
                "Destination": self._url(remote_path),
                "OC-Total-Length": str(file_size),
            },
            auth=self._auth,
            timeout=60,
        )
        if resp.status_code not in (200, 201, 204):
            raise NextcloudError(
                f"Chunked upload assembly failed ({resp.status_code}): {resp.text[:300]}"
            )

    def create_directory(self, remote_path: str) -> None:
        """Create a remote directory (no-op if it already exists)."""
        resp = requests.request(
            "MKCOL",
            self._url(remote_path),
            auth=self._auth,
            timeout=15,
        )
        if resp.status_code not in (201, 405):  # 405 = already exists
            raise NextcloudError(f"Create directory failed ({resp.status_code})")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def rename(self, current_path: str, new_path: str) -> None:
        """Rename or move a remote file or folder."""
        resp = requests.request(
            "MOVE",
            self._url(current_path),
            headers={"Destination": self._url(new_path), "Overwrite": "F"},
            auth=self._auth,
            timeout=30,
        )
        if resp.status_code not in (201, 204):
            raise NextcloudError(f"Rename failed ({resp.status_code}): {resp.text[:200]}")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, remote_path: str) -> None:
        """Delete a remote file or directory (recursive for directories)."""
        resp = requests.request(
            "DELETE",
            self._url(remote_path),
            auth=self._auth,
            timeout=30,
        )
        if resp.status_code not in (200, 204):
            raise NextcloudError(f"Delete failed ({resp.status_code}): {resp.text[:200]}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dirs(self, remote_path: str) -> None:
        parts = remote_path.strip("/").split("/")
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else part
            try:
                self.create_directory(current)
            except NextcloudError:
                pass


# ------------------------------------------------------------------
# PROPFIND XML parser
# ------------------------------------------------------------------

def _parse_propfind(xml_text: str, dav_base: str) -> list[RemoteFile]:
    """Parse a WebDAV PROPFIND response into a list of RemoteFile objects."""
    dav_path_prefix = urlparse(dav_base).path
    root = ET.fromstring(xml_text)
    files: list[RemoteFile] = []

    for i, response in enumerate(root.findall(f"{{{_DAV}}}response")):
        href_el = response.find(f"{{{_DAV}}}href")
        if href_el is None or not href_el.text:
            continue

        href_path = unquote(href_el.text)
        rel = (
            href_path[len(dav_path_prefix):]
            if href_path.startswith(dav_path_prefix)
            else href_path.lstrip("/")
        )

        if i == 0:
            continue  # Skip the requested directory itself

        prop = response.find(f".//{{{_DAV}}}prop")
        if prop is None:
            continue

        rt = prop.find(f"{{{_DAV}}}resourcetype")
        is_dir = rt is not None and rt.find(f"{{{_DAV}}}collection") is not None

        size_el = prop.find(f"{{{_DAV}}}getcontentlength")
        size: int | None = (
            int(size_el.text) if size_el is not None and size_el.text else None
        )

        name = rel.rstrip("/").rsplit("/", 1)[-1]
        files.append(RemoteFile(name=name, path=rel.rstrip("/"), is_dir=is_dir, size_bytes=size))

    return sorted(files, key=lambda f: (not f.is_dir, f.name.lower()))
