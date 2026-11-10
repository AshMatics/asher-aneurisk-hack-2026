from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

SCHEMAS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SCHEMAS_ROOT.parents[1]
SAMPLE_DIR = REPO_ROOT / "slicepoint" / "python_notebooks" / "hospital_test_output"
PRACTICE_DIR = REPO_ROOT / "data" / "practice"
JSONSCHEMA_DIR = SCHEMAS_ROOT / "jsonschema"

SAMPLE_FILES = sorted(SAMPLE_DIR.glob("hospital_*_slicepoint.json"))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(params=SAMPLE_FILES, ids=[p.name for p in SAMPLE_FILES])
def sample_raw(request: pytest.FixtureRequest) -> dict[str, Any]:
    raw: dict[str, Any] = load_json(request.param)
    return raw


@pytest.fixture
def hospital_b_raw() -> dict[str, Any]:
    raw: dict[str, Any] = load_json(SAMPLE_DIR / "hospital_b_slicepoint.json")
    return raw
