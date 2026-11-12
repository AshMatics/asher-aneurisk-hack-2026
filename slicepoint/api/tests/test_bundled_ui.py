"""The live viewer build shipped in this package (``_ui/``, written by ``pnpm build:api``)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from conftest import API_ROOT, make_client
from slicepoint_api.ui import UI_CSP, bundled_ui_dir

SCHEMA_FILE = API_ROOT.parent / "schemas" / "jsonschema" / "AssessmentResult.schema.json"
REBUILD = "the bundled web UI is stale: run `pnpm build:api` in slicepoint/viewer"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle() -> tuple[Path, dict[str, object]]:
    ui = bundled_ui_dir()
    assert ui is not None, "slicepoint_api/_ui is missing: run `pnpm build:api` in slicepoint/viewer"
    meta: dict[str, object] = json.loads((ui / "ui.json").read_text(encoding="utf-8"))
    return ui, meta


def test_bundled_ui_matches_the_current_api_and_contract() -> None:
    _, meta = _bundle()
    assert meta["openapi_sha256"] == _sha256(API_ROOT / "openapi.json"), REBUILD
    assert meta["schema_sha256"] == _sha256(SCHEMA_FILE), REBUILD


def test_bundled_ui_is_the_recorded_build() -> None:
    ui, meta = _bundle()
    files = meta["files"]
    assert isinstance(files, dict)
    on_disk = {p.relative_to(ui).as_posix() for p in ui.rglob("*") if p.is_file()} - {"ui.json"}
    assert on_disk == set(files), REBUILD
    for name, digest in files.items():
        assert _sha256(ui / name) == digest, f"{name}: {REBUILD}"


def test_bundled_index_loads_only_same_origin_assets() -> None:
    ui, _ = _bundle()
    html = (ui / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r"""\s(?:src|href)\s*=\s*["']([^"']*)["']""", html)
    assert refs and all(r.startswith("/assets/") and (ui / r.lstrip("/")).is_file() for r in refs)
    assert not re.search(r"<script\b[^>]*>\s*[^<\s]", html), "inline script"
    assert "<style" not in html.lower()


def test_bundled_ui_is_served(tmp_path: Path) -> None:
    ui, meta = _bundle()
    data = tmp_path / "data"
    data.mkdir()
    with make_client(data, tmp_path / "results", ui_dir=ui) as c:
        r = c.get("/")
        assert r.status_code == 200 and r.headers["content-security-policy"] == UI_CSP
        files = meta["files"]
        assert isinstance(files, dict)
        for name in files:
            if name.startswith("assets/"):
                assert c.get(f"/{name}").status_code == 200, name
        assert c.get("/ui.json").status_code == 401  # build metadata is not a UI route
