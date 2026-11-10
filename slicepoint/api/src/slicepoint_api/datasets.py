"""Server-side dataset folders under ``SLICEPOINT_DATA_ROOT``.

Requests name a dataset by its path relative to the data root (for example
``hospital_b`` or ``practice/hospital_b``). Absolute paths, ``..``, backslashes and
anything that resolves outside the root (a symlink escape) are rejected. Error messages
repeat only the name the client sent, never a server path.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import AfterValidator, Field

MAX_DEPTH = 3
"""How deep under the data root a dataset folder may sit (and how deep listing looks)."""

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MARKER_FILE = "features.parquet"
"""A folder holding this file is listed as a dataset."""


class DatasetPathError(ValueError):
    """The dataset name is unsafe, or is not a folder under the data root."""


def _check_name(name: str) -> str:
    if not name or name != name.strip():
        raise ValueError("dataset must be a non-empty relative folder name")
    if "\\" in name or "\x00" in name:
        raise ValueError("dataset must use '/' separators")
    p = PurePosixPath(name)
    if p.is_absolute() or name.startswith("~"):
        raise ValueError("dataset must be relative to the data root, not an absolute path")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("dataset must not contain '.', '..' or empty path segments")
    if len(parts) > MAX_DEPTH:
        raise ValueError(f"dataset may be at most {MAX_DEPTH} folders deep")
    if not all(_SEGMENT.match(part) for part in parts):
        raise ValueError("dataset folder names may use letters, digits, '_', '-' and '.' only")
    return name


DatasetName = Annotated[
    str,
    Field(max_length=400, description="Dataset folder, relative to the server's data root (e.g. hospital_b).",
          examples=["hospital_b"]),
    AfterValidator(_check_name),
]


def resolve_dataset(root: Path, name: str) -> Path:
    """The real folder for ``name`` under ``root`` (already resolved).

    Raises :class:`DatasetPathError` with a message that names only ``name``.
    """
    try:
        _check_name(name)
    except ValueError as exc:
        raise DatasetPathError(str(exc)) from None
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or candidate == root or not candidate.is_dir():
        raise DatasetPathError(f"dataset {name!r} is not a folder under the data root")
    return candidate


def list_datasets(root: Path) -> list[str]:
    """Relative names of folders under ``root`` that hold a ``features.parquet``.

    Symlinked folders are not followed, so listing never leaves the root.
    """
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = Path(dirpath).relative_to(root)
        depth = 0 if rel == Path(".") else len(rel.parts)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")) if depth < MAX_DEPTH else []
        if depth and MARKER_FILE in filenames:
            name = rel.as_posix()
            try:
                _check_name(name)
            except ValueError:
                continue
            found.append(name)
    return sorted(found)
