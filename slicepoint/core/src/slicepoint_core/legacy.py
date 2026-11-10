"""Export an assessment in the POC's ``<hospital>_slicepoint.json`` shape (``SlicePointFileV0``).

For the existing Base44 viewer and for the parity suite. Differences from the notebook's
writer: every evaluated check gets a finding (the POC dropped a check when nothing
mapped to it), and a check's sentence is core's summary.
"""

from __future__ import annotations

from slicepoint_schemas.assessment import DiameterAgreement, ToleranceRole
from slicepoint_schemas.checks import CheckStatus
from slicepoint_schemas.legacy import DiameterMetricsV0, EmptyObject, SlicePointFileV0

from .assessment import AssessmentReport

_LEGACY_STATUS = {CheckStatus.OK: "OK", CheckStatus.WATCH: "Watch", CheckStatus.PROBLEM: "Problem"}


def to_slicepoint_v0(report: AssessmentReport, *, hospital_name: str) -> SlicePointFileV0:
    """``hospital_name`` is the display name (e.g. ``"Hospital B"``); pass it explicitly."""
    r = report.result
    perf = r.performance
    if perf.aaa_missing_as_wrong is None or perf.aaa_when_answered is None or perf.diameter is None:
        raise ValueError("the POC format needs labels and predictions (performance blocks are missing)")

    def rnd(v: float | None) -> float | None:
        return None if v is None else round(v, 2)

    scans = [
        {
            "id": s.case_id[:8],
            "personGroup": s.person_group,
            "sex": s.sex,
            "age_band": s.age_band,
            "scanner_vendor": s.scanner_vendor,
            "contrast_phase": s.contrast_phase.value if s.contrast_phase else None,
            "slice_thickness_class": s.slice_thickness_class.value if s.slice_thickness_class else None,
            "aaa_size_class": s.aaa_size_class.value if s.aaa_size_class else None,
            "aaa": s.aaa,
            "referenceDiameterMm": rnd(s.reference_diameter_mm),
            "aiDiameterMm": rnd(s.ai_diameter_mm),
            "aiAaa": s.ai_aaa,
        }
        for s in r.scans
    ]
    findings = [
        {"check": c.check_id, "status": _LEGACY_STATUS[c.status], "sentence": c.summary or c.status.value}
        for c in r.verdict.results
    ]
    data = {
        "fileType": "hospital_data",
        "hospitalName": hospital_name,
        "scans": scans,
        "findings": findings,
        "notes": list(r.notes),
        "performance": {
            "aaa_missing_as_wrong": perf.aaa_missing_as_wrong,
            "aaa_when_answered": perf.aaa_when_answered,
            "diameter": _diameter_v0(perf.diameter),
            "dice": perf.dice if perf.dice is not None else EmptyObject(),
        },
    }
    if perf.dice is not None:
        data["dice"] = {"average": round(perf.dice.mean, 3), "note": "Baseline model Dice."}
    return SlicePointFileV0.model_validate(data)


def _diameter_v0(d: DiameterAgreement) -> DiameterMetricsV0:
    """The POC block names its tolerances 2 mm and 3 mm. Export refuses other profiles
    rather than mislabelling a share."""
    by_role = {w.role: w for w in d.within_tolerance}
    ba, size = by_role.get(ToleranceRole.BLAND_ALTMAN), by_role.get(ToleranceRole.SIZE)
    if ba is None or size is None or (ba.tolerance_mm, size.tolerance_mm) != (2.0, 3.0):
        raise ValueError("the POC format only carries 2 mm / 3 mm tolerances")
    return DiameterMetricsV0(
        n=d.n, mae=d.mae, rmse=d.rmse, bias=d.bias, loa_low=d.loa_low, loa_high=d.loa_high,
        within_2mm=ba.share, within_3mm=size.share, spearman=d.spearman,
    )
