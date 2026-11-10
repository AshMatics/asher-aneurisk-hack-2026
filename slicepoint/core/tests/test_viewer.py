"""The interactive viewer bundled in slicepoint-core (``slicepoint assess --viewer``)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from slicepoint_core import InputError, copy_viewer, viewer_info, viewer_path
from slicepoint_core import viewer as viewer_mod
from slicepoint_schemas.common import SCHEMA_VERSION

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "schemas" / "jsonschema" / "AssessmentResult.schema.json"
REBUILD = "the bundled viewer is stale: run `pnpm build:core` in slicepoint/viewer"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bundled_viewer_matches_the_current_contract() -> None:
    info = viewer_info()
    assert info.schema_version == SCHEMA_VERSION, REBUILD
    assert info.schema_sha256 == _sha256(SCHEMA_FILE), REBUILD


def test_bundled_viewer_is_the_recorded_build() -> None:
    assert _sha256(viewer_path()) == viewer_info().html_sha256, REBUILD


def test_bundled_viewer_loads_nothing_external() -> None:
    html = viewer_path().read_text(encoding="utf-8")
    assert "default-src 'none'" in html
    assert not re.search(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""", html, re.IGNORECASE)
    assert "@import" not in html


def test_copy_viewer(tmp_path: Path) -> None:
    out = copy_viewer(tmp_path / "new" / "folder")
    assert out == tmp_path / "new" / "folder" / "slicepoint-viewer.html"
    assert out.read_bytes() == viewer_path().read_bytes()
    # An existing copy is replaced.
    out.write_text("old", encoding="utf-8")
    assert copy_viewer(out.parent).read_bytes() == viewer_path().read_bytes()


def test_missing_viewer_is_a_one_line_input_error() -> None:
    with pytest.raises(InputError, match=r"bundled viewer is missing .*pnpm build:core"):
        viewer_mod._bundled("not-there.html")
