"""Errors a user can fix: a missing or malformed input file, folder or column.

:class:`InputError` is a :class:`ValueError`, so existing ``except ValueError`` code keeps
working. Its message is a single line that names the file (and the column when there is
one), so the CLI can print it as is. Missing files and folders still raise
:class:`FileNotFoundError`.
"""

from __future__ import annotations

from pathlib import Path


class InputError(ValueError):
    """An input file, folder or column is wrong. ``path`` and ``column`` locate it."""

    def __init__(self, message: str, *, path: str | Path | None = None, column: str | None = None) -> None:
        super().__init__(message)
        self.path = None if path is None else str(path)
        self.column = column


__all__ = ["InputError"]
