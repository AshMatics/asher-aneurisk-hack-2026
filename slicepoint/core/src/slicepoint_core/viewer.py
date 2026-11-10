"""The interactive viewer that ships inside this package.

``_viewer/slicepoint-viewer.html`` is the single-file build of ``slicepoint/viewer`` (the
React static viewer), copied in by ``pnpm build:core``. ``_viewer/viewer.json`` records
which contract it reads. :func:`copy_viewer` writes it next to a ``result.json`` so a
hospital can open the viewer and drop the result onto it without downloading anything.
The viewer makes no network requests; it reads only the file the user opens.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .errors import InputError

VIEWER_FILENAME = "slicepoint-viewer.html"
_PACKAGE_DIR = "_viewer"


@dataclass(frozen=True)
class ViewerInfo:
    """What the bundled viewer was built from (``_viewer/viewer.json``)."""

    viewer_version: str
    schema_version: str
    schema_sha256: str
    html_sha256: str


def _bundled(name: str) -> Path:
    path = Path(str(resources.files("slicepoint_core").joinpath(_PACKAGE_DIR).joinpath(name)))
    if not path.is_file():
        raise InputError(
            f"the bundled viewer is missing ({_PACKAGE_DIR}/{name}); this install was made without it. "
            "From a source checkout run `pnpm build:core` in slicepoint/viewer",
            path=path,
        )
    return path


def viewer_path() -> Path:
    """Path of the bundled ``slicepoint-viewer.html``."""
    return _bundled(VIEWER_FILENAME)


def viewer_info() -> ViewerInfo:
    """Version and contract of the bundled viewer."""
    data = json.loads(_bundled("viewer.json").read_text(encoding="utf-8"))
    return ViewerInfo(
        viewer_version=str(data["viewer_version"]),
        schema_version=str(data["schema_version"]),
        schema_sha256=str(data["schema_sha256"]),
        html_sha256=str(data["html_sha256"]),
    )


def copy_viewer(dest: str | Path) -> Path:
    """Copy the viewer into ``dest`` (a folder, created if needed) and return the new file.

    An existing ``slicepoint-viewer.html`` there is replaced.
    """
    folder = Path(dest)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / VIEWER_FILENAME
    shutil.copyfile(viewer_path(), target)
    return target


__all__ = ["VIEWER_FILENAME", "ViewerInfo", "copy_viewer", "viewer_info", "viewer_path"]
