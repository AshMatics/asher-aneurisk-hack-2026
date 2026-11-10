"""Optional yellow/red lines, inclusive comparisons and named parameters on profiles
(added for slicepoint-core milestone 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE, CheckStatus, ThresholdProfile, TriggerThreshold
from slicepoint_schemas.thresholds import Worse


def test_red_only_and_yellow_only_triggers() -> None:
    red_only = TriggerThreshold(yellow=None, red=0.01, worse=Worse.HIGH)
    assert red_only.classify(0.01) is CheckStatus.OK
    assert red_only.classify(0.011) is CheckStatus.PROBLEM
    yellow_only = TriggerThreshold(yellow=0.90, red=None, worse=Worse.LOW)
    assert yellow_only.classify(0.89) is CheckStatus.WATCH
    assert yellow_only.classify(0.0) is CheckStatus.WATCH
    assert yellow_only.classify(0.95) is CheckStatus.OK
    with pytest.raises(ValidationError, match="yellow line, a red line or both"):
        TriggerThreshold(yellow=None, red=None, worse=Worse.HIGH)


def test_inclusive_comparison() -> None:
    auc = TriggerThreshold(yellow=0.65, red=0.80, worse=Worse.HIGH, inclusive=True)
    assert auc.classify(0.80) is CheckStatus.PROBLEM
    assert auc.classify(0.65) is CheckStatus.WATCH
    assert auc.classify(0.6499) is CheckStatus.OK
    strict = TriggerThreshold(yellow=0.65, red=0.80, worse=Worse.HIGH)
    assert strict.classify(0.80) is CheckStatus.WATCH
    low = TriggerThreshold(yellow=0.05, red=0.01, worse=Worse.LOW, inclusive=True)
    assert low.classify(0.01) is CheckStatus.PROBLEM


def test_crosses_absent_line_is_false() -> None:
    t = TriggerThreshold(yellow=0.05, red=None, worse=Worse.HIGH)
    assert t.crosses(1.0, t.red) is False
    assert t.crosses(1.0, t.yellow) is True


def test_default_profile_has_notebook_rules() -> None:
    p = HACKATHON_DEFAULT_PROFILE
    assert p.triggers["repeats_near_duplicate_share"].red == 0.01
    assert p.triggers["scanning_domain_auc"].inclusive
    assert p.parameters["near_duplicate_similarity"] == 0.95
    assert p.parameters["permutation_count"] == 1000
    # round-trips through JSON
    again = ThresholdProfile.model_validate_json(p.model_dump_json())
    assert again == p


def test_dotted_parameter_keys_rejected() -> None:
    data = HACKATHON_DEFAULT_PROFILE.model_dump()
    with pytest.raises(ValidationError, match="must not contain"):
        ThresholdProfile.model_validate({**data, "parameters": {"a.b": 1.0}, "value_sources": {}})


def test_derive_verdict_accepts_a_custom_registry() -> None:
    from slicepoint_schemas import DEFAULT_CHECK_REGISTRY, CheckDescriptor, CheckRegistry, CheckResult, derive_verdict

    reg = CheckRegistry(checks=(*DEFAULT_CHECK_REGISTRY.checks,
                                CheckDescriptor(id="metadata", title="Metadata", definition="kVp present")))
    ctx = {"check_registry": reg}
    extra = CheckResult.model_validate({"check_id": "metadata", "status": "watch", "n": 5}, context=ctx)
    with pytest.raises(ValidationError, match="unknown check_id"):
        derive_verdict([extra], HACKATHON_DEFAULT_PROFILE)
    v = derive_verdict([extra], HACKATHON_DEFAULT_PROFILE, registry=reg)
    assert v.outcome.value == "borderline" and v.results[0].check_id == "metadata"
