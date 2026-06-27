# Assetto Corsa — Server Content Updater

A local Windows GUI tool for browsing and selecting Assetto Corsa content (cars, tracks) to synchronise with a dedicated server.

## Requirements

- Python 3.12+
- Tkinter (ships with Python on Windows)

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
| Save Selection | Write ticked items to `selections/selection.txt` |

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
