# Assetto Corsa — Server Content Updater

A local Windows GUI tool for browsing and selecting Assetto Corsa content (cars, tracks) to synchronise with a dedicated server.

## Requirements

- Python 3.12+
- Tkinter (ships with Python on Windows)
- [7-Zip](https://www.7-zip.org/) — required for archive creation
- Nextcloud instance with WebDAV access (for the upload feature)

## Usage

```bash
python main.py
```

On launch the app will locate your Assetto Corsa install automatically. If it
cannot be found (default Steam path and registry both fail), a folder picker
dialog will open so you can browse to it manually.

### Main window

Two side-by-side panels list every car and track found under your AC
`content/` directory. All items are selected by default.

| Control | Action |
|---|---|
| Checkbox | Toggle a single item |
| Select All | Tick everything in that panel |
| Deselect All | Untick everything in that panel |
| Change... | Switch to a different AC install directory without restarting |
| Save Selection | Write ticked items to `selections/selection.txt` |
| Create Archive | Compress ticked content into a `.7z` file via a save dialog |
| Create & Upload to Nextcloud | Create archive then upload it to a Nextcloud share |

**Create Archive** and **Create & Upload** both require 7-Zip installed on the system.
Archives preserve the AC content layout (`cars/<name>`, `tracks/<name>`) for direct
extraction into a server's `content/` directory.

### Nextcloud integration

Click **Create & Upload to Nextcloud** to open the connection dialog on first use.
Enter your Nextcloud server URL, username, and password, then click **Test Connection**
before saving. Credentials are persisted to `~/.ac_updater/nextcloud.json`.

Once connected the file browser opens automatically after the archive is built:

| Control | Action |
|---|---|
| Double-click folder | Navigate into it |
| ↑ Up | Go up one level |
| New Folder | Create a remote directory |
| Rename | Rename or move selected item |
| Delete | Permanently delete selected item |
| Upload Here | Upload the archive to the current remote folder |

### Selection file

`selections/selection.txt` uses a simple INI-style format:

```
[cars]
ferrari_458_italia
bmw_m3_e30

[tracks]
monza
spa
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/ tests/
mypy src/
```
