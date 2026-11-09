"""The by-group table and the cases-to-review list (contract models, computed at run time).

:meth:`slicepoint_core.Assessment.run` calls :func:`stratified_table` and
:func:`cases_to_review` on the per-scan table and stores the results in
:class:`~slicepoint_schemas.assessment.AssessmentResult` (``strata`` and
``cases_to_review``). The HTML report only displays them; it computes no statistics.
Both use the same :mod:`slicepoint_core.stats` functions as the checks.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
from slicepoint_schemas.assessment import (
    CasesToReview,
    ReviewCase,
    ReviewReason,
    ScanSummary,
    Strata,
    StratumRow,
)

from . import stats as S
from .checks.builtin import SUBGROUP_COLUMNS

__all__ = ["cases_to_review", "stratified_table"]


def _scan_value(s: ScanSummary, col: str) -> str:
    v = getattr(s, col, None)
    if v is None:
        return S.MISSING
    return str(getattr(v, "value", v))


def stratified_table(
    scans: Sequence[ScanSummary],
    *,
    size_tolerance_mm: float,
    min_group_size: int,
    min_aaa_for_sensitivity: int,
    columns: Iterable[str] = SUBGROUP_COLUMNS,
) -> Strata:
    """Per-group scans, people, bias, MAE, share within tolerance and sensitivity.

    A group with fewer than ``min_group_size`` scans is marked ``too_few`` and its metrics
    are suppressed. Sensitivity is suppressed below ``min_aaa_for_sensitivity`` aneurysms.
    Both rules use raw scan counts, as the notebook did (see README "Known gaps").
    """
    rows: list[StratumRow] = []
    for col in columns:
        levels = sorted({_scan_value(s, col) for s in scans})
        for lvl in levels:
            g = [s for s in scans if _scan_value(s, col) == lvl]
            n = len(g)
            people = len({s.person_group for s in g})
            labelled = [s for s in g if s.aaa is not None]
            n_aaa = sum(1 for s in labelled if s.aaa)
            too_few = n < min_group_size
            bias = mae = within = sens = lo = hi = None
            if not too_few:
                dm = S.diameter_agreement(
                    np.array([np.nan if s.ai_diameter_mm is None else s.ai_diameter_mm for s in g], dtype=float),
                    np.array([np.nan if s.reference_diameter_mm is None else s.reference_diameter_mm for s in g],
                             dtype=float),
                    tolerances_mm=(size_tolerance_mm,),
                )
                bias, mae, within = dm.bias, dm.mae, dm.within.get(size_tolerance_mm)
            sens_too_few = too_few or n_aaa < min_aaa_for_sensitivity
            if not sens_too_few and labelled:
                b = S.binary_metrics(
                    np.array([bool(s.aaa) for s in labelled]),
                    np.array([np.nan if s.ai_aaa is None else float(s.ai_aaa) for s in labelled], dtype=float),
                )
                sens, lo, hi = b.sens, b.sens_lo, b.sens_hi
            if sens is None:
                lo = hi = None
            rows.append(StratumRow(
                variable=col, level=lvl, n=n, people=people, n_aaa=n_aaa, too_few=too_few, bias_mm=bias,
                mae_mm=mae, within_tolerance=within, sens=sens, sens_lo=lo, sens_hi=hi, sens_too_few=sens_too_few,
            ))
    return Strata(min_group_size=min_group_size, min_aaa_for_sensitivity=min_aaa_for_sensitivity,
                  size_tolerance_mm=size_tolerance_mm, rows=tuple(rows))


def cases_to_review(scans: Sequence[ScanSummary], *, size_tolerance_mm: float) -> CasesToReview:
    """Missed aneurysms, no-answers, size errors beyond the tolerance and false alarms.

    Sorted by priority (1 = missed or unanswered aneurysm, 2 = no answer, 3 = size error,
    4 = false alarm), then by the size of the diameter error, then case id.
    """
    out: list[ReviewCase] = []
    for s in scans:
        reasons: list[ReviewReason] = []
        if s.aaa is True and s.ai_aaa is False:
            reasons.append(ReviewReason.MISSED_ANEURYSM)
        if s.ai_aaa is None:
            reasons.append(ReviewReason.NO_ANSWER_ON_ANEURYSM if s.aaa is True else ReviewReason.NO_ANSWER)
        err: float | None = None
        if s.ai_diameter_mm is not None and s.reference_diameter_mm is not None:
            err = s.ai_diameter_mm - s.reference_diameter_mm
            if abs(err) > size_tolerance_mm:
                reasons.append(ReviewReason.SIZE_ERROR)
        if s.aaa is False and s.ai_aaa is True:
            reasons.append(ReviewReason.FALSE_ALARM)
        if reasons:
            out.append(ReviewCase(
                case_id=s.case_id, person_group=s.person_group, reasons=tuple(reasons),
                priority=min(r.priority for r in reasons), aaa=s.aaa, ai_aaa=s.ai_aaa,
                reference_diameter_mm=s.reference_diameter_mm, ai_diameter_mm=s.ai_diameter_mm, error_mm=err,
            ))
    out.sort(key=lambda c: (c.priority, -abs(c.error_mm or 0.0), c.case_id))
    return CasesToReview(size_tolerance_mm=size_tolerance_mm, n_scans=len(scans), cases=tuple(out))
