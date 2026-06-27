from collections.abc import Sequence
from pathlib import Path

DEFAULT_CATEGORIES: tuple[str, ...] = ("cars", "tracks")


def scan_content(
    install_dir: Path,
    *,
    categories: Sequence[str] = DEFAULT_CATEGORIES,
) -> dict[str, list[str]]:
    """Return top-level folder names per content category.

    Each key in the result matches a category name; missing or empty
    category directories produce an empty list. Results within each
    category are sorted alphabetically.
    """
    content_dir = install_dir / "content"
    result: dict[str, list[str]] = {}

    for category in categories:
        category_dir = content_dir / category
        if category_dir.is_dir():
            result[category] = sorted(
                entry.name for entry in category_dir.iterdir() if entry.is_dir()
            )
        else:
            result[category] = []

    return result
