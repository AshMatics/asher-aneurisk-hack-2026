"""PARITY: core with reference hospital_a, against the legacy notebook outputs in
``slicepoint/python_notebooks/hospital_test_output/hospital_{b..e}_slicepoint.json``.

(a) performance numbers (BinMetrics, diameter, Dice) within 1e-9;
(b) each legacy finding's check status equals core's status;
(c) the scans list: every field equal, ``personGroup`` partitions equal up to relabelling.

Sentences are also compared, except where ``PARITY.md`` documents why they differ.
Thresholds are not adjusted to force a match.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from slicepoint_schemas import CheckStatus, SlicePointFileV0

from conftest import PARITY_SITES, load_legacy, needs_data
from slicepoint_core import AssessmentReport, to_slicepoint_v0

pytestmark = [needs_data, pytest.mark.parity]

TOL = 1e-9

# (site, check) -> why the legacy sentence differs from core's. Status still must match.
KNOWN_SENTENCE_DIVERGENCES: dict[tuple[str, str], str] = {
    ("hospital_c", "repeats"): "MLP leakage MAE 5.95 mm rounds to 5.9 on the POC machine and 6.0 here (BLAS numerics)",
    ("hospital_c", "accuracy"): "outlier threshold printed as 4.2 mm (population SD) instead of 4.3 mm (sample SD)",
    ("hospital_d", "accuracy"): "outlier threshold printed as 4.2 mm (population SD) instead of 4.3 mm (sample SD)",
}


def _legacy_status(s: str) -> CheckStatus:
    return CheckStatus.from_legacy(s)


def _close(a: Any, b: Any) -> bool:
    if b is None:
        return a is None
    if isinstance(b, (bool, int)):
        return bool(a == b) and type(a) is type(b)
    return a is not None and math.isclose(float(a), float(b), rel_tol=0, abs_tol=TOL)


@pytest.mark.parametrize("site", PARITY_SITES)
def test_a_performance_numbers(site: str, reports: dict[str, AssessmentReport]) -> None:
    legacy = load_legacy(site)["performance"]
    core = reports[site].performance
    # The result's diameter block is the profile-driven DiameterAgreement (reviewer decision
    # 5); parity is checked on the POC-shaped export of it, plus the new fields directly.
    exported = to_slicepoint_v0(reports[site], hospital_name="x").performance
    blocks = {
        "aaa_missing_as_wrong": core.aaa_missing_as_wrong,
        "aaa_when_answered": core.aaa_when_answered,
        "diameter": exported.diameter,
        "dice": core.dice,
    }
    d = core.diameter
    assert d is not None
    shares = {w.tolerance_mm: w.share for w in d.within_tolerance}
    assert _close(shares[2.0], legacy["diameter"]["within_2mm"]) and _close(shares[3.0], legacy["diameter"]["within_3mm"])
    assert _close(d.loa_low, legacy["diameter"]["loa_low"]) and _close(d.mae, legacy["diameter"]["mae"])
    for name, block in blocks.items():
        assert block is not None, name
        got = block.model_dump(by_alias=True)
        assert set(got) == set(legacy[name]), name
        bad = {k: (got[k], v) for k, v in legacy[name].items() if not _close(got[k], v)}
        assert not bad, f"{site} {name}: {bad}"
    leg_dice = load_legacy(site)["dice"]
    assert core.dice is not None and round(core.dice.mean, 3) == leg_dice["average"]


@pytest.mark.parametrize("site", PARITY_SITES)
def test_b_finding_statuses(site: str, reports: dict[str, AssessmentReport]) -> None:
    checks = reports[site].checks
    for f in load_legacy(site)["findings"]:
        assert f["check"] in checks, f"{site}: core did not evaluate {f['check']}"
        assert checks[f["check"]].status is _legacy_status(f["status"]), (site, f["check"])


@pytest.mark.parametrize("site", PARITY_SITES)
def test_b_finding_sentences(site: str, reports: dict[str, AssessmentReport]) -> None:
    checks = reports[site].checks
    for f in load_legacy(site)["findings"]:
        same = checks[f["check"]].summary == f["sentence"]
        if (site, f["check"]) in KNOWN_SENTENCE_DIVERGENCES:
            assert not same, f"{site}/{f['check']} now matches; remove it from KNOWN_SENTENCE_DIVERGENCES"
        else:
            assert same, (site, f["check"])


@pytest.mark.parametrize("site", PARITY_SITES)
def test_c_scans(site: str, reports: dict[str, AssessmentReport]) -> None:
    legacy = load_legacy(site)["scans"]
    core = to_slicepoint_v0(reports[site], hospital_name=site.replace("_", " ").title()).to_legacy_dict()["scans"]
    assert len(core) == len(legacy)
    for a, b in zip(core, legacy):
        assert list(a) == list(b)  # key order is part of the POC contract
        assert {k: v for k, v in a.items() if k != "personGroup"} == {k: v for k, v in b.items() if k != "personGroup"}
    assert _partition([s["personGroup"] for s in core]) == _partition([s["personGroup"] for s in legacy])


@pytest.mark.parametrize("site", PARITY_SITES)
def test_legacy_export_validates_and_notes_match(site: str, reports: dict[str, AssessmentReport]) -> None:
    out = to_slicepoint_v0(reports[site], hospital_name=site.replace("_", " ").title())
    assert isinstance(out, SlicePointFileV0)
    assert sorted(out.notes) == sorted(load_legacy(site)["notes"])


def test_kvp_shift_routed_to_scanning_not_patients(reports: dict[str, AssessmentReport]) -> None:
    """Documented divergence: the notebook's keyword router filed the kVp shift under
    patients because "voltage" contains "age". Core routes by variable."""
    findings = reports["hospital_d"].findings
    assert any(f.factor == "shift_kvp" for f in findings["scanning"])
    assert not any(f.factor == "shift_kvp" for f in findings["patients"])


def _partition(labels: list[str]) -> set[frozenset[int]]:
    groups: dict[str, set[int]] = {}
    for i, lab in enumerate(labels):
        groups.setdefault(lab, set()).add(i)
    return {frozenset(v) for v in groups.values()}


def parity_table(reports: dict[str, AssessmentReport]) -> list[tuple[str, str, str, str]]:
    """(site, check, legacy status or '-', core status) for every check, for PARITY.md."""
    rows = []
    for site in PARITY_SITES:
        legacy = {f["check"]: f["status"] for f in load_legacy(site)["findings"]}
        for check, res in reports[site].checks.items():
            rows.append((site, check, legacy.get(check, "-"), res.status.value))
    return rows
