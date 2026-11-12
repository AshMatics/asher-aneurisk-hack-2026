"""Comparing a site with a VendorDatasheet: coverage and equality, from summary statistics only."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from slicepoint_schemas import VendorDatasheet

from conftest import REPO_ROOT, load_site, needs_data
from slicepoint_core.cli import main
from slicepoint_core.datasheet import DatasheetComparison, Status, compare_to_datasheet
from slicepoint_core.ingestion import TabularDataset

EXAMPLE = REPO_ROOT / "slicepoint" / "schemas" / "examples" / "aaa-baseline-v0.vendor-datasheet.json"
SOURCE = [{"source_id": "s", "value_source": "reported"}]


def example() -> VendorDatasheet:
    return VendorDatasheet.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))


def statuses(result: DatasheetComparison) -> dict[str, Status]:
    return {v.variable: v.status for v in result.variables}


def site(n: int = 200, seed: int = 0, **cols: Any) -> TabularDataset:
    """A synthetic site with only the columns a test needs."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({
        "case_id": [f"c{i}" for i in range(n)],
        "patient_id": [f"p{i}" for i in range(n)],
        "sex": rng.choice(["M", "F"], n, p=[0.55, 0.45]),
        "scanner_vendor": rng.choice(["siemens", "ge"], n, p=[0.8, 0.2]),
        "kvp": rng.choice([100.0, 120.0], n),
        "age_band": rng.choice(["50-59", "60-69", "70-79"], n),
    })
    for k, v in cols.items():
        frame[k] = v
    return TabularDataset(site_id="synthetic", frame=frame, embeddings=None, space=None, has_labels=False)


def sheet(*variables: dict[str, Any], **top: Any) -> VendorDatasheet:
    d: dict[str, Any] = {
        "datasheet_id": "t", "title": "t", "model": {"name": "m"}, "describes": "training",
        "scope": {"description": "test"}, "n_scans": 1000,
        "sources": [{"source_id": "s", "kind": "publication", "citation": "c"}],
        "variables": list(variables),
    }
    d.update(top)
    return VendorDatasheet.model_validate(d)


def cat(variable: str, **kw: Any) -> dict[str, Any]:
    return {"variable": variable, "summary": {"kind": "categorical", **kw}, "sources": SOURCE}


def cont(variable: str, **kw: Any) -> dict[str, Any]:
    return {"variable": variable, "summary": {"kind": "continuous", **kw}, "sources": SOURCE}


# --------------------------------------------------------------------------- synthetic


def test_matching_mix_is_similar() -> None:
    r = compare_to_datasheet(site(), sheet(cat("sex", proportions={"M": 0.55, "F": 0.45})))
    assert statuses(r)["sex"] is Status.SIMILAR


def test_different_mix_differs() -> None:
    r = compare_to_datasheet(site(), sheet(cat("sex", proportions={"M": 0.2, "F": 0.8})))
    v = r.variables[0]
    assert v.status is Status.DIFFERS
    assert v.equality is not None and v.equality.effect is not None and v.equality.effect > 0.25
    assert v.equality.method == "chi2_contingency"  # n_scans known -> two-sample test


def test_goodness_of_fit_when_datasheet_n_unknown() -> None:
    r = compare_to_datasheet(site(), sheet(cat("sex", proportions={"M": 0.2, "F": 0.8}), n_scans=None))
    assert r.variables[0].equality is not None
    assert r.variables[0].equality.method == "chi2_goodness_of_fit"


def test_unlisted_category_is_outside_coverage() -> None:
    r = compare_to_datasheet(site(), sheet(cat("scanner_vendor", proportions={"siemens": 1.0})))
    v = r.variables[0]
    assert v.status is Status.OUTSIDE_COVERAGE
    assert v.coverage is not None and "ge" in v.coverage.detail


def test_catch_all_category_absorbs_unlisted() -> None:
    r = compare_to_datasheet(site(), sheet(cat("scanner_vendor", proportions={"siemens": 0.8, "other": 0.2})))
    v = r.variables[0]
    assert v.status is Status.SIMILAR
    assert v.coverage is not None and v.coverage.outside_n == 0


def test_category_keys_match_case_insensitively() -> None:
    r = compare_to_datasheet(site(), sheet(cat("scanner_vendor", proportions={"Siemens": 0.8, "GE": 0.2})))
    assert statuses(r)["scanner_vendor"] is Status.SIMILAR


def test_scope_broader_marks_differences_expected_but_keeps_coverage() -> None:
    ds = sheet(cat("sex", proportions={"M": 0.2, "F": 0.8}), cat("scanner_vendor", proportions={"siemens": 1.0}))
    r = compare_to_datasheet(site(), ds, scope_broader=True)
    assert statuses(r) == {"sex": Status.DIFFERS_EXPECTED, "scanner_vendor": Status.OUTSIDE_COVERAGE}


def test_values_outside_disclosed_range() -> None:
    r = compare_to_datasheet(site(), sheet(cont("kvp", unit="kV", mean=110, sd=10, min=100, max=110)))
    v = r.variables[0]
    assert v.status is Status.OUTSIDE_COVERAGE
    assert v.coverage is not None and v.coverage.outside_share > 0.3


def test_tied_quartiles_fall_back_to_mean_and_sd() -> None:
    r = compare_to_datasheet(site(), sheet(cont("kvp", unit="kV", mean=110, sd=10, median=120, q1=100, q3=120)))
    v = r.variables[0]
    assert v.equality is not None and v.equality.method == "welch_t_from_summary_statistics"
    assert v.reason is not None and "quartiles tie" in v.reason


def test_histogram_bins_are_used() -> None:
    values = np.random.default_rng(1).normal(25, 5, 300)
    d = site(300, max_aortic_diameter_mm=values)
    ds = sheet(cont("max_aortic_diameter_mm", unit="mm",
                    histogram={"edges": [0, 20, 25, 30, 100], "proportions": [0.16, 0.34, 0.34, 0.16]}))
    v = compare_to_datasheet(d, ds).variables[0]
    assert v.status is Status.SIMILAR
    assert v.equality is not None and "histogram" in v.equality.method


def test_age_bands_missing_from_site_count_as_zero() -> None:
    """A site with nobody under 50 must not look like a datasheet that spans 20 to 90."""
    ds = sheet(cont("age_years", unit="years", median=55, q1=42, q3=68, min=20, max=95))
    v = compare_to_datasheet(site(), ds).variables[0]
    assert v.status is Status.DIFFERS
    assert v.equality is not None and v.equality.approximate
    assert v.equality.datasheet_shares is not None and "20-29" in v.equality.datasheet_shares
    assert v.equality.site_shares is not None and v.equality.site_shares["20-29"] == 0.0


def test_variable_without_site_column_is_not_testable() -> None:
    r = compare_to_datasheet(site(), sheet(cat("race", proportions={"a": 0.5, "b": 0.5})))
    v = r.variables[0]
    assert v.status is Status.NOT_TESTABLE
    assert v.reason is not None and "no column" in v.reason


def test_digitized_source_marks_equality_approximate() -> None:
    var = cat("sex", proportions={"M": 0.55, "F": 0.45})
    var["sources"] = [{"source_id": "s", "value_source": "digitized", "locator": "Figure 3"}]
    v = compare_to_datasheet(site(), sheet(var)).variables[0]
    assert v.equality is not None and v.equality.approximate


def test_site_columns_the_datasheet_skips_are_listed() -> None:
    r = compare_to_datasheet(site(), sheet(cat("sex", proportions={"M": 0.55, "F": 0.45})))
    assert "scanner_vendor" in r.site_columns_not_in_datasheet
    assert "sex" not in r.site_columns_not_in_datasheet


def test_result_round_trips() -> None:
    r = compare_to_datasheet(site(), sheet(cat("sex", proportions={"M": 0.55, "F": 0.45})))
    assert DatasheetComparison.model_validate_json(r.model_dump_json()) == r


# --------------------------------------------------------------------------- practice data


@needs_data
def test_clean_site_reads_similar() -> None:
    """hospital_a is a clean sample of the same population as the example datasheet."""
    r = compare_to_datasheet(load_site("hospital_a"), example())
    assert set(statuses(r).values()) == {Status.SIMILAR}


@needs_data
def test_planted_shifts_are_found() -> None:
    c = statuses(compare_to_datasheet(load_site("hospital_c"), example()))
    assert c["slice_thickness_class"] is Status.DIFFERS and c["contrast_phase"] is Status.DIFFERS
    d = statuses(compare_to_datasheet(load_site("hospital_d"), example()))
    for var in ("age_years", "sex", "aaa", "max_aortic_diameter_mm"):
        assert d[var] is Status.DIFFERS, var


@needs_data
def test_cli_exit_codes_and_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = ["datasheet", "check", "--datasheet", str(EXAMPLE), "--json"]
    from conftest import PRACTICE_DIR

    assert main([*base, "--data", str(PRACTICE_DIR / "hospital_a"), "--site-id", "hospital_a"]) == 0
    out = tmp_path / "cmp.json"
    assert main([*base, "--data", str(PRACTICE_DIR / "hospital_c"), "--site-id", "hospital_c", "--out", str(out)]) == 3
    assert '"exit_code": 3' in capsys.readouterr().out
    saved = DatasheetComparison.model_validate_json(out.read_text(encoding="utf-8"))
    assert saved.site_id == "hospital_c"
    bad = copy.deepcopy(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    bad["variables"] = []
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps(bad), encoding="utf-8")
    assert main([*base, "--data", str(PRACTICE_DIR / "hospital_a"), "--site-id", "hospital_a",
                 "--datasheet", str(bad_file)]) == 1
