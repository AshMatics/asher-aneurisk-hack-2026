"""(c) Invariants, each with a negative test."""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any

import pytest
from pydantic import ValidationError

from conftest import SAMPLE_FILES, load_json
from slicepoint_schemas.checks import (
    CHECK_REGISTRY_CONTEXT_KEY,
    DEFAULT_CHECK_REGISTRY,
    CheckDescriptor,
    CheckRegistry,
    CheckResult,
    CheckStatus,
)
from slicepoint_schemas.common import SCHEMA_VERSION, Modality, short_case_id
from slicepoint_schemas.embedding import (
    HACKATHON_MERLIN_CT_SPACE,
    CaseEmbedding,
    EmbeddingComparisonRequest,
    EmbeddingSet,
    EmbeddingSpace,
    IncomparableEmbeddingSpacesError,
    assert_comparable,
    case_embedding_from_wide_row,
)
from slicepoint_schemas.ingestion import (
    DECLARED_ADAPTERS,
    CuratedDataset,
    FeatureRow,
    IngestionAdapter,
    PredictionRow,
)
from slicepoint_schemas.legacy import SCAN_KEYS, BinMetricsV0, DiameterMetricsV0, DiceMetricsV0, ScanV0
from slicepoint_schemas.thresholds import (
    HACKATHON_DEFAULT_PROFILE,
    AaaRules,
    DiceMarkers,
    ThresholdProfile,
    TriggerThreshold,
    Worse,
)
from slicepoint_schemas.verdict import (
    OVERRIDE_NOTE_MIN_CHARS,
    Verdict,
    VerdictOutcome,
    VerdictOverride,
    derive_verdict,
)

CASE = "0123456789abcdef"
CASE2 = "fedcba9876543210"

# --------------------------------------------------------------------------- BinMetrics


def _bins() -> list[dict[str, Any]]:
    out = []
    for path in SAMPLE_FILES:
        perf = load_json(path)["performance"]
        out += [perf["aaa_missing_as_wrong"], perf["aaa_when_answered"]]
    return out


@pytest.mark.parametrize("raw", _bins())
def test_bin_metrics_samples_satisfy_arithmetic(raw: dict[str, Any]) -> None:
    m = BinMetricsV0.model_validate(raw)
    assert m.tp + m.fn == m.n_aaa and m.tn + m.fp == m.n_not_aaa and m.n_aaa + m.n_not_aaa == m.n


BASE_BIN = load_json(SAMPLE_FILES[0])["performance"]["aaa_missing_as_wrong"]


@pytest.mark.parametrize(
    "patch, match",
    [
        ({"tp": BASE_BIN["tp"] + 1}, "tp \\+ fn"),
        ({"tn": BASE_BIN["tn"] - 1}, "tn \\+ fp"),
        ({"n": BASE_BIN["n"] + 1}, "n_aaa \\+ n_not_aaa"),
        ({"n_no_answer": BASE_BIN["fn"] + BASE_BIN["fp"] + 1}, "n_no_answer"),
        ({"sens_lo": 0.9, "sens_hi": 0.95}, "Wilson"),  # point 0.857 below lo
        ({"sens_hi": 0.5}, "Wilson"),
        ({"sens": 0.5}, "must equal"),
        ({"bal_acc": 0.5}, "bal_acc"),
        ({"g_mean": None}, "null exactly"),
        ({"spec_hi": 1.2}, "less than or equal"),
    ],
)
def test_bin_metrics_negative(patch: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        BinMetricsV0.model_validate({**BASE_BIN, **patch})


def test_bin_metrics_zero_denominator_requires_nulls() -> None:
    raw = {
        "n": 5, "n_aaa": 0, "n_not_aaa": 5, "tp": 0, "fn": 0, "tn": 5, "fp": 0, "n_no_answer": 0,
        "sens": None, "sens_lo": None, "sens_hi": None, "spec": 1.0, "spec_lo": 0.56, "spec_hi": 1.0,
        "bal_acc": None, "g_mean": None,
    }
    BinMetricsV0.model_validate(raw)
    with pytest.raises(ValidationError, match="denominator is 0"):
        BinMetricsV0.model_validate({**raw, "sens": 0.0})


def test_performance_modes_must_agree() -> None:
    from slicepoint_schemas.legacy import PerformanceV0

    perf = copy.deepcopy(load_json(SAMPLE_FILES[0])["performance"])
    PerformanceV0.model_validate(perf)
    perf["aaa_when_answered"]["n_no_answer"] = 1
    perf["aaa_when_answered"]["fp"] += 0
    with pytest.raises(ValidationError):
        PerformanceV0.model_validate(perf)


# --------------------------------------------------------------------------- diameter / Dice


def test_diameter_small_n_all_null() -> None:
    nulls = dict.fromkeys(["mae", "rmse", "bias", "loa_low", "loa_high", "within_2mm", "within_3mm", "spearman"])
    DiameterMetricsV0.model_validate({"n": 2, **nulls})
    with pytest.raises(ValidationError, match="n < 3"):
        DiameterMetricsV0.model_validate({"n": 2, **nulls, "mae": 1.0})


def test_diameter_ordering() -> None:
    base = load_json(SAMPLE_FILES[0])["performance"]["diameter"]
    with pytest.raises(ValidationError, match="within_2mm"):
        DiameterMetricsV0.model_validate({**base, "within_2mm": 0.99, "within_3mm": 0.5})
    with pytest.raises(ValidationError, match="limits of agreement"):
        DiameterMetricsV0.model_validate({**base, "bias": 10.0})
    with pytest.raises(ValidationError, match="rmse"):
        DiameterMetricsV0.model_validate({**base, "rmse": 0.1})


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_dice_in_unit_interval(bad: float) -> None:
    ok = {"median": 0.98, "mean": 0.97, "share_below_0.90": 0.05, "share_below_0.85": 0.01}
    DiceMetricsV0.model_validate(ok)
    with pytest.raises(ValidationError):
        DiceMetricsV0.model_validate({**ok, "mean": bad})
    with pytest.raises(ValidationError):
        PredictionRow(case_id=CASE, pred_aorta_dice=bad, pred_max_diameter_mm=20.0, pred_aaa=False)


def test_dice_share_nesting() -> None:
    with pytest.raises(ValidationError, match="0.85"):
        DiceMetricsV0.model_validate({"median": 0.9, "mean": 0.9, "share_below_0.90": 0.01, "share_below_0.85": 0.2})


# --------------------------------------------------------------------------- predictions


def test_pred_null_together() -> None:
    PredictionRow(case_id=CASE, pred_aorta_dice=0.9, pred_max_diameter_mm=None, pred_aaa=None)
    with pytest.raises(ValidationError, match="null if and only if"):
        PredictionRow(case_id=CASE, pred_aorta_dice=0.9, pred_max_diameter_mm=None, pred_aaa=False)
    with pytest.raises(ValidationError, match="null if and only if"):
        PredictionRow(case_id=CASE, pred_aorta_dice=0.9, pred_max_diameter_mm=31.0, pred_aaa=None)


def test_pred_aaa_is_strict_bool() -> None:
    with pytest.raises(ValidationError):
        PredictionRow.model_validate({"case_id": CASE, "pred_aorta_dice": 0.9, "pred_max_diameter_mm": 31.0, "pred_aaa": 1})


# --------------------------------------------------------------------------- identifiers


def _feature(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "case_id": CASE, "patient_id": CASE2, "age_band": "60-69", "sex": "M", "scanner_vendor": None,
        "contrast_phase": "venous", "slice_thickness_mm": 1.0, "slice_thickness_class": "thin", "kvp": None,
        "study_description": "CTA Abdomen/Pelvis", "protocol_name": "p", "aorta_hu_mean": 300.0,
        "aorta_hu_sd": 30.0, "organ_volumes_liver": 0.0, "organ_volumes_spleen": 0.0,
        "organ_volumes_kidney_left": 0.0, "organ_volumes_kidney_right": 0.0,
    }
    base.update(kw)
    return base


def test_feature_row_identifiers() -> None:
    FeatureRow.model_validate(_feature(age_band="10-19"))
    bads: list[dict[str, Any]] = [{"age_band": "60-70"}, {"age_band": "6-9"}, {"case_id": ""}, {"case_id": " x"},
                {"case_id": "x" * 129}, {"sex": ""}, {"scanner_vendor": " "}, {"contrast_phase": "delayed"},
                {"unexpected": 1}]
    for bad in bads:
        with pytest.raises(ValidationError):
            FeatureRow.model_validate(_feature(**bad))


def test_short_case_id() -> None:
    assert short_case_id(CASE) == "01234567"
    with pytest.raises(ValueError):
        short_case_id("xyz")


def test_models_are_frozen() -> None:
    row = PredictionRow(case_id=CASE, pred_aorta_dice=0.9, pred_max_diameter_mm=None, pred_aaa=None)
    with pytest.raises(ValidationError):
        row.pred_aorta_dice = 0.1  # type: ignore[misc]


# --------------------------------------------------------------------------- embeddings


def _space(space_id: str = "test-space", dim: int = 3) -> EmbeddingSpace:
    return EmbeddingSpace(space_id=space_id, encoder_name="enc", modality=Modality.CT, dim=dim)


def _set(space: EmbeddingSpace, *vectors: tuple[float, ...]) -> EmbeddingSet:
    ids = [CASE, CASE2]
    return EmbeddingSet(space=space, embeddings=tuple(CaseEmbedding(case_id=ids[i], vector=v) for i, v in enumerate(vectors)))


def test_embedding_dim_mismatch_rejected() -> None:
    _set(_space(), (1.0, 2.0, 3.0))
    with pytest.raises(ValidationError, match="dim 3"):
        _set(_space(), (1.0, 2.0))


def test_embedding_duplicate_case_rejected() -> None:
    e = CaseEmbedding(case_id=CASE, vector=(1.0, 2.0, 3.0))
    with pytest.raises(ValidationError, match="duplicate"):
        EmbeddingSet(space=_space(), embeddings=(e, e))


def test_cross_space_comparison_rejected() -> None:
    a = _set(_space("space-a"), (1.0, 2.0, 3.0))
    b = _set(_space("space-b"), (1.0, 2.0, 3.0))
    assert_comparable(a, _set(_space("space-a"), (0.0, 0.0, 0.0)))
    with pytest.raises(IncomparableEmbeddingSpacesError):
        assert_comparable(a, b)
    with pytest.raises(IncomparableEmbeddingSpacesError):
        a.require_comparable(b)
    with pytest.raises(ValidationError, match="embedding spaces differ"):
        EmbeddingComparisonRequest(reference=a, candidate=b)
    # same id, different definition
    c = _set(_space("space-a", dim=2), (1.0, 2.0))
    with pytest.raises(IncomparableEmbeddingSpacesError, match="inconsistently"):
        assert_comparable(a, c)


def test_wide_row_conversion() -> None:
    row: dict[str, object] = {"case_id": CASE, "emb_0": 1.0, "emb_1": 2.0}
    assert case_embedding_from_wide_row(row, dim=2).vector == (1.0, 2.0)
    with pytest.raises(ValueError, match="missing"):
        case_embedding_from_wide_row(row, dim=3)


def test_hackathon_space_is_documented_unknown() -> None:
    assert HACKATHON_MERLIN_CT_SPACE.dim == 2048
    assert HACKATHON_MERLIN_CT_SPACE.encoder_version is None
    assert HACKATHON_MERLIN_CT_SPACE.schema_version == SCHEMA_VERSION


def test_schema_version_literal() -> None:
    with pytest.raises(ValidationError):
        EmbeddingSpace.model_validate({**_space().model_dump(), "schema_version": "9.9.9"})


# --------------------------------------------------------------------------- dataset joins


def test_dataset_case_sets_must_match() -> None:
    f = FeatureRow.model_validate(_feature())
    p_ok = PredictionRow(case_id=CASE, pred_aorta_dice=0.9, pred_max_diameter_mm=None, pred_aaa=None)
    p_bad = PredictionRow(case_id=CASE2, pred_aorta_dice=0.9, pred_max_diameter_mm=None, pred_aaa=None)
    CuratedDataset(site_id="hospital_x", features=(f,), predictions=(p_ok,))
    with pytest.raises(ValidationError, match="differs from features"):
        CuratedDataset(site_id="hospital_x", features=(f,), predictions=(p_bad,))
    with pytest.raises(ValidationError, match="not unique"):
        CuratedDataset(site_id="hospital_x", features=(f, f), predictions=(p_ok,))
    with pytest.raises(ValidationError):
        CuratedDataset(site_id="Hospital X", features=(f,), predictions=(p_ok,))


def test_declared_adapters_conform_and_refuse_io() -> None:
    for cls in DECLARED_ADAPTERS.values():
        adapter: IngestionAdapter = cls()
        assert isinstance(adapter, IngestionAdapter)
        with pytest.raises(NotImplementedError):
            adapter.load("anything")


# --------------------------------------------------------------------------- thresholds


def test_threshold_ordering() -> None:
    TriggerThreshold(yellow=0.15, red=0.30, worse=Worse.HIGH)
    TriggerThreshold(yellow=0.90, red=0.85, worse=Worse.LOW)
    with pytest.raises(ValidationError, match="worse=high"):
        TriggerThreshold(yellow=0.30, red=0.15, worse=Worse.HIGH)
    with pytest.raises(ValidationError, match="worse=low"):
        TriggerThreshold(yellow=0.85, red=0.90, worse=Worse.LOW)
    with pytest.raises(ValidationError):
        TriggerThreshold(yellow=0.2, red=0.2, worse=Worse.HIGH)


def test_threshold_classify_is_strict_like_monitor() -> None:
    t = TriggerThreshold(yellow=0.02, red=0.04, worse=Worse.HIGH)
    assert t.classify(0.02) is CheckStatus.OK
    assert t.classify(0.03) is CheckStatus.WATCH
    assert t.classify(0.05) is CheckStatus.PROBLEM
    assert t.classify(None) is None
    low = TriggerThreshold(yellow=0.90, red=0.85, worse=Worse.LOW)
    assert low.classify(0.84) is CheckStatus.PROBLEM and low.classify(0.95) is CheckStatus.OK


def test_aaa_rules_and_dice_markers_ordering() -> None:
    with pytest.raises(ValidationError):
        AaaRules(decision_line_mm=55, large_aneurysm_line_mm=30, nearby_window_mm=5,
                 size_tolerance_mm=3, bland_altman_tolerance_mm=2)
    with pytest.raises(ValidationError):
        DiceMarkers(lower=0.9, upper=0.81)


def test_default_profile_values_and_provenance() -> None:
    p = HACKATHON_DEFAULT_PROFILE
    assert p.aaa is not None and p.dice_markers is not None
    assert (p.aaa.decision_line_mm, p.aaa.large_aneurysm_line_mm) == (30.0, 55.0)
    assert (p.aaa.nearby_window_mm, p.aaa.size_tolerance_mm, p.aaa.bland_altman_tolerance_mm) == (5.0, 3.0, 2.0)
    assert (p.dice_markers.lower, p.dice_markers.upper) == (0.81, 0.90)
    assert p.min_group_size == 15
    assert p.check_targets == {"repeats": 90, "scanning": 70, "patients": 70, "labels": 90, "accuracy": 88}
    # every configured number has a cited source
    expected = {f"aaa.{k}" for k in AaaRules.model_fields} | {"dice_markers.lower", "dice_markers.upper",
                "min_group_size"} | {f"check_targets.{k}" for k in p.check_targets} | {f"triggers.{k}" for k in p.triggers} \
        | {f"parameters.{k}" for k in p.parameters}
    assert set(p.value_sources) == expected
    assert "12-14" in (p.provenance.notes or "")


def test_profile_rejects_unknown_paths_and_checks() -> None:
    data = HACKATHON_DEFAULT_PROFILE.model_dump()
    with pytest.raises(ValidationError, match="value_sources"):
        ThresholdProfile.model_validate({**data, "value_sources": {"aaa.nope": "x"}})
    with pytest.raises(ValidationError, match="unknown check_id"):
        ThresholdProfile.model_validate({**data, "check_targets": {"vibes": 50}, "value_sources": {}})
    with pytest.raises(ValidationError, match="0..100"):
        ThresholdProfile.model_validate({**data, "check_targets": {"repeats": 150}, "value_sources": {}})


# --------------------------------------------------------------------------- check results


def test_score_requires_method() -> None:
    CheckResult(check_id="labels", status=CheckStatus.OK, n=80)
    CheckResult(check_id="labels", status=CheckStatus.OK, n=80, score=94.0, score_method="1-conflict_share")
    with pytest.raises(ValidationError, match="score_method"):
        CheckResult(check_id="labels", status=CheckStatus.OK, n=80, score=94.0)
    with pytest.raises(ValidationError, match="without a score"):
        CheckResult(check_id="labels", status=CheckStatus.OK, n=80, score_method="x")
    with pytest.raises(ValidationError):
        CheckResult(check_id="labels", status=CheckStatus.OK, n=80, score=101.0, score_method="x")


def test_n_is_required() -> None:
    with pytest.raises(ValidationError):
        CheckResult.model_validate({"check_id": "labels", "status": "ok"})


def test_unknown_check_id_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown check_id"):
        CheckResult(check_id="vibes", status=CheckStatus.OK, n=1)


def test_sub_factors_validated() -> None:
    CheckResult(check_id="scanning", status=CheckStatus.WATCH, n=80, failing_sub_factors=("contrast_phase",))
    with pytest.raises(ValidationError, match="unknown sub-factors"):
        CheckResult(check_id="scanning", status=CheckStatus.WATCH, n=80, failing_sub_factors=("sex",))
    with pytest.raises(ValidationError, match="ok check"):
        CheckResult(check_id="scanning", status=CheckStatus.OK, n=80, failing_sub_factors=("contrast_phase",))


def test_adding_a_check_is_data_only() -> None:
    extra = CheckDescriptor(id="calibration", title="Calibration", definition="Predicted vs observed rate.")
    registry = CheckRegistry(checks=(*DEFAULT_CHECK_REGISTRY.checks, extra))
    payload = {"check_id": "calibration", "status": "watch", "n": 50}
    with pytest.raises(ValidationError):
        CheckResult.model_validate(payload)
    r = CheckResult.model_validate(payload, context={CHECK_REGISTRY_CONTEXT_KEY: registry})
    assert r.check_id == "calibration"
    with pytest.raises(ValidationError, match="duplicate"):
        CheckRegistry(checks=(extra, extra))


def test_registry_has_five_checks() -> None:
    reg = DEFAULT_CHECK_REGISTRY.as_mapping()
    assert set(reg) == {"repeats", "scanning", "patients", "labels", "accuracy"}
    assert {k: v.target for k, v in reg.items()} == HACKATHON_DEFAULT_PROFILE.check_targets


# --------------------------------------------------------------------------- verdict


def _r(check: str, status: str) -> CheckResult:
    return CheckResult(check_id=check, status=CheckStatus(status), n=80)


ALL_OK = [_r(c, "ok") for c in ("repeats", "scanning", "patients", "labels", "accuracy")]


def test_derive_verdict_rule() -> None:
    p = HACKATHON_DEFAULT_PROFILE
    assert derive_verdict(ALL_OK, p).outcome is VerdictOutcome.GO
    assert derive_verdict([*ALL_OK[:4], _r("accuracy", "watch")], p).outcome is VerdictOutcome.BORDERLINE
    v = derive_verdict([*ALL_OK[:3], _r("labels", "problem"), _r("accuracy", "watch")], p)
    assert v.outcome is VerdictOutcome.NO_GO and "labels" in v.rationale
    missing = derive_verdict(ALL_OK[:4], p)
    assert missing.outcome is VerdictOutcome.BORDERLINE and missing.not_evaluated == ("accuracy",)
    assert derive_verdict([], p).outcome is VerdictOutcome.BORDERLINE


def test_verdict_consistency_enforced() -> None:
    Verdict(outcome=VerdictOutcome.GO, rationale="ok", results=tuple(ALL_OK))
    with pytest.raises(ValidationError, match="every included check"):
        Verdict(outcome=VerdictOutcome.GO, rationale="x", results=(*ALL_OK[:4], _r("accuracy", "watch")))
    with pytest.raises(ValidationError, match="evaluated"):
        Verdict(outcome=VerdictOutcome.GO, rationale="x", results=tuple(ALL_OK[:4]), not_evaluated=("accuracy",))
    with pytest.raises(ValidationError, match="at least one result|at least one check result"):
        Verdict(outcome=VerdictOutcome.GO, rationale="x", results=())
    with pytest.raises(ValidationError, match="problem"):
        Verdict(outcome=VerdictOutcome.NO_GO, rationale="x", results=tuple(ALL_OK))
    with pytest.raises(ValidationError, match="duplicate"):
        Verdict(outcome=VerdictOutcome.BORDERLINE, rationale="x", results=(ALL_OK[0], ALL_OK[0]))
    with pytest.raises(ValidationError, match="both evaluated"):
        Verdict(outcome=VerdictOutcome.BORDERLINE, rationale="x", results=(ALL_OK[0],), not_evaluated=("repeats",))


def test_verdict_round_trips_through_json() -> None:
    v = derive_verdict(ALL_OK, HACKATHON_DEFAULT_PROFILE, site_id="hospital_b")
    assert Verdict.model_validate_json(v.model_dump_json()) == v


# --------------------------------------------------------------------------- open values (new) vs closed (legacy)


def test_new_source_row_open_but_legacy_closed() -> None:
    row = FeatureRow.model_validate(
        _feature(case_id="MRN-000123/series-4", patient_id="pat 42", scanner_vendor="Canon", sex="m")
    )
    assert row.scanner_vendor == "canon"  # lowercased
    assert row.sex == "M"  # known value normalised
    assert row.case_id == "MRN-000123/series-4"
    assert FeatureRow.model_validate(_feature(sex="X")).sex == "X"  # unknown kept
    PredictionRow(case_id="MRN-000123/series-4", pred_aorta_dice=0.9, pred_max_diameter_mm=None, pred_aaa=None)

    legacy_scan: dict[str, Any] = dict(zip(SCAN_KEYS, [
        "01234567", "p0", "M", "60-69", "siemens", "venous", "thin", "none", False, 20.0, 20.5, False,
    ]))
    ScanV0.model_validate(legacy_scan)
    with pytest.raises(ValidationError):
        ScanV0.model_validate({**legacy_scan, "scanner_vendor": "canon"})
    with pytest.raises(ValidationError):
        ScanV0.model_validate({**legacy_scan, "sex": "X"})
    with pytest.raises(ValidationError):
        ScanV0.model_validate({**legacy_scan, "id": "pat 42"})
    with pytest.raises(ValueError):
        short_case_id("MRN-000123/series-4")


# --------------------------------------------------------------------------- effective sample size


def test_effective_sample_size() -> None:
    r = CheckResult(check_id="repeats", status=CheckStatus.PROBLEM, n=80, subjects=40,
                    n_effective=46.5, n_effective_method="kish_design_effect_per_person")
    assert r.n_effective == 46.5
    CheckResult(check_id="repeats", status=CheckStatus.OK, n=80, n_effective=80.0, n_effective_method="cluster_icc")


@pytest.mark.parametrize(
    "kw, match",
    [
        ({"n_effective": 40.0}, "n_effective_method"),
        ({"n_effective_method": "cluster_icc"}, "without n_effective"),
        ({"n_effective": 81.0, "n_effective_method": "cluster_icc"}, "exceed n"),
        ({"n_effective": 0.0, "n_effective_method": "cluster_icc"}, "greater than 0"),
        ({"subjects": 81}, "subjects cannot exceed"),
        ({"subjects": -1}, "greater than or equal"),
    ],
)
def test_effective_sample_size_negative(kw: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        CheckResult.model_validate({"check_id": "repeats", "status": "ok", "n": 80, **kw})


# --------------------------------------------------------------------------- verdict override

NOW = dt.datetime(2026, 11, 9, 14, 0, tzinfo=dt.timezone.utc)
NOTE = "Committee accepted: labels conflict is a known local convention, reviewed by radiology."


def _override(outcome: VerdictOutcome, **kw: Any) -> dict[str, Any]:
    return {"outcome": outcome, "by": "ai-committee", "at": NOW, "note": NOTE, **kw}


def test_override_positive() -> None:
    p = HACKATHON_DEFAULT_PROFILE
    derived = derive_verdict([*ALL_OK[:3], _r("labels", "problem")], p)
    assert derived.outcome is VerdictOutcome.NO_GO and derived.not_evaluated == ("accuracy",)
    # go over a problem and a not-evaluated check: allowed, but only via the record
    v = derived.with_override(VerdictOverride.model_validate(_override(VerdictOutcome.GO)))
    assert v.outcome is VerdictOutcome.NO_GO  # derived outcome unchanged and still consistent
    assert v.final_outcome is VerdictOutcome.GO
    assert derived.final_outcome is VerdictOutcome.NO_GO
    assert Verdict.model_validate_json(v.model_dump_json()) == v
    # downgrade go -> borderline
    go = derive_verdict(ALL_OK, p)
    assert go.with_override(VerdictOverride.model_validate(_override(VerdictOutcome.BORDERLINE))).final_outcome \
        is VerdictOutcome.BORDERLINE


@pytest.mark.parametrize(
    "patch",
    [
        {"note": ""},
        {"note": "   \n\t "},
        {"note": "ok"},
        {"note": " " + "x" * (OVERRIDE_NOTE_MIN_CHARS - 1) + " "},
        {"by": ""},
        {"by": "   "},
        {"at": dt.datetime(2026, 11, 9, 14, 0)},  # naive datetime
    ],
)
def test_override_bad_fields_rejected(patch: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VerdictOverride.model_validate(_override(VerdictOutcome.GO, **patch))


def test_override_note_required() -> None:
    data = _override(VerdictOutcome.GO)
    del data["note"]
    with pytest.raises(ValidationError, match="note"):
        VerdictOverride.model_validate(data)


def test_override_equal_to_derived_rejected() -> None:
    derived = derive_verdict(ALL_OK, HACKATHON_DEFAULT_PROFILE)
    with pytest.raises(ValidationError, match="must differ"):
        derived.with_override(VerdictOverride.model_validate(_override(VerdictOutcome.GO)))


def test_override_does_not_relax_derived_invariants() -> None:
    o = VerdictOverride.model_validate(_override(VerdictOutcome.NO_GO))
    with pytest.raises(ValidationError, match="every included check"):
        Verdict(outcome=VerdictOutcome.GO, rationale="x", results=(_r("labels", "problem"),), override=o)
