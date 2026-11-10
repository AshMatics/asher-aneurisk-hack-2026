"""The five POC checks, ported from ``test_your_hospital.ipynb``.

Each function reproduces the notebook's finding logic for the areas that the POC's
export (cell 34, ``AREA_TO_CHECK``) mapped to that check. Every number comes from the
:class:`~slicepoint_schemas.thresholds.ThresholdProfile` (see :class:`~slicepoint_core.params.Params`).

Routing differs from the notebook in one deliberate way. The notebook sent each
"Patients & scanners" finding to ``patients`` or ``scanning`` by a substring test on the
sentence (``sex``, ``age``, ``prevalence``, ``aorta diameter``). Here routing is explicit
by variable: the scanner, contrast, slice-thickness, brightness and kVp shifts belong to
``scanning``; sex, age, the two diameter distributions and prevalence belong to
``patients``. The only practical difference is kVp: its sentence ("tube volt*age*")
matched ``age``, so the notebook filed it under ``patients``. See ``PARITY.md``.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from slicepoint_schemas.checks import DEFAULT_CHECK_REGISTRY, CheckStatus

from .. import stats as S
from ..reference import CATEGORY_LABELS
from .context import CheckContext, EvidenceValue, Finding, Severity, all_of, worst
from .registry import CheckFn, CheckOutput, CheckRegistry, CheckSkipped, CheckSpec, Requirement, evidence

_DESC = DEFAULT_CHECK_REGISTRY.as_mapping()

_NICE = {
    "aorta_hu_mean": "aorta brightness (HU)",
    "max_aortic_diameter_mm": "labelled aorta diameter",
    "pred_max_diameter_mm": "predicted aorta diameter",
    "kvp": "tube voltage (kVp)",
    "slice_thickness_mm": "slice thickness",
}


# --------------------------------------------------------------------------- shared pieces


_MIX_TRIGGERS: dict[str, str] = {**CATEGORY_LABELS, "aaa_size_class": "AAA size class mix"}
"""Category column -> trigger name in the profile. ``aaa_size_class`` is new vs the POC
(reviewer decision 2026-11-09); the notebook only used it for the score."""

_MIX_TEXT: dict[str, str] = {**{c: lbl.lower() for c, lbl in CATEGORY_LABELS.items()}, "aaa_size_class": "AAA size-class mix"}


def _tvd_findings(ctx: CheckContext, columns: tuple[str, ...], area: str) -> tuple[list[Finding], dict[str, float]]:
    """Category-mix distance vs the reference (cell 19). Only red / yellow are findings."""
    findings: list[Finding] = []
    distances: dict[str, float] = {}
    ref_mixes = ctx.reference.summary.category_mixes
    for c in columns:
        if c not in ctx.frame or c not in ref_mixes:
            continue
        here = S.category_mix(ctx.frame[c])
        ref = ref_mixes[c]
        t = S.tvd(here, ref)
        distances[c] = t
        sev = Severity.of(ctx.params.classify(_MIX_TRIGGERS[c], t))
        if sev is Severity.OK:
            continue
        label = _MIX_TEXT[c]
        word = "is very different from" if sev is Severity.RED else "differs from"
        findings.append(
            Finding(f"tvd_{c}", sev, f"The {label} {word} the reference (distance {t:.2f}). {_gaps(here, ref)}.", area,
                    {"distance": t})
        )
    return findings, distances


def _gaps(a: dict[str, float], b: dict[str, float], k: int = 2) -> str:
    idx = sorted(set(a) | set(b))
    diff = pd.Series({i: a.get(i, 0.0) - b.get(i, 0.0) for i in idx})
    top = diff.abs().sort_values(ascending=False, kind="stable").index[:k]
    return "; ".join(f"{i}: {a.get(i, 0):.0%} here vs {b.get(i, 0):.0%} reference" for i in top)


def _shift_findings(ctx: CheckContext, columns: tuple[str, ...], area: str) -> tuple[list[Finding], dict[str, S.PermutationTest]]:
    """Wasserstein permutation tests on one-scan-per-person data (cell 19)."""
    findings: list[Finding] = []
    tests: dict[str, S.PermutationTest] = {}
    dd = ctx.deduplicated
    for c in columns:
        if c not in dd or c not in ctx.reference.numeric:
            continue
        r = S.permutation_test(
            dd[c].to_numpy(dtype=float),
            ctx.reference.numeric[c],
            n_perm=ctx.params.int("permutation_count"),
            seed=ctx.params.int("random_seed"),
            min_n=ctx.params.int("numeric_test_min_n"),
        )
        tests[c] = r
        status = all_of(ctx.params.classify("numeric_shift_sd", r.sd_units), ctx.params.classify("numeric_shift_p", r.p))
        sev = Severity.of(status)
        if sev is Severity.OK or r.sd_units is None or r.p is None:
            continue
        ev = {"sd_units": r.sd_units, "p": r.p, "median_diff": r.median_diff, "null95_sd_units": r.null95_sd_units}
        if sev is Severity.RED:
            text = (f"The {_NICE[c]} is clearly different from the reference (shift {r.sd_units:.2f} SD, "
                    f"median {r.median_diff:+.1f}, p={r.p:.3f}).")
        else:
            text = f"The {_NICE[c]} is somewhat different from the reference (shift {r.sd_units:.2f} SD, p={r.p:.3f})."
        findings.append(Finding(f"shift_{c}", sev, text, area, ev))
    return findings, tests


# --------------------------------------------------------------------------- repeats


def check_repeats(ctx: CheckContext) -> CheckOutput:
    """Repeat patients (cell 11) and leakage (cell 13)."""
    df, g, p = ctx.frame, ctx.people, ctx.params
    n, n_true = ctx.n, g.n_people
    share = g.share_with_near_duplicate
    info: dict[str, EvidenceValue] = {
        "scans": n,
        "patient_ids": int(df["patient_id"].nunique()),
        "real_people": n_true,
        "scans_with_near_duplicate": int(g.is_duplicate.sum()),
        "share_with_near_duplicate": share,
        "duplicates_under_different_patient_id": int(g.id_mismatch.sum()),
        "median_nearest_neighbour_similarity": float(np.median(g.twin_similarity)),
    }
    findings: list[Finding] = []
    if Severity.of(p.classify("repeats_near_duplicate_share", share)) is Severity.RED:
        findings.append(Finding(
            "near_duplicates", Severity.RED,
            f"{int(g.is_duplicate.sum())} of {n} scans ({share:.0%}) have a near-identical twin; there are only "
            f"{n_true} real patients behind {n} scans. {int(g.id_mismatch.sum())} of the twins are filed under a "
            "different patient ID, so ID-based checks would miss them. Accuracy measured on this data will look "
            "better than it really is until repeats are removed.", "Repeat patients", info))
    else:
        findings.append(Finding("near_duplicates", Severity.OK,
                                f"No repeat scans found: {n} scans, {n_true} real patients.", "Repeat patients",
                                info))
    n_missing = int(df["patient_id"].isna().sum())
    if Severity.of(p.classify("repeats_missing_patient_id_count", n_missing)) is not Severity.OK:
        findings.append(Finding("missing_patient_id", Severity.YELLOW,
                                f"{n_missing} scans have no patient_id, so repeat patients can only be found from the images.",
                                "Repeat patients", {"count": n_missing}))

    out = CheckOutput(findings=findings, score=100.0 * n_true / n if n else None)
    if ctx.dataset.has_labels and ctx.dataset.embeddings is not None:
        leak = S.leakage_test(
            ctx.dataset.embeddings, df["max_aortic_diameter_mm"].to_numpy(float), g.labels,
            n_splits=p.int("cv_folds"), seed=p.int("random_seed"), n_pc=p.int("embedding_max_pcs"),
            max_iter=p.int("leakage_mlp_max_iter"),
        )
        if leak is None:
            out.not_evaluated_parts["leakage"] = "fewer real people than cross-validation folds"
        else:
            ev = {"random_split_mae_mm": leak.random_split_mae, "by_person_mae_mm": leak.by_person_mae,
                  "gap_ratio": leak.gap_ratio, "random_split_r2": leak.random_split_r2,
                  "by_person_r2": leak.by_person_r2}
            if Severity.of(p.classify("repeats_leakage_gap_ratio", leak.gap_ratio)) is Severity.RED:
                findings.append(Finding("leakage", Severity.RED,
                    f"A random split gives {leak.random_split_mae:.1f} mm error but the honest by-patient split gives "
                    f"{leak.by_person_mae:.1f} mm: the data leaks, so random-split results here are too optimistic.",
                    "Leakage", ev))
            else:
                findings.append(Finding("leakage", Severity.OK,
                    f"Random-split and by-patient errors agree ({leak.random_split_mae:.1f} vs "
                    f"{leak.by_person_mae:.1f} mm): no sign of leakage.", "Leakage", ev))
            findings.append(Finding("leakage_r2", Severity.INFO,
                "R2 is unreliable with this few scans and a narrow diameter range; compare errors in mm and the "
                "random-vs-patient gap instead.", "Leakage"))
    else:
        out.not_evaluated_parts["leakage"] = "needs labelled diameters and embeddings"
    out.evidence.append(evidence("score_basis", "distinct people / scans"))
    return out


# --------------------------------------------------------------------------- scanning


_SCANNING_CATS = ("scanner_vendor", "contrast_phase", "slice_thickness_class")

CHANCE_AUC = 0.5


def floor_domain_auc(auc: float) -> float:
    """The domain AUC the scanning check classifies and reports: ``max(auc, 0.5)``.

    :func:`slicepoint_core.stats.domain_auc` returns the raw cross-validated AUC (notebook
    parity). Below 0.5 it only means the classifier did no better than chance, so it is
    floored at chance rather than read as a separation.
    """
    return max(float(auc), CHANCE_AUC)
_SCANNING_NUMERIC = ("aorta_hu_mean", "kvp", "slice_thickness_mm")


def _implausible(ctx: CheckContext) -> Finding:
    p, df = ctx.params, ctx.frame
    dlo, dhi = p.num("plausible_diameter_low_mm"), p.num("plausible_diameter_high_mm")
    ranges = {
        "max_aortic_diameter_mm": (dlo, dhi),
        "pred_max_diameter_mm": (dlo, dhi),
        "aorta_hu_mean": (p.num("plausible_hu_low"), p.num("plausible_hu_high")),
        "kvp": (p.num("plausible_kvp_low"), p.num("plausible_kvp_high")),
        "slice_thickness_mm": (p.num("plausible_slice_low_mm"), p.num("plausible_slice_high_mm")),
    }
    counts = {c: int(((df[c] < lo) | (df[c] > hi)).sum()) for c, (lo, hi) in ranges.items() if c in df}
    for c in [c for c in df if str(c).startswith("organ_volumes_")]:
        counts[f"{c} (negative)"] = int((df[c] < 0).sum())
    bad = {k: v for k, v in counts.items() if v}
    total = sum(bad.values())
    if Severity.of(p.classify("scanning_implausible_value_count", total)) is Severity.RED:
        return Finding("implausible_values", Severity.RED, f"Values outside any plausible range: {bad}.",
                       "Impossible values", {"count": total, "detail": json.dumps(bad)})
    return Finding("implausible_values", Severity.OK,
                   "No impossible diameters, brightness, kVp, slice thickness or organ volumes.", "Impossible values",
                   {"count": total})


def check_scanning(ctx: CheckContext) -> CheckOutput:
    """Acquisition similarity: impossible values (cell 15), scanner / contrast / slice
    mixes and HU / kVp / slice-thickness shifts (cell 19), scan content (cell 20) and the
    embedding shortcut probe (cell 26)."""
    p = ctx.params
    findings: list[Finding] = [_implausible(ctx)]
    tvd_f, distances = _tvd_findings(ctx, _SCANNING_CATS, "Patients & scanners")
    shift_f, _ = _shift_findings(ctx, _SCANNING_NUMERIC, "Patients & scanners")
    findings += tvd_f + shift_f
    out = CheckOutput(findings=findings)

    if ctx.has_embeddings and ctx.reference_has_embeddings:
        ref = ctx.reference
        assert ref.embeddings is not None and ref.coverage is not None and ctx.dataset.embeddings is not None
        auc_raw = S.domain_auc(
            ref.embeddings, ctx.dataset.embeddings,
            np.array([f"ref_{i}" for i in ref.person_labels], dtype=object),
            np.array([f"new_{i}" for i in ctx.people.labels], dtype=object),
            n_pc=p.int("embedding_max_pcs"), n_splits=p.int("cv_folds"), seed=p.int("random_seed"),
        )
        # A cross-validated AUC below 0.5 is noise around chance, never "anti-separation":
        # classify and report the floored value; the raw one stays in the evidence.
        auc = floor_domain_auc(auc_raw)
        sev = Severity.of(p.classify("scanning_domain_auc", auc))
        if auc_raw < CHANCE_AUC and sev is Severity.OK:
            text = (f"The scans cannot be told apart from the reference: a simple classifier did no better than "
                    f"chance (AUC {auc:.2f}; cross-validated {auc_raw:.2f}, at or below chance).")
        else:
            text = {
                Severity.RED: f"A simple classifier can tell this hospital's scans from the reference with AUC "
                              f"{auc:.2f}; the images are systematically different.",
                Severity.YELLOW: f"The scans are partly distinguishable from the reference (AUC {auc:.2f}).",
                Severity.OK: f"The scans are hard to tell apart from the reference (AUC {auc:.2f}).",
            }[sev]
        findings.append(Finding("scan_content_auc", sev, text, "Scan content", {"auc": auc, "auc_raw": auc_raw}))
        outside = ref.coverage.share_outside(ctx.dataset.embeddings)
        sev = Severity.of(p.classify("Scans unlike anything in the reference", outside))
        if sev is not Severity.OK:
            text = (f"{outside:.0%} of scans look unlike anything the model was validated on." if sev is Severity.RED
                    else f"{outside:.0%} of scans look unlike anything in the reference.")
            findings.append(Finding("scan_content_coverage", sev, text, "Scan content", {"share": outside}))
        out.evidence.append(evidence("share_outside_reference_coverage", outside))
    else:
        why = "no embeddings for this site" if not ctx.has_embeddings else "reference has no embeddings"
        out.not_evaluated_parts["scan_content"] = why

    if ctx.has_embeddings and ctx.dataset.has_labels:
        _embedding_probe(ctx, findings)
    else:
        out.not_evaluated_parts["embedding_shortcuts"] = "needs embeddings and AAA labels"

    worst_tvd = max((distances[c] for c in _SCANNING_CATS if c in distances), default=None)
    out.score = None if worst_tvd is None else 100.0 * (1.0 - worst_tvd)
    for c, t in distances.items():
        out.evidence.append(evidence(f"tvd.{c}", t))
    out.evidence.append(evidence("score_basis", "1 - worst TVD of scanner, contrast, slice thickness"))
    return out


def _embedding_probe(ctx: CheckContext, findings: list[Finding]) -> None:
    p = ctx.params
    assert ctx.dataset.embeddings is not None
    scores: dict[str, S.ProbeScore] = {}
    for c in (*_SCANNING_CATS, "aaa"):
        if c not in ctx.frame:
            continue
        s = S.embedding_probe(
            ctx.dataset.embeddings, ctx.frame[c], ctx.people.labels,
            n_pc=p.int("embedding_max_pcs"), n_splits=p.int("cv_folds"), seed=p.int("random_seed"),
            min_class_n=p.int("embedding_probe_min_class_n"), min_rows=p.int("embedding_probe_min_rows"),
        )
        if s is not None:
            scores[c] = s
    acq = [scores[c].above_chance for c in _SCANNING_CATS if c in scores]
    if not acq or "aaa" not in scores:
        return
    dis = scores["aaa"].above_chance
    margin = float(np.mean(acq)) - dis
    ev = {"acquisition_signal": float(np.mean(acq)), "aaa_signal": dis, "margin": margin}
    if Severity.of(p.classify("scanning_embedding_shortcut_margin", margin)) is not Severity.OK:
        findings.append(Finding("embedding_shortcuts", Severity.YELLOW,
            f"In this hospital the embeddings encode scanner/protocol information (+{np.mean(acq):.2f} above chance) "
            f"more strongly than the aneurysm label (+{dis:.2f}); a model on top of them could learn acquisition "
            "shortcuts.", "Embeddings", ev))
    else:
        findings.append(Finding("embedding_shortcuts", Severity.INFO,
            f"The embeddings carry aneurysm information (+{dis:.2f} above chance) at least as strongly as "
            f"scanner/protocol information (+{np.mean(acq):.2f}).", "Embeddings", ev))


# --------------------------------------------------------------------------- patients


_PATIENT_CATS = ("sex", "age_band")
_PATIENT_NUMERIC = ("max_aortic_diameter_mm", "pred_max_diameter_mm")


def check_patients(ctx: CheckContext) -> CheckOutput:
    """Patient mix: sex and age mixes, diameter distributions and AAA prevalence (cell 19),
    plus the AAA size-class mix (new vs the POC, reviewer decision 2026-11-09)."""
    p = ctx.params
    cats = _PATIENT_CATS + (("aaa_size_class",) if ctx.dataset.has_labels else ())
    findings, distances = _tvd_findings(ctx, cats, "Patients & scanners")
    shift_f, _ = _shift_findings(ctx, _PATIENT_NUMERIC, "Patients & scanners")
    findings += shift_f
    out = CheckOutput(findings=findings)

    ref = ctx.reference.summary
    if ctx.dataset.has_labels and ref.has_labels and ref.aaa_positive_deduplicated is not None:
        dd = ctx.deduplicated
        a_new, n_new = int(dd["aaa"].sum()), len(dd)
        a_ref, n_ref = ref.aaa_positive_deduplicated, ref.n_deduplicated
        p_f = S.fisher_exact_p(a_new, n_new, a_ref, n_ref)
        diff = a_new / n_new - a_ref / n_ref
        status = all_of(p.classify("patients_prevalence_fisher_p", p_f), p.classify("patients_prevalence_abs_diff", abs(diff)))
        ev = {"new": a_new / n_new, "reference": a_ref / n_ref, "fisher_p": p_f}
        if Severity.of(status) is not Severity.OK:
            findings.append(Finding("prevalence", Severity.of(status),
                f"Aneurysm prevalence is {a_new / n_new:.0%} here vs {a_ref / n_ref:.0%} at the reference (p={p_f:.3f}); "
                "the model sees a different case mix.", "Patients & scanners", ev))
    else:
        out.not_evaluated_parts["prevalence"] = "needs AAA labels at the site and the reference"

    parts = [distances[c] for c in ("sex", "age_band", "aaa_size_class") if c in distances]
    out.score = 100.0 * (1.0 - max(parts)) if parts else None
    for c, t in distances.items():
        out.evidence.append(evidence(f"tvd.{c}", t))
    out.evidence.append(evidence("score_basis", "1 - worst TVD of sex, age band, AAA size class"))
    return out


# --------------------------------------------------------------------------- labels


def check_labels(ctx: CheckContext) -> CheckOutput:
    """Labelling (cell 15) and labelling vs model cutoff (cell 24)."""
    p, df = ctx.params, ctx.frame
    line = p.decision_line_mm
    d = df["max_aortic_diameter_mm"]
    y = df["aaa"].astype(bool)
    neg_max = float(d[~y].max()) if (~y).any() else float("nan")
    pos_min = float(d[y].min()) if y.any() else float("nan")
    conflict = (d >= line) != y
    share = float(conflict.mean())
    ref_pos_min = ctx.reference.summary.smallest_aaa_mm
    ev: dict[str, EvidenceValue] = {
        "largest_diameter_labelled_not_aaa": neg_max,
        "smallest_diameter_labelled_aaa": pos_min,
        "reference_smallest_aaa": ref_pos_min,
        "n_labels_disagreeing_with_cutoff": int(conflict.sum()),
        "share_disagreeing": share,
        "cutoff_mm": line,
    }
    s_share = p.classify("Labels that disagree with the 30 mm rule", share)
    s_min = p.classify("labels_smallest_aaa_below_line_mm", line - pos_min) if y.any() else None
    findings: list[Finding] = []
    if CheckStatus.PROBLEM in (s_share, s_min):
        ref_txt = f"{ref_pos_min:.1f}" if ref_pos_min is not None else "n/a"
        findings.append(Finding("rule_conflicts", Severity.RED,
            f"This hospital labels an aneurysm from {pos_min:.1f} mm (reference: {ref_txt} mm) and {int(conflict.sum())} "
            f"labels ({share:.0%}) disagree with the {line:g} mm rule the model follows. The model's AAA calls cannot be "
            "judged until both sides use the same definition.", "Labelling", ev))
    elif s_share is CheckStatus.WATCH:
        findings.append(Finding("rule_conflicts", Severity.YELLOW,
            f"{int(conflict.sum())} labels ({share:.0%}) disagree with the {line:g} mm rule.", "Labelling", ev))
    else:
        findings.append(Finding("rule_conflicts", Severity.OK,
            f"Aneurysm labels follow the {line:g} mm rule (largest 'no AAA' {neg_max:.1f} mm, smallest 'AAA' "
            f"{pos_min:.1f} mm).", "Labelling", ev))

    known = {"none", "30-54mm", ">=55mm"}
    if set(df["aaa_size_class"].dropna().unique()) <= known:
        big = p.large_aneurysm_line_mm
        expected = d.map(lambda x: "none" if x < line else ("30-54mm" if x < big else ">=55mm"))
        mismatch = int((expected != df["aaa_size_class"]).sum())
        if Severity.of(p.classify("labels_size_class_mismatch_count", mismatch)) is not Severity.OK:
            findings.append(Finding("size_class_mismatch", Severity.YELLOW,
                f"{mismatch} scans have a size class that does not match their own diameter.", "Labelling",
                {"count": mismatch}))

    out = CheckOutput(findings=findings, score=100.0 * (1.0 - share))
    ref_cut = ctx.reference.summary.cutoff
    if ctx.dataset.has_predictions and ref_cut is not None:
        cut = S.cutoff_range(df["pred_max_diameter_mm"], y.to_numpy(bool), p.cutoff_grid())
        if cut is not None:
            shift = cut.midpoint - (ref_cut.low + ref_cut.high) / 2
            sev = Severity.of(p.classify("labels_cutoff_shift_mm", abs(shift)))

            def rng(lo: float, hi: float) -> str:
                return f"{lo:.1f} mm" if lo == hi else f"{lo:.1f}-{hi:.1f} mm"

            here, there = rng(cut.low, cut.high), rng(ref_cut.low, ref_cut.high)
            text = {
                Severity.RED: f"The model's diameter output matches this hospital's AAA labels best at {here}, versus "
                              f"{there} at the reference: the hospital's definition of an aneurysm differs from the "
                              "model's. The model measures well but its yes/no call will not match.",
                Severity.YELLOW: f"The labels line up with the model's diameters at {here}, versus {there} at the reference.",
                Severity.OK: "This hospital's labels line up with the model's diameter output at about the same cutoff "
                             "as the reference.",
            }[sev]
            findings.append(Finding("cutoff_shift", sev, text, "Labelling vs model",
                                    {"low": cut.low, "high": cut.high, "bal_acc_at_best": cut.bal_acc_at_best,
                                     "shift_mm": shift}))
        else:
            out.not_evaluated_parts["cutoff_alignment"] = "labels contain only one class"
    else:
        out.not_evaluated_parts["cutoff_alignment"] = "needs predictions here and a labelled reference"
    out.evidence.append(evidence("score_basis", "1 - share of labels conflicting with the decision line"))
    return out


# --------------------------------------------------------------------------- accuracy


SUBGROUP_COLUMNS: tuple[str, ...] = ("contrast_phase", "slice_thickness_class", "sex", "age_band", "scanner_vendor")


def check_accuracy(ctx: CheckContext) -> CheckOutput:
    """AI accuracy: silent failures and outliers (cell 17), AAA call and diameter (cell
    22), subgroups (cell 23) and outline Dice (cell 29)."""
    p, df = ctx.params, ctx.frame
    ref = ctx.reference.summary
    findings: list[Finding] = []
    out = CheckOutput(findings=findings)

    # ---- silent failures
    na = df["pred_aaa_f"].isna()
    na_rate = float(na.mean())
    by_group: dict[str, dict[str, float]] = {}
    for c in ("contrast_phase", "sex", "scanner_vendor", "slice_thickness_class"):
        if c in df:
            t = na.groupby(df[c].astype(object).where(df[c].notna(), "MISSING")).mean()
            by_group[c] = {str(k): float(v) for k, v in t.items() if v > 0}
    sev = Severity.of(p.classify("No-answer rate", na_rate))
    text = {
        Severity.RED: f"The model returned no AAA answer for {na_rate:.0%} of scans, most often in: {by_group}. "
                      "A blank must never be read as 'normal'.",
        Severity.YELLOW: f"The model returned no AAA answer for {na_rate:.0%} of scans.",
        Severity.OK: f"The model answered for {1 - na_rate:.0%} of scans.",
    }[sev]
    findings.append(Finding("no_answers", sev, text, "Silent failures",
                            {"share_no_answer": na_rate, "by_group": json.dumps(by_group)}))

    # ---- measurement outliers
    err = df["pred_max_diameter_mm"] - df["max_aortic_diameter_mm"]
    if ref.error_sd_mm is not None:
        thr = p.num("outlier_sd_multiple") * ref.error_sd_mm
        outl = err.abs() > thr
        k = int(outl.sum())
        if Severity.of(p.classify("accuracy_measurement_outlier_count", k)) is not Severity.OK:
            findings.append(Finding("measurement_outliers", Severity.YELLOW,
                f"{k} scan(s) where the model's diameter differs from the label by more than {thr:.1f} mm "
                f"({p.num('outlier_sd_multiple'):g}x the reference spread). Worth a manual look.",
                "Measurement outliers", {"count": k, "threshold_mm": thr}))
    else:
        out.not_evaluated_parts["measurement_outliers"] = "reference has no diameter error spread"

    # ---- AAA call
    b = ctx.bin_missing_as_wrong
    assert b is not None
    br = ref.performance_missing_as_wrong
    caught = p.trigger("Aneurysms the model caught")
    bev = {k: v for k, v in b.model_dump().items()}
    if b.n_aaa < p.int("min_aaa_for_sensitivity"):
        findings.append(Finding("aneurysms_caught", Severity.INFO,
            f"Only {b.n_aaa} scans carry an aneurysm label, too few to judge the model's AAA call.", "AAA model", bev))
    else:
        assert b.sens is not None and b.sens_lo is not None and b.sens_hi is not None
        if caught.crosses(b.sens_hi, caught.red):
            sev = Severity.RED
        elif caught.crosses(b.sens, caught.yellow):
            sev = Severity.YELLOW
        else:
            sev = Severity.OK
        ref_sens = f"{br.sens:.0%}" if br is not None and br.sens is not None else "n/a"
        findings.append(Finding("aneurysms_caught", sev,
            f"The model caught {b.tp} of {b.n_aaa} aneurysms (sensitivity {b.sens:.0%}, plausible range "
            f"{b.sens_lo:.0%} to {b.sens_hi:.0%}; reference {ref_sens}). Balanced accuracy {_num(b.bal_acc)}, "
            f"G-mean {_num(b.g_mean)}.", "AAA model", bev))
    if b.spec is not None and Severity.of(p.classify("accuracy_specificity", b.spec)) is not Severity.OK:
        findings.append(Finding("specificity", Severity.YELLOW,
            f"The model raised false alarms: specificity {b.spec:.0%} ({b.fp} of {b.n_not_aaa} healthy scans, "
            "including no-answers).", "AAA model", bev))

    dm = ctx.diameter
    assert dm is not None
    tol_ba, tol_size = p.tolerances()
    if dm.mae is not None:
        sev = Severity.of(p.classify("Average diameter error", dm.mae))
        ref_mae = ref.diameter.mae if ref.diameter is not None else None
        within = dm.within.get(tol_ba)
        findings.append(Finding("diameter_error", sev,
            f"Diameter error: on average {dm.mae:.1f} mm (reference {_num(ref_mae, 1)} mm); "
            f"{_pct(within)} of scans within {tol_ba:g} mm; bias {dm.bias:+.1f} mm.", "AAA model",
            {"mae": dm.mae, "bias": dm.bias, "loa_low": dm.loa_low, "loa_high": dm.loa_high, "n": dm.n}))

    # ---- subgroups
    _subgroups(ctx, findings, out)

    # ---- outline quality
    dice = ctx.dice
    if dice is not None:
        status = worst(p.classify("accuracy_dice_median", dice.median),
                       p.classify("accuracy_dice_share_below_line", dice.share_below_0_90))
        ref_med = f"{ref.dice.median:.2f}" if ref.dice is not None else "nan"
        line = p.num("dice_poor_outline_line")
        findings.append(Finding("dice", Severity.of(status),
            f"The model's aorta outline overlaps the expert outline well in most scans (median Dice {dice.median:.2f}, "
            f"reference {ref_med}); {dice.share_below_0_90:.0%} of scans are below {line:.2f}.", "Segmentation shape",
            {"median": dice.median, "mean": dice.mean, "share_below_line": dice.share_below_0_90}))
        low = df["pred_aorta_dice"] < line
        k_min = p.int("poor_outline_min_cases")
        if k_min <= int(low.sum()) < len(df) - k_min and int(err[low].notna().sum()) >= k_min:
            e_low, e_hi = float(err[low].abs().mean()), float(err[~low].abs().mean())
            bad = e_low > p.num("poor_outline_error_ratio") * e_hi and e_low > p.num("poor_outline_error_floor_mm")
            findings.append(Finding("poor_outline_error", Severity.YELLOW if bad else Severity.INFO,
                f"Scans with a poor outline (Dice < {line:.2f}) have an average diameter error of {e_low:.1f} mm, "
                f"versus {e_hi:.1f} mm for the rest.", "Segmentation shape", {"error_low_mm": e_low, "error_rest_mm": e_hi}))
    else:
        out.not_evaluated_parts["dice"] = "no Dice values"

    # ---- provisional score: lowest of Dice, share within size tolerance, sensitivity
    parts: dict[str, float] = {}
    if dice is not None:
        parts["dice_mean"] = 100.0 * dice.mean
    within_size = dm.within.get(tol_size)
    if within_size is not None:
        parts["within_size_tolerance"] = 100.0 * within_size
    if b.sens is not None and b.n_aaa >= p.int("min_aaa_for_sensitivity"):
        parts["sensitivity"] = 100.0 * b.sens
    out.score = min(parts.values()) if parts else None
    for k2, v in parts.items():
        out.evidence.append(evidence(f"score_part.{k2}", v))
    out.evidence.append(evidence("score_basis", "lowest of Dice x 100, % within size tolerance, sensitivity x 100"))
    return out


def _subgroups(ctx: CheckContext, findings: list[Finding], out: CheckOutput) -> None:
    """Per-subgroup flags (cell 23, ``flag_row``), one finding per problem type."""
    p, df = ctx.params, ctx.frame
    ref = ctx.reference.summary
    ref_mae = ref.diameter.mae if ref.diameter is not None else None
    min_n = ctx.profile.min_group_size
    min_aaa = p.int("min_aaa_for_sensitivity")
    mae_floor = p.trigger("Average diameter error").yellow
    na_line = p.trigger("No-answer rate").red
    sens_red = p.trigger("Aneurysms the model caught").red
    rows = []
    for col in [c for c in SUBGROUP_COLUMNS if c in df]:
        key = df[col].astype(object).where(df[col].notna(), "MISSING").astype(str)
        for lvl in sorted(key.unique()):
            g = df[key == lvl]
            b = S.binary_metrics(g["aaa"].to_numpy(bool), g["pred_aaa_f"].to_numpy(float))
            dm = S.diameter_agreement(g["pred_max_diameter_mm"], g["max_aortic_diameter_mm"])
            rows.append({"variable": col, "level": lvl, "n": b.n, "n_aaa": b.n_aaa, "sens_hi": b.sens_hi,
                         "mae_mm": dm.mae, "pct_no_answer": float(g["pred_aaa_f"].isna().mean())})
    sub = pd.DataFrame(rows)
    if sub.empty:
        return

    def flags(r: pd.Series) -> list[str]:
        f = []
        if (mae_floor is not None and ref_mae is not None and r["n"] >= min_n and r["mae_mm"] is not None
                and r["mae_mm"] > max(mae_floor, p.num("subgroup_mae_ref_multiple") * ref_mae)):
            f.append("measurement error high")
        if sens_red is not None and r["n_aaa"] >= min_aaa and r["sens_hi"] is not None and r["sens_hi"] < sens_red:
            f.append("misses aneurysms")
        if na_line is not None and r["n"] >= min_n and r["pct_no_answer"] > na_line:
            f.append("many no-answers")
        return f

    sub["flags"] = sub.apply(flags, axis=1)
    eligible_of = {
        "measurement error high": sub["n"] >= min_n,
        "misses aneurysms": sub["n_aaa"] >= min_aaa,
        "many no-answers": sub["n"] >= min_n,
    }
    flagged = 0
    for name, eligible in eligible_of.items():
        hit = sub[sub["flags"].map(lambda f: name in f)]
        if not len(hit):
            continue
        flagged += len(hit)
        names = [f"{r['variable']}={r['level']} (n={r['n']})" for _, r in hit.iterrows()]
        n_el = int(eligible.sum())
        if len(hit) >= p.num("subgroup_hospital_wide_share") * max(n_el, 1):
            text = (f"Problem '{name}' appears in nearly every subgroup tested ({len(hit)} of {n_el}), so it is "
                    "hospital-wide, not specific to one scanner or patient group.")
        else:
            text = f"Problem '{name}' in: {', '.join(names[:8])}{' ...' if len(names) > 8 else ''}."
        sev = Severity.of(p.classify("accuracy_subgroup_flag_count", len(hit)))
        if sev is not Severity.OK:
            findings.append(Finding(f"subgroup_{name.replace(' ', '_').replace('-', '_')}", sev, text, "Subgroups",
                                    {"groups": "; ".join(names)}))
    gaps = sub[(sub["n"] >= p.num("evidence_gap_min_n")) & (sub["n_aaa"] == 0)]
    if len(gaps):
        listing = ", ".join(f"{r['variable']}={r['level']}" for _, r in gaps.iterrows())
        findings.append(Finding("evidence_gaps", Severity.INFO,
            f"No aneurysm cases in these groups, so the model's AAA detection there could not be tested: {listing}.",
            "Subgroups"))
    if len(sub[(sub["n_aaa"] > 0) & (sub["n_aaa"] < min_aaa)]):
        findings.append(Finding("small_subgroups", Severity.INFO,
            f"Subgroups with only 1-{min_aaa - 1} aneurysms give meaningless sensitivity numbers; they are listed but "
            "should not be interpreted.", "Subgroups"))
    out.evidence.append(evidence("subgroups_flagged", flagged))


def _num(v: float | None, dp: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{dp}f}"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


# --------------------------------------------------------------------------- registry


def _spec(check_id: str, fn: CheckFn, requires: set[Requirement], sub: dict[str, str]) -> CheckSpec:
    return CheckSpec(descriptor=_DESC[check_id], run=fn, requires=frozenset(requires), sub_factor_of=sub)


def default_registry() -> CheckRegistry:
    """The five POC checks, in the POC's display order."""
    return CheckRegistry([
        _spec("repeats", check_repeats, {Requirement.EMBEDDINGS},
              {"near_duplicates": "people", "missing_patient_id": "people", "leakage": "leakage"}),
        _spec("scanning", check_scanning, set(),
              {"tvd_scanner_vendor": "scanner_vendor", "tvd_contrast_phase": "contrast_phase",
               "tvd_slice_thickness_class": "slice_thickness_class", "shift_slice_thickness_mm": "slice_thickness_class",
               "scan_content_auc": "domain_auc", "scan_content_coverage": "coverage",
               "shift_aorta_hu_mean": "hu_shift", "shift_kvp": "kvp_shift",
               "implausible_values": "impossible_values", "embedding_shortcuts": "embedding_shortcuts"}),
        _spec("patients", check_patients, set(),
              {"tvd_sex": "sex", "tvd_age_band": "age_band", "tvd_aaa_size_class": "aaa_size_class",
               "prevalence": "aaa_size_class", "shift_max_aortic_diameter_mm": "labelled_diameter_shift",
               "shift_pred_max_diameter_mm": "predicted_diameter_shift"}),
        _spec("labels", check_labels, {Requirement.LABELS},
              {"rule_conflicts": "rule_conflicts", "size_class_mismatch": "rule_conflicts",
               "cutoff_shift": "cutoff_alignment"}),
        _spec("accuracy", check_accuracy, {Requirement.LABELS, Requirement.PREDICTIONS},
              {"aneurysms_caught": "aneurysms_caught", "dice": "dice", "poor_outline_error": "dice",
               "diameter_error": "size_within_tolerance", "measurement_outliers": "size_within_tolerance",
               "no_answers": "no_answers", "specificity": "specificity",
               "subgroup_measurement_error_high": "subgroups", "subgroup_misses_aneurysms": "subgroups",
               "subgroup_many_no_answers": "subgroups"}),
    ])


__all__ = [
    "CHANCE_AUC",
    "SUBGROUP_COLUMNS",
    "CheckSkipped",
    "check_accuracy",
    "check_labels",
    "check_patients",
    "check_repeats",
    "check_scanning",
    "default_registry",
    "floor_domain_auc",
]
