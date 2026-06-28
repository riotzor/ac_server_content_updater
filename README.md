# Assetto Corsa — Server Content Updater

A local Windows GUI tool for browsing and selecting Assetto Corsa content (cars, tracks) to synchronise with a dedicated server — via network share copy, Nextcloud upload, or local archive.

## Requirements

- Python 3.12+
- Tkinter (ships with Python on Windows)
- [7-Zip](https://www.7-zip.org/) — required for archive creation and Nextcloud upload
- `keyring` — installed automatically as a dependency (uses Windows Credential Manager)
- Nextcloud instance with WebDAV access _(optional — for the upload feature)_

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
python main.py
```

On first launch the app locates your Assetto Corsa install automatically via the Steam registry and common install paths. If it cannot be found a folder picker opens so you can select it manually.

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

### Tab 2 — Server Update

Copies server-relevant files from the current selection directly to a network share. Only the files the AC server actually reads are copied — not the full content directories.

| Content type | Files copied |
|---|---|
| Car | `<car>/data.acd` |
| Track | `<track>/modes.ini`, `<track>/data/surfaces.ini` |

The destination share (default `\\192.168.1.215\ac-share`) is shown at the top with a **Change...** button. The path persists to `~/.ac_updater/share.json`.

A **Results** log at the bottom of the tab shows a timestamped, colour-coded line for each operation run during the session (green = all copied, orange = some files not found in AC install, red = OS errors). A **Clear** button resets the log.

### Tab 3 — Nextcloud

Upload content archives to a Nextcloud instance via WebDAV.

**Connection** — click **Connect...** to open the credentials dialog. Enter your server URL, username and password, then click **Test Connection**. The password is stored in **Windows Credential Manager** (not written to disk in plain text). The URL and username are saved to `~/.ac_updater/nextcloud.json`. The tab shows live connection status.

Once connected, click **Create & Upload to Nextcloud** to:
1. Create a `.7z` archive of the current selection (same as the Archive tab)
2. Open a file browser to choose the upload destination on Nextcloud

The default archive name is `cars.7z`, `tracks.7z`, or `content.7z` depending on the selection — editable before uploading. Files over 10 MB are uploaded using Nextcloud's chunked-upload protocol so Cloudflare proxy limits are not a concern.

**Nextcloud file browser controls:**

| Control | Action |
|---|---|
| Double-click folder | Navigate into it |
| ↑ Up | Go up one directory level |
| New Folder | Create a remote directory |
| Rename | Rename or move the selected item |
| Delete | Permanently delete the selected item |
| Upload Here | Upload the archive to the current folder |

### Tab 4 — Archive

Create a `.7z` archive of the current selection and save it locally.

Click **Create Archive...** to open a save dialog. The archive preserves the AC content layout (`cars/<name>`, `tracks/<name>`) so it can be extracted directly into a server's `content/` directory. The path of the last created archive is shown below the button.

---

## Persistent state

All state files are written to `~/.ac_updater/` (outside the repository).

| File | Contents |
|---|---|
| `~/.ac_updater/nextcloud.json` | Nextcloud URL and username (no password) |
| `~/.ac_updater/share.json` | Last-used network share path |
| `~/.ac_updater/logs/ac_updater.log` | Rotating application log (2 MB × 3 backups) |

---

## Logging

The application logs to `~/.ac_updater/logs/ac_updater.log`. Each module has its own named logger within the `ac_updater` hierarchy:

| Logger | What is recorded |
|---|---|
| `ac_updater.archiver` | 7-Zip invocation, exit code, stderr on failure |
| `ac_updater.content_copier` | Per-file copy, skip (not found), OS errors |
| `ac_updater.nextcloud_client` | Every HTTP method and status code, chunked upload progress |
| `ac_updater.nextcloud_config` | Credential save/load/migrate events — passwords are never logged |
| `ac_updater.gui.app` | User actions, flow transitions, temp-file lifecycle |
| `ac_updater.gui.nextcloud_panel` | Dialog events, CRUD operations, upload start/result |

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
