from __future__ import annotations

from pathlib import Path

import pytest

import numpy as np
from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE, CheckDescriptor, CheckStatus
from slicepoint_schemas.assessment import CheckRunState, StepState
from slicepoint_schemas.checks import SubFactor
from slicepoint_schemas.thresholds import TriggerThreshold, Worse

from conftest import FIXED_NOW, load_site, needs_data
from slicepoint_core import Assessment, CheckSpec, ReferenceProfile, TabularDataset, default_registry
from slicepoint_core.checks import CheckContext, CheckOutput, Finding, Requirement, Severity

pytestmark = needs_data


def _without(site: TabularDataset, *, labels: bool = True, embeddings: bool = True) -> TabularDataset:
    frame = site.frame if labels else site.frame.drop(columns=["max_aortic_diameter_mm", "aaa", "aaa_size_class"])
    return TabularDataset(
        site_id=site.site_id, frame=frame,
        embeddings=site.embeddings if embeddings else None, space=site.space if embeddings else None,
        has_labels=labels,
    )


def test_registry_has_the_five_checks_in_order() -> None:
    reg = default_registry()
    assert [s.id for s in reg] == ["repeats", "scanning", "patients", "labels", "accuracy"]
    assert {c.id for c in reg.schema_registry().checks} == set(HACKATHON_DEFAULT_PROFILE.check_targets)


def test_results_carry_n_subjects_n_effective_and_score(reports: dict[str, object]) -> None:
    from slicepoint_core import AssessmentReport

    rep = reports["hospital_b"]
    assert isinstance(rep, AssessmentReport)
    for r in rep.checks.values():
        assert r.n == 80 and r.subjects == 40
        assert r.n_effective == 32.0 and r.n_effective_method == "kish_design_effect_per_person"
        assert r.score_method == "provisional-v0" and r.score is not None
    assert rep.checks["repeats"].score == 50.0  # 40 people / 80 scans
    assert rep.checks["repeats"].failing_sub_factors == ("people", "leakage")


def test_every_failing_notebook_rule_names_a_sub_factor(reports: dict[str, object]) -> None:
    """Reviewer decision 1: the registry now has a sub-factor for each notebook rule."""
    from slicepoint_core import AssessmentReport

    expected = {
        ("hospital_b", "accuracy"): {"no_answers", "subgroups", "size_within_tolerance", "dice"},
        ("hospital_b", "scanning"): {"scanner_vendor"},
        ("hospital_c", "scanning"): {"contrast_phase", "slice_thickness_class", "hu_shift", "domain_auc"},
        ("hospital_c", "accuracy"): {"size_within_tolerance", "subgroups"},
        ("hospital_d", "scanning"): {"contrast_phase", "hu_shift", "kvp_shift"},
        ("hospital_d", "patients"): {"sex", "age_band", "aaa_size_class", "labelled_diameter_shift",
                                     "predicted_diameter_shift"},
        # Milestone 2: e's patients card was "watch" with nothing named; the diameter shifts now name it.
        ("hospital_e", "patients"): {"labelled_diameter_shift", "predicted_diameter_shift"},
        ("hospital_e", "accuracy"): {"aneurysms_caught", "subgroups", "size_within_tolerance"},
    }
    for (site, check), subs in expected.items():
        rep = reports[site]
        assert isinstance(rep, AssessmentReport)
        assert set(rep.checks[check].failing_sub_factors) == subs, (site, check)
    # Milestone 2 closed the last gap: no failing factor is evidence-only any more.
    for rep in reports.values():
        assert isinstance(rep, AssessmentReport)
        for r in rep.checks.values():
            unmapped = {e.value for e in r.evidence if e.key == "failing_factor_without_sub_factor"}
            assert unmapped == set(), (r.check_id, unmapped)


def test_aaa_size_class_mix_alert(reports: dict[str, object], reference: ReferenceProfile) -> None:
    """Reviewer decision 4 (new vs POC): TVD alert on the AAA size-class mix."""
    from slicepoint_core import AssessmentReport

    d = reports["hospital_d"]
    assert isinstance(d, AssessmentReport)
    f = next(f for f in d.findings["patients"] if f.factor == "tvd_aaa_size_class")
    assert f.severity is Severity.YELLOW and f.evidence["distance"] == pytest.approx(0.16)
    for site in ("hospital_b", "hospital_c", "hospital_e"):
        rep = reports[site]
        assert isinstance(rep, AssessmentReport)
        assert not any(f.factor == "tvd_aaa_size_class" for f in rep.findings["patients"])
    triggers = dict(HACKATHON_DEFAULT_PROFILE.triggers)
    triggers["AAA size class mix"] = TriggerThreshold(yellow=0.05, red=0.10, worse=Worse.HIGH)
    strict = HACKATHON_DEFAULT_PROFILE.model_copy(update={"triggers": triggers})
    rep = Assessment(load_site("hospital_d"), reference, strict, now=FIXED_NOW).run()
    f = next(f for f in rep.findings["patients"] if f.factor == "tvd_aaa_size_class")
    assert f.severity is Severity.RED


def test_missing_labels_skip_labels_and_accuracy(reference: ReferenceProfile) -> None:
    rep = Assessment(_without(load_site("hospital_d"), labels=False), reference, now=FIXED_NOW).run()
    runs = {c.check_id: c for c in rep.result.checks}
    assert runs["labels"].state is CheckRunState.SKIPPED and "labels" in (runs["labels"].reason or "")
    assert runs["accuracy"].state is CheckRunState.SKIPPED
    assert set(rep.verdict.not_evaluated) == {"labels", "accuracy"}
    assert rep.verdict.outcome.value != "go"
    assert rep.performance.aaa_missing_as_wrong is None
    patients = rep.checks["patients"]
    assert any(e.key == "not_evaluated" and e.value == "prevalence" for e in patients.evidence)
    steps = {s.step: s.state for s in rep.result.steps}
    assert steps["check_labels"] is StepState.SKIPPED and steps["performance"] is StepState.SKIPPED


def test_missing_embeddings_skip_repeats_and_mark_scan_content(reference: ReferenceProfile) -> None:
    rep = Assessment(_without(load_site("hospital_c"), embeddings=False), reference, now=FIXED_NOW).run()
    runs = {c.check_id: c.state for c in rep.result.checks}
    assert runs["repeats"] is CheckRunState.SKIPPED
    assert "repeats" in rep.verdict.not_evaluated
    scanning = rep.checks["scanning"]
    assert {e.value for e in scanning.evidence if e.key == "not_evaluated"} >= {"scan_content", "embedding_shortcuts"}
    assert scanning.status is CheckStatus.PROBLEM  # the category mixes still fail without embeddings


def test_thresholds_come_from_the_profile(reference: ReferenceProfile) -> None:
    site = load_site("hospital_b")
    base = Assessment(site, reference, now=FIXED_NOW).run()
    assert base.checks["scanning"].status is CheckStatus.WATCH
    triggers = dict(HACKATHON_DEFAULT_PROFILE.triggers)
    triggers["Scanner brand mix"] = TriggerThreshold(yellow=0.50, red=0.60, worse=Worse.HIGH)
    lenient = HACKATHON_DEFAULT_PROFILE.model_copy(update={"triggers": triggers, "profile_id": "lenient"})
    rep = Assessment(site, reference, lenient, now=FIXED_NOW).run()
    assert rep.checks["scanning"].status is CheckStatus.OK
    assert rep.result.profile_id == "lenient"


def test_a_sixth_check_is_one_function_plus_data(reference: ReferenceProfile) -> None:
    def kvp_known(ctx: CheckContext) -> CheckOutput:
        missing = int(ctx.frame["kvp"].isna().sum())
        sev = Severity.YELLOW if missing else Severity.OK
        return CheckOutput(findings=[Finding("kvp_missing", sev, f"{missing} scans lack kVp.", "Data quality")],
                           score=100.0 * (1 - missing / ctx.n))

    reg = default_registry()
    reg.register(CheckSpec(
        descriptor=CheckDescriptor(id="metadata", title="Metadata complete", definition="Share of scans with kVp.",
                                   sub_factors=(SubFactor(id="kvp", title="kVp"),)),
        run=kvp_known, sub_factor_of={"kvp_missing": "kvp"},
    ))
    rep = Assessment(load_site("hospital_b"), reference, registry=reg, now=FIXED_NOW).run()
    r = rep.checks["metadata"]
    assert r.status is CheckStatus.WATCH and r.failing_sub_factors == ("kvp",)
    from slicepoint_schemas import AssessmentResult

    again = AssessmentResult.model_validate_json(rep.to_json(), context=reg.validation_context())
    assert again.verdict.results[-1].check_id == "metadata"
    assert again.verdict.results[-1].score is None  # stripped by default, also for a sixth check


def test_failing_check_is_recorded_not_hidden(reference: ReferenceProfile) -> None:
    def boom(ctx: CheckContext) -> CheckOutput:
        raise RuntimeError("kaboom")

    reg = default_registry()
    reg.register(CheckSpec(descriptor=CheckDescriptor(id="flaky", title="Flaky", definition="Always fails."), run=boom,
                           requires=frozenset({Requirement.LABELS})))
    rep = Assessment(load_site("hospital_e"), reference, registry=reg, now=FIXED_NOW).run()
    run = next(c for c in rep.result.checks if c.check_id == "flaky")
    assert run.state is CheckRunState.FAILED and "kaboom" in (run.reason or "")
    assert "flaky" not in rep.checks


def test_ok_check_has_no_failing_sub_factors(reports: dict[str, object]) -> None:
    from slicepoint_core import AssessmentReport

    for rep in reports.values():
        assert isinstance(rep, AssessmentReport)
        for r in rep.checks.values():
            if r.status is CheckStatus.OK:
                assert r.failing_sub_factors == ()


def test_context_people_stats_match_kish(reference: ReferenceProfile) -> None:
    ctx = CheckContext(load_site("hospital_b"), reference, HACKATHON_DEFAULT_PROFILE)
    n, subjects, n_eff = ctx.people_stats()
    sizes = np.bincount(ctx.people.labels)
    sizes = sizes[sizes > 0]
    assert (n, subjects) == (80, 40)
    assert n_eff == sizes.sum() ** 2 / (sizes**2).sum()


def test_assessment_json_round_trips(reports: dict[str, object], tmp_path: Path) -> None:
    from slicepoint_schemas import AssessmentResult

    from slicepoint_core import AssessmentReport

    rep = reports["hospital_d"]
    assert isinstance(rep, AssessmentReport)
    text = rep.to_json(show_provisional_scores=True)
    (tmp_path / "result.json").write_text(text)
    again = AssessmentResult.model_validate_json(text)
    assert again == rep.result
    stripped = AssessmentResult.model_validate_json(rep.to_json())
    assert stripped == rep.export() and stripped.verdict == rep.export().verdict
    assert again.schema_version == "0.1.0" and again.generator.startswith("slicepoint-core")
    assert {s.step for s in again.steps} >= {"ingest", "embed", "load_reference", "segmentation", "verdict"}
    seg = next(s for s in again.steps if s.step == "segmentation")
    assert seg.state is StepState.SKIPPED


def test_provisional_scores_are_stripped_from_json_by_default(reports: dict[str, object]) -> None:
    import json

    from slicepoint_core import AssessmentReport, strip_provisional_scores

    rep = reports["hospital_b"]
    assert isinstance(rep, AssessmentReport)
    assert all(r.score is not None for r in rep.result.verdict.results)  # in memory they still exist
    data = json.loads(rep.to_json())
    for r in data["verdict"]["results"]:
        assert "score" not in r and "score_method" not in r
        keys = [e["key"] for e in r["evidence"]]
        assert "score_basis" not in keys and not [k for k in keys if k.startswith(("score_part.", "score."))]
    assert "provisional-v0" not in rep.to_json()
    kept = json.loads(rep.to_json(show_provisional_scores=True))
    assert all(r["score"] is not None and r["score_method"] == "provisional-v0" for r in kept["verdict"]["results"])
    # the verdict and everything else are untouched
    stripped = strip_provisional_scores(rep.result)
    assert stripped.verdict.outcome == rep.result.verdict.outcome
    assert stripped.model_dump(exclude={"verdict"}) == rep.result.model_dump(exclude={"verdict"})


# --------------------------------------------------------------------------- domain AUC floor


def _auc_evidence(rep: object) -> tuple[float, float, str]:
    from slicepoint_core import AssessmentReport

    assert isinstance(rep, AssessmentReport)
    ev = {e.key: e for e in rep.checks["scanning"].evidence}
    auc, raw, head = ev["scan_content_auc.auc"].value, ev["scan_content_auc.auc_raw"].value, ev["scan_content_auc"]
    assert isinstance(auc, float) and isinstance(raw, float) and head.text is not None
    return auc, raw, head.text


def test_floor_domain_auc() -> None:
    from slicepoint_core.checks.builtin import floor_domain_auc

    assert floor_domain_auc(0.14) == 0.5 and floor_domain_auc(0.5) == 0.5 and floor_domain_auc(0.85) == 0.85


def test_domain_auc_below_chance_is_floored_and_raw_kept(reports: dict[str, object]) -> None:
    """hospital_b and hospital_e cross-validate below 0.5 against hospital_a: noise, not separation."""
    for site in ("hospital_b", "hospital_e"):
        auc, raw, text = _auc_evidence(reports[site])
        assert raw < 0.5 and auc == 0.5, site
        assert "no better than chance" in text and "at or below chance" in text and "AUC 0.50" in text
        assert "domain_auc" not in reports[site].checks["scanning"].failing_sub_factors  # type: ignore[attr-defined]


def test_domain_auc_above_chance_is_unchanged(reports: dict[str, object]) -> None:
    auc, raw, text = _auc_evidence(reports["hospital_c"])
    assert auc == raw > 0.8 and "systematically different" in text


def test_domain_auc_floor_is_applied_before_classifying(
    reference: ReferenceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Classification uses the floored value: with a (hypothetical) yellow line at 0.5,
    a raw 0.30 is classified as 0.5, i.e. watch, not ok."""
    from slicepoint_core import stats

    monkeypatch.setattr(stats, "domain_auc", lambda *a, **k: 0.30)
    triggers = dict(HACKATHON_DEFAULT_PROFILE.triggers)
    triggers["scanning_domain_auc"] = TriggerThreshold(yellow=0.5, red=0.8, worse=Worse.HIGH, inclusive=True)
    profile = HACKATHON_DEFAULT_PROFILE.model_copy(update={"triggers": triggers})
    rep = Assessment(load_site("hospital_b"), reference, profile, now=FIXED_NOW).run()
    auc, raw, text = _auc_evidence(rep)
    assert (auc, raw) == (0.5, 0.30)
    head = next(e for e in rep.checks["scanning"].evidence if e.key == "scan_content_auc")
    assert head.value == "yellow" and "AUC 0.50" in text
    assert "domain_auc" in rep.checks["scanning"].failing_sub_factors


# --------------------------------------------------------------------------- self-comparison


def test_self_comparison_is_flagged_only_for_the_reference_site(
    reports: dict[str, object], reference: ReferenceProfile
) -> None:
    from slicepoint_core import SELF_COMPARISON_NOTE, AssessmentReport

    own = Assessment(load_site("hospital_a"), reference, HACKATHON_DEFAULT_PROFILE, now=FIXED_NOW).run()
    assert own.result.is_self_comparison
    assert own.result.notes[0] == SELF_COMPARISON_NOTE
    assert own.result.dataset_fingerprint == reference.summary.provenance.dataset_fingerprint
    # The verdict logic is unchanged: hospital_a against itself is borderline (measurement outliers).
    assert own.verdict.outcome.value == "borderline"
    for site, rep in reports.items():
        assert isinstance(rep, AssessmentReport)
        assert not rep.result.is_self_comparison, site
        assert SELF_COMPARISON_NOTE not in rep.result.notes, site


# --------------------------------------------------------------------------- embedded descriptors


def test_result_embeds_the_registry_it_used(reports: dict[str, object], reference: ReferenceProfile) -> None:
    from slicepoint_schemas import DEFAULT_CHECK_REGISTRY, AssessmentResult

    from slicepoint_core import AssessmentReport

    rep = reports["hospital_b"]
    assert isinstance(rep, AssessmentReport)
    assert rep.result.check_descriptors == DEFAULT_CHECK_REGISTRY.checks
    assert rep.export().check_descriptors == DEFAULT_CHECK_REGISTRY.checks  # not stripped with the scores
    assert AssessmentResult.model_validate_json(rep.to_json()).check_descriptors == DEFAULT_CHECK_REGISTRY.checks

    reg = default_registry()
    extra = CheckDescriptor(id="metadata", title="Metadata complete", definition="Share of scans with kVp.")
    reg.register(CheckSpec(descriptor=extra, run=lambda ctx: CheckOutput(findings=[])))
    custom = Assessment(load_site("hospital_b"), reference, registry=reg, now=FIXED_NOW).run()
    assert custom.result.check_descriptors is not None
    assert [d.id for d in custom.result.check_descriptors] == [s.id for s in reg]
    assert custom.result.check_descriptors[-1] == extra
