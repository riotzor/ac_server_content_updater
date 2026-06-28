# Assetto Corsa — Server Content Updater

A local Windows GUI tool for browsing and selecting Assetto Corsa content (cars, tracks) to synchronise with a dedicated server — via network share copy, SSH deploy, Nextcloud upload, or local archive.

## Requirements

- Python 3.12+
- Tkinter (ships with Python on Windows)
- [7-Zip](https://www.7-zip.org/) — required for archive creation and Nextcloud upload
- `keyring` — installed automatically as a dependency (uses Windows Credential Manager)
- Nextcloud instance with WebDAV access _(optional — for the upload feature)_
- SSH access to the AC server _(optional — for direct server management)_

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
python main.py
```

On first launch the app locates your Assetto Corsa install automatically via the Steam registry and common install paths. If it cannot be found, a folder picker opens so you can select it manually. The chosen path is saved and used on subsequent launches.

---

## Interface

The window has a persistent header showing your current AC install path and a **Change...** button. Below it, four tabs organise the available functionality.

### Tab 1 — Content Browser

All cars and tracks found under `<AC install>/content/` are listed in scrollable panels, all ticked by default. This selection drives every action across the other tabs.

| Control | Action |
|---|---|
| Checkbox | Toggle a single item |
| Select All | Tick all items in that panel |
| Deselect All | Untick all items in that panel |
| Save Selection | Write the current selection to `selections/selection.txt` |

The selection file uses a simple INI-style format:

```
[cars]
ferrari_458_italia
bmw_m3_e30

[tracks]
monza
spa
```

### Tab 2 — Server Manager

Manages content on the AC server via a network share and an optional SSH connection.

**Network share copy** — copies server-relevant files from the current selection directly to a configured network share. Only the files the AC server actually reads are copied:

| Content type | Files copied |
|---|---|
| Car | `<car>/data.acd` |
| Track | `<track>/models.ini`, `<track>/data/surfaces.ini` |

The destination share path is shown at the top with a **Change...** button. A **Copy to Share** button starts the operation.

**Results** — dark log at the bottom of the share section; shows a timestamped, colour-coded line per operation (green = all copied, orange = some files not found, red = OS errors). A **Clear** button resets it.

**SSH Connection** — manages a persistent SSH session to the AC server host. Fields for host, user, and private key file persist across launches. If the key is passphrase-protected, the passphrase is stored in **Windows Credential Manager** (not in the key file or any config file); a **Forget Passphrase** button removes it. Leaving the key field blank uses the default `~/.ssh/` keys.

Once connected, a **Target server** dropdown lists AC server directories found on the host. Selecting one reveals:

- **Service controls** — Start / Stop / Restart buttons and a live status indicator
- **From Share** — content currently present on the network share; tick items to include in a deploy
- **On Server** — the selected server's installed content, split into Cars and Tracks panels

| On Server button | Action |
|---|---|
| Deploy to Server | SFTP-copies ticked share items into the server's `content/` directory; auto-rebuilds `entry_list.ini` and syncs `MAX_CLIENTS`; restarts the service |
| Fix Permissions | Corrects file ownership/mode on the selected items |
| Set as AI | Marks the selected cars as AI-driveable in `entry_list.ini` |
| Fix surfaces.ini | Patches `[SURFACE_0]` → `[CSPFACE_0]` in the track's surfaces file |
| Delete | Removes the selected items from the server |
| Change… (active track) | Updates `server_cfg.ini` to point at a different track |

### Tab 3 — Nextcloud

Uploads content archives to a Nextcloud instance via WebDAV.

**Connections** — two status rows:

- **Nextcloud** — click **Connect...** to open the credentials dialog. Enter your server URL, username, and password, then click **Test Connection**. The password is stored in **Windows Credential Manager**; the URL and username are saved to `~/.ac_updater/nextcloud.json`. If credentials are already saved, the app attempts to reconnect automatically at startup without showing a dialog. **Forget Credentials** removes the keyring entry and the config file.

- **AC Server** — mirrors the SSH connection status from the Server Manager tab. An active SSH connection is required for the **Create & Upload Server Pack** action.

**Content Packs** — two archive-and-upload actions:

| Button | What it archives |
|---|---|
| Create & Upload to Nextcloud | The current Content Browser selection |
| Create & Upload Server Pack | The target AC server's `content/` directory (requires SSH) |

Both actions: create a `.7z` archive with 7-Zip, then set it as the pending upload in the embedded file browser. Files over 10 MB are uploaded using Nextcloud's chunked-upload protocol so Cloudflare proxy limits are not a concern.

**Progress bar** — shows progress for both archive creation (item count) and upload (byte count).

**Logs** — live dark log pane that streams archive and upload activity from the `ac_updater` logger.

**Nextcloud Files** — the Nextcloud file browser is embedded directly in the right side of the tab (no separate dialog). Navigate to the target folder and click **Upload Here** when the archive is ready.

| Browser control | Action |
|---|---|
| Double-click folder | Navigate into it |
| ↑ Up | Go up one directory level |
| New Folder | Create a remote directory |
| Rename | Rename or move the selected item |
| Delete | Permanently delete the selected item |
| Upload Here | Upload the pending archive to the current folder |

### Tab 4 — Archive

Create a `.7z` archive of the current selection and save it locally.

Click **Create Archive...** to open a save dialog. The archive preserves the AC content layout (`cars/<name>`, `tracks/<name>`) so it can be extracted directly into a server's `content/` directory. The path of the last created archive is shown below the button.

---

## Persistent state

All state files are written to `~/.ac_updater/` (outside the repository).

| File | Contents |
|---|---|
| `~/.ac_updater/install.json` | AC install directory |
| `~/.ac_updater/share.json` | Last-used network share path |
| `~/.ac_updater/ssh.json` | SSH host, username, and key file path (no passphrase) |
| `~/.ac_updater/nextcloud.json` | Nextcloud URL and username (no password) |
| `~/.ac_updater/logs/ac_updater.log` | Rotating application log (2 MB × 3 backups) |

SSH passphrases and the Nextcloud password are stored exclusively in **Windows Credential Manager** via the `keyring` package — never written to disk in plain text.

---

## Logging

The application logs to `~/.ac_updater/logs/ac_updater.log`. Each module has its own named logger within the `ac_updater` hierarchy:

| Logger | What is recorded |
|---|---|
| `ac_updater.archiver` | 7-Zip invocation, exit code, stderr on failure |
| `ac_updater.content_copier` | Per-file copy, skip (not found), OS errors, surfaces.ini patch |
| `ac_updater.nextcloud_client` | Every HTTP method and status code, chunked upload progress |
| `ac_updater.nextcloud_config` | Credential save/load/clear/migrate events — passwords are never logged |
| `ac_updater.ssh_client` | SSH auth, SFTP file ops, deploy per-item results, service control, entry_list rebuild, MAX_CLIENTS sync |
| `ac_updater.ssh_config` | SSH config load and save events |
| `ac_updater.passphrase_store` | Passphrase save/forget events in OS keyring |
| `ac_updater.gui.app` | User actions, flow transitions, share copy outcome, temp-file lifecycle |
| `ac_updater.gui.nextcloud_panel` | Dialog events, file browser CRUD operations, upload start/result |

Log files are excluded from version control.

---

## Development

```bash
pip install -e ".[dev]"
pytest                     # run test suite with coverage
ruff check src/ tests/     # lint
mypy src/                  # type check
```

Tests cover all non-GUI modules. The GUI (`app.py`, `nextcloud_panel.py`) is excluded from the test suite as it requires a display.
