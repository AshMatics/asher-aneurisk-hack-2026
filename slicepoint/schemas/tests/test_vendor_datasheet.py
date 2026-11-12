"""VendorDatasheet: what a vendor discloses about its training data, marginals only."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from conftest import SCHEMAS_ROOT
from slicepoint_schemas import (
    KNOWN_VARIABLES,
    CategoricalSummary,
    ContinuousSummary,
    Histogram,
    ValueSource,
    VendorDatasheet,
)

EXAMPLE = SCHEMAS_ROOT / "examples" / "aaa-baseline-v0.vendor-datasheet.json"


def minimal() -> dict[str, Any]:
    """A datasheet shaped like a paper's figure: digitized age histogram, reported sex counts."""
    return {
        "datasheet_id": "paper-fig3",
        "title": "Segmentation model, training set (paper Figure 3)",
        "model": {"name": "Example segmenter", "version": "1"},
        "describes": "training",
        "scope": {"description": "Routine clinical CT, all body regions", "modality": "CT"},
        "n_scans": 1000,
        "sources": [{"source_id": "paper", "kind": "publication", "citation": "Author et al. 2023",
                     "doi": "10.1148/ryai.230024"}],
        "variables": [
            {"variable": "age_years", "n": 1000,
             "summary": {"kind": "continuous", "unit": "years",
                         "histogram": {"edges": [20, 40, 60, 80, 100], "counts": [100, 300, 450, 150]}},
             "sources": [{"source_id": "paper", "value_source": "digitized", "locator": "Figure 3"}]},
            {"variable": "sex", "n": 1000,
             "summary": {"kind": "categorical", "counts": {"F": 420, "M": 580}, "proportions": {"F": 0.42, "M": 0.58}},
             "sources": [{"source_id": "paper", "value_source": "reported", "locator": "Table 1"}]},
        ],
        "not_disclosed": ["joint distributions"],
    }


def test_example_file_validates() -> None:
    ds = VendorDatasheet.model_validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    assert ds.describes.value == "training"
    assert ds.n_scans == 333
    sex = ds.variable("sex")
    assert sex is not None and isinstance(sex.summary, CategoricalSummary)
    assert sum(sex.summary.shares().values()) == pytest.approx(1.0)
    for v in ds.variables:
        if v.variable in KNOWN_VARIABLES:
            assert v.summary.kind == KNOWN_VARIABLES[v.variable][0]


def test_minimal_round_trips() -> None:
    ds = VendorDatasheet.model_validate(minimal())
    again = VendorDatasheet.model_validate_json(ds.model_dump_json())
    assert again == ds
    age = ds.variable("age_years")
    assert age is not None and isinstance(age.summary, ContinuousSummary)
    assert age.summary.histogram is not None
    assert age.summary.histogram.shares() == pytest.approx((0.1, 0.3, 0.45, 0.15))
    assert age.weakest_value_source is ValueSource.DIGITIZED


def test_weakest_value_source_picks_least_direct() -> None:
    d = minimal()
    d["variables"][1]["sources"].append({"source_id": "paper", "value_source": "estimated"})
    sex = VendorDatasheet.model_validate(d).variable("sex")
    assert sex is not None and sex.weakest_value_source is ValueSource.ESTIMATED


def _invalid(mutate: Any, match: str) -> None:
    d = copy.deepcopy(minimal())
    mutate(d)
    with pytest.raises(ValidationError, match=match):
        VendorDatasheet.model_validate(d)


def test_rejects_unknown_source() -> None:
    _invalid(lambda d: d["variables"][0]["sources"][0].update(source_id="nope"), "unknown source_id")


def test_rejects_duplicate_variable() -> None:
    _invalid(lambda d: d["variables"].append(copy.deepcopy(d["variables"][1])), "listed twice")


def test_rejects_variable_without_source() -> None:
    _invalid(lambda d: d["variables"][1].update(sources=[]), "at least 1")


def test_known_variable_must_use_its_kind() -> None:
    _invalid(lambda d: d["variables"][1].update(variable="kvp"), "kvp must be a continuous summary")


def test_unknown_variable_name_is_accepted() -> None:
    d = minimal()
    d["variables"][1]["variable"] = "insurance_type"
    assert VendorDatasheet.model_validate(d).variable("insurance_type") is not None


def test_race_and_ethnicity_are_known_categoricals() -> None:
    assert KNOWN_VARIABLES["race"][0] == "categorical"
    assert KNOWN_VARIABLES["ethnicity"][0] == "categorical"
    _invalid(lambda d: d["variables"][0].update(variable="race"), "race must be a categorical summary")


def test_rejects_n_beyond_n_scans() -> None:
    _invalid(lambda d: d["variables"][1].update(n=990, n_missing=20), "exceeds n_scans")


def test_rejects_more_patients_than_scans() -> None:
    _invalid(lambda d: d.update(n_patients=1001), "n_patients exceeds n_scans")


def test_rejects_wrong_schema_version() -> None:
    _invalid(lambda d: d.update(schema_version="9.9.9"), "schema_version")


@pytest.mark.parametrize(
    ("summary", "match"),
    [
        ({"kind": "categorical"}, "needs counts or proportions"),
        ({"kind": "categorical", "proportions": {"F": 0.3, "M": 0.5}}, "sum to 0.800"),
        ({"kind": "categorical", "counts": {"F": 0, "M": 0}}, "all zero"),
        ({"kind": "categorical", "counts": {"F": 40, "M": 60}, "proportions": {"F": 0.5, "M": 0.5}}, "count share"),
        ({"kind": "categorical", "counts": {"F": 40}, "proportions": {"M": 1.0}}, "different categories"),
    ],
)
def test_categorical_rules(summary: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        CategoricalSummary.model_validate(summary)


def test_rounded_percentages_are_tolerated() -> None:
    s = CategoricalSummary.model_validate({"kind": "categorical", "proportions": {"a": 0.33, "b": 0.33, "c": 0.33}})
    assert sum(s.shares().values()) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("summary", "match"),
    [
        ({"unit": "years", "min": 18, "max": 90}, "needs mean and sd"),
        ({"unit": "years", "sd": 5, "median": 60, "q1": 50, "q3": 70}, "sd given without mean"),
        ({"unit": "years", "median": 60, "q1": 50}, "q1 and q3 together"),
        ({"unit": "years", "median": 60, "q1": 65, "q3": 70}, "min <= q1"),
        ({"unit": "years", "mean": 60, "sd": 5, "min": 61}, "mean is below min"),
        ({"unit": "years", "mean": 60, "sd": -1}, "greater than or equal to 0"),
    ],
)
def test_continuous_rules(summary: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        ContinuousSummary.model_validate(summary)


@pytest.mark.parametrize(
    ("hist", "match"),
    [
        ({"edges": [0, 10, 10], "counts": [1, 2]}, "strictly increasing"),
        ({"edges": [0, 10, 20], "counts": [1]}, "2 bins but 1 counts"),
        ({"edges": [0, 10, 20]}, "needs counts or proportions"),
        ({"edges": [0, 10, 20], "proportions": [0.5, 0.2]}, "sum to 0.700"),
        ({"edges": [0, 10, 20], "counts": [10, 30], "proportions": [0.5, 0.5]}, "disagree"),
    ],
)
def test_histogram_rules(hist: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        Histogram.model_validate(hist)


def test_datasheet_is_frozen() -> None:
    ds = VendorDatasheet.model_validate(minimal())
    with pytest.raises(ValidationError):
        ds.title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("path", sorted((SCHEMAS_ROOT / "examples").glob("*.vendor-datasheet.json")), ids=lambda p: p.name)
def test_every_example_validates(path: Any) -> None:
    ds = VendorDatasheet.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert path.name == f"{ds.datasheet_id}.vendor-datasheet.json"
