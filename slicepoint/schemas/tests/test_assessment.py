"""AssessmentResult: the versioned top-level result payload."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from pydantic import ValidationError

from slicepoint_schemas import (
    HACKATHON_DEFAULT_PROFILE,
    AssessmentResult,
    CheckResult,
    CheckRun,
    CheckRunState,
    CheckStatus,
    StepRecord,
    StepState,
    derive_verdict,
)

NOW = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc)


def _result(**overrides: Any) -> dict[str, Any]:
    results = [
        CheckResult(check_id=c, status=CheckStatus.OK, n=80)
        for c in ("repeats", "scanning", "patients", "labels")
    ]
    verdict = derive_verdict(results, HACKATHON_DEFAULT_PROFILE, site_id="hospital_b")
    base: dict[str, Any] = {
        "site_id": "hospital_b",
        "reference": {"reference_id": "ref-hospital_a", "site_id": "hospital_a", "n_cases": 100},
        "profile_id": HACKATHON_DEFAULT_PROFILE.profile_id,
        "model_id": HACKATHON_DEFAULT_PROFILE.model_id,
        "generated_at": NOW,
        "generator": "test",
        "steps": [{"step": "ingest", "state": "ok"}, {"step": "segmentation", "state": "skipped", "detail": "no worker"}],
        "checks": [
            *({"check_id": r.check_id, "state": "evaluated"} for r in results),
            {"check_id": "accuracy", "state": "skipped", "reason": "no labels"},
        ],
        "verdict": verdict,
        "performance": {},
    }
    base.update(overrides)
    return base


def test_valid_result_round_trips() -> None:
    res = AssessmentResult.model_validate(_result())
    assert res.schema_version == "0.1.0"
    assert res.result_type == "slicepoint.assessment_result"
    assert res.verdict.outcome.value == "borderline"
    assert res.verdict.not_evaluated == ("accuracy",)
    again = AssessmentResult.model_validate_json(res.model_dump_json())
    assert again == res


def test_skipped_step_and_check_need_a_reason() -> None:
    with pytest.raises(ValidationError, match="must say why"):
        StepRecord(step="embed", state=StepState.SKIPPED)
    with pytest.raises(ValidationError, match="must give a reason"):
        CheckRun(check_id="labels", state=CheckRunState.SKIPPED)


def test_evaluated_checks_must_match_verdict() -> None:
    data = _result()
    data["checks"] = [*data["checks"][:3], {"check_id": "labels", "state": "skipped", "reason": "x"},
                      data["checks"][4]]
    with pytest.raises(ValidationError, match="exactly the verdict's results"):
        AssessmentResult.model_validate(data)


def test_not_evaluated_must_be_explained() -> None:
    data = _result()
    data["checks"] = data["checks"][:4]
    with pytest.raises(ValidationError, match="no skipped/failed entry"):
        AssessmentResult.model_validate(data)


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError):
        AssessmentResult.model_validate(_result(generated_at=dt.datetime(2026, 11, 9)))


def test_performance_modes_present_together() -> None:
    from slicepoint_schemas.assessment import PerformanceSummary

    bm = {"n": 2, "n_aaa": 1, "n_not_aaa": 1, "tp": 1, "fn": 0, "tn": 1, "fp": 0, "n_no_answer": 0,
          "sens": 1.0, "sens_lo": 0.2, "sens_hi": 1.0, "spec": 1.0, "spec_lo": 0.2, "spec_hi": 1.0,
          "bal_acc": 1.0, "g_mean": 1.0}
    PerformanceSummary.model_validate({"aaa_missing_as_wrong": bm, "aaa_when_answered": bm})
    with pytest.raises(ValidationError, match="present together"):
        PerformanceSummary.model_validate({"aaa_missing_as_wrong": bm})


def test_duplicate_scan_ids_rejected() -> None:
    scan = {"case_id": "abc", "person_group": "p0"}
    with pytest.raises(ValidationError, match="duplicate case_id"):
        AssessmentResult.model_validate(_result(scans=[scan, scan]))


def _agreement(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "n": 4, "mae": 2.5, "rmse": 3.0, "bias": 2.0, "sd": 5 ** 0.5,
        "loa_low": 2 - 1.96 * 5 ** 0.5, "loa_high": 2 + 1.96 * 5 ** 0.5,
        "within_tolerance": [{"role": "bland_altman", "tolerance_mm": 2.0, "share": 0.5},
                             {"role": "size", "tolerance_mm": 3.0, "share": 0.75}],
        "spearman": None,
    }
    base.update(kw)
    return base


def test_diameter_agreement_profile_driven() -> None:
    from slicepoint_schemas import DiameterAgreement
    from slicepoint_schemas.assessment import ToleranceRole

    d = DiameterAgreement.model_validate(_agreement())
    assert d.share_within(ToleranceRole.SIZE) == 0.75
    # any tolerance, not just 2/3 mm
    DiameterAgreement.model_validate(_agreement(within_tolerance=[{"role": "size", "tolerance_mm": 5.0, "share": 1.0}]))
    with pytest.raises(ValidationError, match="limits of agreement"):
        DiameterAgreement.model_validate(_agreement(loa_low=0.0))
    with pytest.raises(ValidationError, match="wider tolerance"):
        DiameterAgreement.model_validate(_agreement(within_tolerance=[
            {"role": "bland_altman", "tolerance_mm": 2.0, "share": 0.9},
            {"role": "size", "tolerance_mm": 3.0, "share": 0.5}]))
    empty = {"n": 2, "mae": None, "rmse": None, "bias": None, "sd": None, "loa_low": None, "loa_high": None,
             "within_tolerance": [{"role": "size", "tolerance_mm": 3.0, "share": None}], "spearman": None}
    DiameterAgreement.model_validate(empty)
    with pytest.raises(ValidationError, match="must be null"):
        DiameterAgreement.model_validate({**empty, "mae": 1.0})


def test_default_registry_names_every_notebook_rule() -> None:
    from slicepoint_schemas import CHECK_REGISTRY

    subs = {c: {s.id for s in d.sub_factors} for c, d in CHECK_REGISTRY.items()}
    assert "leakage" in subs["repeats"]
    assert {"domain_auc", "coverage", "hu_shift", "kvp_shift"} <= subs["scanning"]
    assert {"no_answers", "specificity", "subgroups"} <= subs["accuracy"]
    assert subs["patients"] == {"sex", "age_band", "aaa_size_class"}
