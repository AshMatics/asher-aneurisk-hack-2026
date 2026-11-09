"""(a) The six POC sample files validate as SlicePointFileV0 and round-trip, plus the
other legacy payloads and the legacy -> new converters."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from conftest import SAMPLE_FILES
from slicepoint_schemas.checks import CheckStatus
from slicepoint_schemas.legacy import (
    SCAN_KEYS,
    CompareResponseV1,
    DiceMetricsV0,
    DiceSummaryV0,
    EmptyObject,
    MonthlySummaryV0,
    SlicePointFileV0,
    legacy_verdict_to_outcome,
    slicepoint_file_to_check_results,
    slicepoint_file_to_verdict,
)
from slicepoint_schemas.verdict import VerdictOutcome


def test_six_samples_present() -> None:
    assert len(SAMPLE_FILES) == 6


def test_sample_validates_and_round_trips(sample_raw: dict[str, Any]) -> None:
    model = SlicePointFileV0.model_validate(sample_raw)
    assert model.to_legacy_dict() == sample_raw
    # and once more through JSON text
    again = SlicePointFileV0.model_validate_json(model.model_dump_json(by_alias=True))
    assert again == model


def test_scan_key_order_is_enforced(hospital_b_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(hospital_b_raw)
    scan = raw["scans"][0]
    raw["scans"][0] = {k: scan[k] for k in reversed(SCAN_KEYS)}
    with pytest.raises(ValidationError, match="scan keys"):
        SlicePointFileV0.model_validate(raw)


def test_scan_extra_key_rejected(hospital_b_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(hospital_b_raw)
    raw["scans"][0]["extra"] = 1
    with pytest.raises(ValidationError):
        SlicePointFileV0.model_validate(raw)


def test_ai_no_answer_must_be_null_together(hospital_b_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(hospital_b_raw)
    raw["scans"][0]["aiAaa"] = None  # aiDiameterMm still set
    with pytest.raises(ValidationError, match="aiAaa must be null"):
        SlicePointFileV0.model_validate(raw)


def test_wrong_file_type_rejected(hospital_b_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(hospital_b_raw)
    raw["fileType"] = "something_else"
    with pytest.raises(ValidationError):
        SlicePointFileV0.model_validate(raw)


def test_duplicate_finding_rejected(hospital_b_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(hospital_b_raw)
    raw["findings"].append(dict(raw["findings"][0]))
    with pytest.raises(ValidationError, match="one finding per check"):
        SlicePointFileV0.model_validate(raw)


def test_dice_block_optional_and_omitted_on_dump(hospital_b_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(hospital_b_raw)
    del raw["dice"]
    model = SlicePointFileV0.model_validate(raw)
    assert model.dice is None
    assert model.to_legacy_dict() == raw


def test_performance_dice_may_be_empty(hospital_b_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(hospital_b_raw)
    raw["performance"]["dice"] = {}
    model = SlicePointFileV0.model_validate(raw)
    assert isinstance(model.performance.dice, EmptyObject)
    assert model.to_legacy_dict() == raw


def test_dice_keys_with_dots_use_aliases(hospital_b_raw: dict[str, Any]) -> None:
    model = SlicePointFileV0.model_validate(hospital_b_raw)
    assert isinstance(model.performance.dice, DiceMetricsV0)
    assert model.performance.dice.share_below_0_90 == hospital_b_raw["performance"]["dice"]["share_below_0.90"]


def test_file_level_counts_tie_to_scans(hospital_b_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(hospital_b_raw)
    raw["scans"] = raw["scans"][:-1]
    with pytest.raises(ValidationError, match="number of scans"):
        SlicePointFileV0.model_validate(raw)


def test_site_id_from_hospital_name(hospital_b_raw: dict[str, Any]) -> None:
    assert SlicePointFileV0.model_validate(hospital_b_raw).site_id == "hospital_b"


# --------------------------------------------------------------------------- converters

EXPECTED_STATUSES = {
    "hospital_b": {"repeats": "problem", "labels": "ok", "scanning": "watch", "accuracy": "problem"},
    "hospital_d": {"repeats": "ok", "labels": "ok", "scanning": "problem", "accuracy": "watch", "patients": "problem"},
}


@pytest.mark.parametrize("site", sorted(EXPECTED_STATUSES))
def test_findings_convert_to_check_results(site: str) -> None:
    from conftest import SAMPLE_DIR, load_json

    model = SlicePointFileV0.model_validate(load_json(SAMPLE_DIR / f"{site}_slicepoint.json"))
    results = slicepoint_file_to_check_results(model)
    assert {r.check_id: r.status.value for r in results} == EXPECTED_STATUSES[site]
    for r in results:
        assert r.n == 80
        assert r.score is None and r.score_method is None
        assert r.source == "legacy_v0"


def test_legacy_verdicts(sample_raw: dict[str, Any]) -> None:
    model = SlicePointFileV0.model_validate(sample_raw)
    verdict = slicepoint_file_to_verdict(model)
    statuses = {f.status for f in model.findings}
    if "Problem" in statuses:
        assert verdict.outcome is VerdictOutcome.NO_GO
    else:
        assert verdict.outcome is VerdictOutcome.BORDERLINE
    missing = {"repeats", "scanning", "patients", "labels", "accuracy"} - {f.check for f in model.findings}
    assert set(verdict.not_evaluated) == missing


def test_legacy_status_and_verdict_maps() -> None:
    assert CheckStatus.from_legacy("Watch") is CheckStatus.WATCH
    assert CheckStatus.from_severity("red") is CheckStatus.PROBLEM
    assert CheckStatus.from_trigger("n/a") is None
    with pytest.raises(ValueError):
        CheckStatus.from_severity("info")
    with pytest.raises(ValueError):
        CheckStatus.from_legacy("ok")
    assert legacy_verdict_to_outcome("REVIEW NEEDED") is VerdictOutcome.NO_GO
    assert legacy_verdict_to_outcome("Proceed with care") is VerdictOutcome.BORDERLINE
    assert legacy_verdict_to_outcome("Comparable to validation") is VerdictOutcome.GO
    with pytest.raises(ValueError):
        legacy_verdict_to_outcome("maybe")


# --------------------------------------------------------------------------- monthly summary


def _month(month: str, red: list[str], yellow: list[str], verdict: str) -> dict[str, Any]:
    return {
        "month": month, "n_scans": 40, "labels": True, "red": len(red), "yellow": len(yellow),
        "green": 10, "verdict": verdict, "red_triggers": red, "yellow_triggers": yellow,
    }


def _monthly() -> dict[str, Any]:
    return {
        "hospital": "demo_hospital", "reference": "hospital_a", "scenario": "drift",
        "first_month_with_a_red_alert": "2026-03", "history_file": "monitoring/history.csv",
        "months": [
            _month("2026-01", [], [], "Comparable to validation"),
            _month("2026-02", [], ["Age mix"], "Proceed with care"),
            _month("2026-03", ["No-answer rate"], ["Age mix"], "Review needed"),
        ],
    }


def test_monthly_summary_valid() -> None:
    m = MonthlySummaryV0.model_validate(_monthly())
    assert m.model_dump(mode="json") == _monthly()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(first_month_with_a_red_alert="2026-02"),
        lambda d: d["months"][1].update(verdict="Comparable to validation"),
        lambda d: d["months"][2].update(red=2),
        lambda d: d["months"].reverse(),
        lambda d: d["months"][0].update(month="2026-13"),
    ],
)
def test_monthly_summary_invariants(mutate: Any) -> None:
    d = _monthly()
    mutate(d)
    with pytest.raises(ValidationError):
        MonthlySummaryV0.model_validate(d)


# --------------------------------------------------------------------------- dice.json (inferred)


def test_dice_summary_inferred_shape() -> None:
    assert DiceSummaryV0.model_validate({"average": 0.97}).median is None
    d = DiceSummaryV0.model_validate({"average": 0.97, "share_below_0.90": 0.05})
    assert d.share_below_0_90 == 0.05
    with pytest.raises(ValidationError):
        DiceSummaryV0.model_validate({"average": 1.2})


# --------------------------------------------------------------------------- /v1/compare


def _compare(dice: float = 0.95, status: str = "high_agreement", priority: str = "low") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "comparison_type": "model_vs_vendor_mask_agreement",
        "metrics": {
            "dice": dice, "iou": dice / (2 - dice), "prediction_volume_ml": 120.5,
            "reference_volume_ml": 118.0, "hd95_mm": 2.1, "empty_prediction": False,
            "empty_reference": False, "hd95_status": "ok",
        },
        "assessment": {
            "status": status, "review_priority": priority, "message": "m",
            "dice_percent": round(dice * 100, 2), "clinical_correctness_established": False,
            "interpretation": "i",
            "thresholds": {"high_agreement": "> 0.9", "review_with_caution": "0.7 through 0.9",
                           "low_agreement": "< 0.7"},
        },
        "model": {
            "model": "TotalSegmentator", "version": "2.11.0", "task": "total", "roi": "aorta",
            "fast": True, "device": "gpu", "elapsed_seconds": 12.3,
            "input_sha256": "a" * 64, "mask_sha256": "b" * 64,
        },
        "display": {"plane": "axial", "canonical_slice_index": 42, "selection": "s",
                    "ct_window_hu": [-150, 300], "score_dimension": "3D"},
        "limitation": "l",
        "image": {"media_type": "image/png", "data_url": "data:image/png;base64,AAAA"},
    }


def test_compare_response_valid() -> None:
    CompareResponseV1.model_validate(_compare())
    CompareResponseV1.model_validate(_compare(0.8, "review_with_caution", "medium"))


@pytest.mark.parametrize(
    "payload",
    [
        _compare(0.95, "low_agreement", "high"),  # status contradicts dice
        _compare(0.95, "high_agreement", "high"),  # priority contradicts status
        {**_compare(), "assessment": {**_compare()["assessment"], "clinical_correctness_established": True}},
        {**_compare(), "metrics": {**_compare()["metrics"], "dice": 1.2}},
        {**_compare(), "metrics": {**_compare()["metrics"], "hd95_status": "sheared_grid"}},
    ],
)
def test_compare_response_invariants(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CompareResponseV1.model_validate(payload)
