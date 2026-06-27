from pathlib import Path


def save_selection(path: Path, selection: dict[str, list[str]]) -> None:
    """Write selected items to a text file, grouped by category.

    File format:
        [cars]
        ferrari_458_italia
        bmw_m3_e30

        [tracks]
        monza
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for category, items in selection.items():
        lines.append(f"[{category}]")
        lines.extend(items)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def load_selection(path: Path) -> dict[str, list[str]]:
    """Read a selection file written by save_selection.

    Returns an empty dict if the file does not exist.
    """
    if not path.exists():
        return {}

    result: dict[str, list[str]] = {}
    current_category: str | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]") and len(line) > 2:
            current_category = line[1:-1]
            result[current_category] = []
        elif line and current_category is not None:
            result[current_category].append(line)

    return result
