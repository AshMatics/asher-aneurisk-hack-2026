from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE

from slicepoint_core import Assessment, AssessmentReport, ParquetAdapter, ReferenceProfile, TabularDataset

CORE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CORE_ROOT.parents[1]
PRACTICE_DIR = REPO_ROOT / "data" / "practice"
LEGACY_DIR = REPO_ROOT / "slicepoint" / "python_notebooks" / "hospital_test_output"
NOTEBOOK_DIR = REPO_ROOT / "slicepoint" / "python_notebooks"

PARITY_SITES = ("hospital_b", "hospital_c", "hospital_d", "hospital_e")
FIXED_NOW = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc)

needs_data = pytest.mark.skipif(not (PRACTICE_DIR / "hospital_a").exists(), reason="practice data not present")


def load_site(site: str) -> TabularDataset:
    return ParquetAdapter(site).load_tabular(PRACTICE_DIR / site)


def load_legacy(site: str) -> dict[str, Any]:
    raw: dict[str, Any] = json.loads((LEGACY_DIR / f"{site}_slicepoint.json").read_text(encoding="utf-8"))
    return raw


@pytest.fixture(scope="session")
def site_a() -> TabularDataset:
    return load_site("hospital_a")


@pytest.fixture(scope="session")
def reference(site_a: TabularDataset) -> ReferenceProfile:
    return ReferenceProfile.build(site_a, HACKATHON_DEFAULT_PROFILE, built_at=FIXED_NOW)


@pytest.fixture(scope="session")
def reports(reference: ReferenceProfile) -> dict[str, AssessmentReport]:
    return {
        s: Assessment(load_site(s), reference, HACKATHON_DEFAULT_PROFILE, now=FIXED_NOW).run() for s in PARITY_SITES
    }
