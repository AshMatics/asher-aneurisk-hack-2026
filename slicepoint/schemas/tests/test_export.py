"""(d) JSON Schema export is deterministic and the committed files are current."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import VERSION as PYDANTIC_VERSION

from conftest import JSONSCHEMA_DIR
from slicepoint_schemas.export import GENERATOR_STAMP, TOP_LEVEL_MODELS, diff_json_schemas, main, rendered_files


def test_export_is_deterministic() -> None:
    assert rendered_files() == rendered_files()


def test_every_top_level_model_exported() -> None:
    assert set(rendered_files()) == {f"{n}.schema.json" for n in TOP_LEVEL_MODELS}


def test_committed_files_match_regenerated() -> None:
    stamp = (JSONSCHEMA_DIR / GENERATOR_STAMP).read_text(encoding="utf-8").strip()
    if stamp != PYDANTIC_VERSION:
        pytest.skip(f"committed schemas were generated with pydantic {stamp}, running {PYDANTIC_VERSION}")
    stale = diff_json_schemas(JSONSCHEMA_DIR)
    assert stale == [], f"regenerate with `slicepoint-schemas-export`; stale: {stale}"


def test_cli_writes_and_checks(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path)]) == 0
    assert main(["--out", str(tmp_path), "--check"]) == 0
    (tmp_path / "Verdict.schema.json").write_text("{}\n")
    assert main(["--out", str(tmp_path), "--check"]) == 1


def test_legacy_schema_uses_aliases() -> None:
    schema = json.loads(rendered_files()["SlicePointFileV0.schema.json"])
    assert "fileType" in schema["properties"]
    assert "share_below_0.90" in schema["$defs"]["DiceMetricsV0"]["properties"]
