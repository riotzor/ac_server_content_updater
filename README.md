# Assetto Corsa — Server Content Updater

A local Windows GUI tool for browsing and selecting Assetto Corsa content (cars, tracks) to synchronise with a dedicated server.

## Requirements

- Python 3.12+
- Tkinter (ships with Python on Windows)

## Usage

```bash
python main.py
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/ tests/
mypy src/
```
