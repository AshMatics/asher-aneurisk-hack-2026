"""Serve the live viewer (``slicepoint/viewer``, live build) at ``/``.

The build ships inside this package under ``_ui/`` (copied in by ``pnpm build:api``), so a
plain ``pip install`` serves the UI. ``SLICEPOINT_UI_DIR`` points at another build instead
(for example ``viewer/dist-live`` while developing), and ``SLICEPOINT_UI=off`` serves none.
``_ui/ui.json`` records which openapi.json and result schema the build was made against;
the tests fail when it is stale. The shell and its hashed assets hold no data, so
they are served without authentication; every API call the page makes still needs the
session cookie. Only ``/``, ``/index.html`` and files under ``/assets/`` are served, with
plain path segments only (no dot-files, no ``..``), and the resolved file must sit inside
the UI folder (a symlink pointing out of it is refused).
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

UI_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
          "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
"""The live page talks only to its own origin. No inline script or style is allowed."""

_SEGMENT = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")
_MEDIA = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png",
          ".ico": "image/x-icon", ".json": "application/json", ".map": "application/json",
          ".woff2": "font/woff2", ".txt": "text/plain"}


_BUNDLED_DIR = "_ui"


def bundled_ui_dir() -> Path | None:
    """The live viewer build shipped in this package, or None if this install lacks it."""
    path = Path(str(resources.files("slicepoint_api").joinpath(_BUNDLED_DIR)))
    return path if (path / "index.html").is_file() else None


def is_ui_path(path: str) -> bool:
    return path in ("/", "/index.html") or path.startswith("/assets/")


def resolve_ui_file(ui_dir: Path, relative: str) -> Path | None:
    """``ui_dir / relative`` if it is a plain file inside ``ui_dir``, else None."""
    parts = relative.split("/")
    if not parts or not all(_SEGMENT.match(p) for p in parts):
        return None
    root = ui_dir.resolve()
    target = root.joinpath(*parts)
    try:
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return None
    return resolved


def add_ui_routes(app: FastAPI, ui_dir: Path) -> None:
    headers = {"Content-Security-Policy": UI_CSP}

    def _file(relative: str) -> FileResponse:
        path = resolve_ui_file(ui_dir, relative)
        if path is None:
            raise HTTPException(404, "not found")
        media = _MEDIA.get(path.suffix.lower())
        if media is None:
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type=media, headers=headers)

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    @app.api_route("/index.html", methods=["GET", "HEAD"], include_in_schema=False)
    def ui_index() -> FileResponse:
        path = resolve_ui_file(ui_dir, "index.html")
        if path is None:
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type="text/html; charset=utf-8", headers=headers)

    @app.api_route("/assets/{asset:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def ui_asset(asset: str) -> FileResponse:
        return _file(f"assets/{asset}")
