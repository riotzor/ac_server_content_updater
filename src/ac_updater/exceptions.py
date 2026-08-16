from __future__ import annotations


class OperationCancelled(Exception):
    """Raised when the user cancels a long-running archive or upload operation."""
