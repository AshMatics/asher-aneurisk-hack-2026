"""Self-contained HTML report for one :class:`~slicepoint_schemas.assessment.AssessmentResult`.

``render_html(result)`` returns one HTML document with inline CSS and inline SVG. It makes
**no external requests**: no CDN, web fonts, scripts or images from the network, and a
Content-Security-Policy that forbids them, because the report is opened on hospital
machines and may sit next to patient data. It needs only the standard library
(``string.Template`` and ``html.escape``).

What it shows, following the POC's good parts (ADR 0001; POC spec "What to keep"):

1. the verdict first, with a one-sentence rationale;
2. one card per registered check: status as a text label, per-check n and effective n,
   the named failing sub-factors, the findings, a "What this means" line and a
   "Show the numbers" disclosure;
3. performance: sensitivity and specificity two ways (missing counts as wrong; when
   answered) with 95% Wilson intervals, diameter agreement against the profile's
   tolerances, and Dice against the profile's markers;
4. a stratified table with "Too few" suppression;
5. cases to review;
6. notes, methods and limits;
7. provenance, including every pipeline step and whether it was skipped or failed;
8. the disclaimer.

**Provisional scores are hidden by default.** ADR 0001 (open question 2) says the 0-100
``provisional-v0`` scores must not be shown to a hospital until ratified. Pass
``show_provisional_scores=True`` to show them under a "provisional, not validated" banner.

**The renderer computes no statistics.** The by-group table, the cases-to-review list and
every threshold it prints (minimum group size, size tolerance, Dice markers, check targets)
come from the result itself (``result.strata``, ``result.cases_to_review``,
``result.thresholds``), so a saved ``result.json`` renders the same report as the live run.
A result that lacks one of them (written before slicepoint-core 0.2.0) shows "not
recorded" for it; no default is assumed.
"""

from __future__ import annotations

import ast
import html
import math
import re
from collections.abc import Sequence
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

from slicepoint_schemas.assessment import (
    AssessmentResult,
    CheckRun,
    CheckRunState,
    ReviewCase,
    ReviewReason,
    StepState,
    ToleranceRole,
)
from slicepoint_schemas.checks import DEFAULT_CHECK_REGISTRY, CheckDescriptor, CheckResult, CheckStatus, Evidence
from slicepoint_schemas.checks import CheckRegistry as SchemaCheckRegistry
from slicepoint_schemas.common import SCHEMA_VERSION
from slicepoint_schemas.legacy import BinMetricsV0
from slicepoint_schemas.verdict import VerdictOutcome

from . import __version__
from .stats import MISSING

if TYPE_CHECKING:
    from .assessment import AssessmentReport

DISCLAIMER = (
    "Results come from a test sample, not a full trial. "
    "This report supports a decision and is not medical advice."
)
PROVISIONAL_BANNER = (
    "Provisional scores, not validated. The 0 to 100 scores below use the formula "
    "“provisional-v0” (ADR 0001, open question 2). They have not been ratified and must "
    "not drive a decision. The verdict uses check status only."
)
NOT_RECORDED = "not recorded in this result"

__all__ = [
    "DISCLAIMER",
    "display_site_name",
    "format_n_effective",
    "humanize_column",
    "render_html",
    "render_iframe",
    "summarize",
    "write_html",
]


# --------------------------------------------------------------------------- plain-language copy

_ASKS: dict[str, str] = {
    "repeats": "Does each scan come from a different person, so the numbers are not inflated by repeats?",
    "scanning": "Do your scanners and scan settings look like the ones the model was checked on?",
    "patients": "Do your patients (sex, age, aneurysm size) look like the reference patients?",
    "labels": "Do your aneurysm labels follow the same decision line as the reference?",
    "accuracy": "Does the model find aneurysms and measure the aorta well on your scans?",
}

_MEANS: dict[str, dict[CheckStatus, str]] = {
    "repeats": {
        CheckStatus.OK: "Repeat scans are rare, so the sample size is close to what it looks like.",
        CheckStatus.WATCH: "Some people were scanned more than once; read the accuracy numbers as somewhat optimistic.",
        CheckStatus.PROBLEM: "Many scans come from the same people, so the sample is smaller than it looks and "
                             "accuracy is likely overstated. Use the effective n and remove repeats before relying "
                             "on the accuracy numbers.",
    },
    "scanning": {
        CheckStatus.OK: "Your scans look like the reference scans, so the model sees familiar images.",
        CheckStatus.WATCH: "Some scan settings differ from the reference; check the named settings before relying "
                           "on the model for those scans.",
        CheckStatus.PROBLEM: "Your scans differ clearly from what the model was checked on, so it may perform worse "
                             "here than its published results.",
    },
    "patients": {
        CheckStatus.OK: "Your patient mix is close to the reference.",
        CheckStatus.WATCH: "Your patient mix differs somewhat from the reference; results for the named groups "
                           "carry more uncertainty.",
        CheckStatus.PROBLEM: "Your patients differ clearly from the reference; the model's published accuracy may not "
                             "hold for them.",
    },
    "labels": {
        CheckStatus.OK: "Your labels follow the decision line, so accuracy is measured against a consistent standard.",
        CheckStatus.WATCH: "Some labels disagree with the decision line; the accuracy numbers may be slightly off.",
        CheckStatus.PROBLEM: "Your labels do not follow the decision line consistently. Review the labelling before "
                             "trusting any accuracy number in this report.",
    },
    "accuracy": {
        CheckStatus.OK: "The model performed acceptably on your sample.",
        CheckStatus.WATCH: "The model has weak spots on your data; review the named items and the cases list.",
        CheckStatus.PROBLEM: "The model missed its targets on your data. Do not turn it on without a plan for the "
                             "named problems.",
    },
}
_MEANS_GENERIC: dict[CheckStatus, str] = {
    CheckStatus.OK: "Nothing in this check stands in the way.",
    CheckStatus.WATCH: "This check needs a closer look before deciding.",
    CheckStatus.PROBLEM: "This check found a problem that should be resolved before turning the model on.",
}
_MEANS_NOT_RUN = ("This check did not run, so it cannot support a GO. Supply the missing input and run the "
                  "assessment again.")

_STATUS_LABEL = {CheckStatus.OK: "OK", CheckStatus.WATCH: "Watch", CheckStatus.PROBLEM: "Problem"}
_STATUS_GLYPH = {CheckStatus.OK: "✓", CheckStatus.WATCH: "!", CheckStatus.PROBLEM: "✕"}
_STATUS_CLASS = {CheckStatus.OK: "ok", CheckStatus.WATCH: "watch", CheckStatus.PROBLEM: "problem"}
_SEVERITY_STATUS = {"red": CheckStatus.PROBLEM, "yellow": CheckStatus.WATCH, "ok": CheckStatus.OK}

_VERDICT_LABEL = {VerdictOutcome.GO: "GO", VerdictOutcome.NO_GO: "NO-GO", VerdictOutcome.BORDERLINE: "BORDERLINE"}
_VERDICT_CLASS = {VerdictOutcome.GO: "ok", VerdictOutcome.NO_GO: "problem", VerdictOutcome.BORDERLINE: "watch"}
_VERDICT_GLYPH = {VerdictOutcome.GO: "✓", VerdictOutcome.NO_GO: "✕", VerdictOutcome.BORDERLINE: "!"}

_GROUP_LABEL = {
    "contrast_phase": "Contrast phase",
    "slice_thickness_class": "Slice thickness",
    "sex": "Sex",
    "age_band": "Age group",
    "scanner_vendor": "Scanner brand",
    "aaa_size_class": "Aneurysm size class",
    "patient_id": "Patient",
    "case_id": "Case",
}


def humanize_column(name: str) -> str:
    """A display label for a data column: the label map for known columns, else
    ``some_column_name`` -> ``Some column name``."""
    if name in _GROUP_LABEL:
        return _GROUP_LABEL[name]
    words = name.replace("-", "_").split("_")
    text = " ".join(w for w in words if w)
    return text[:1].upper() + text[1:] if text else name


def display_site_name(site_id: str, site_name: str | None = None) -> str:
    """The name to show for a site: ``site_name`` when given, else the site id made readable
    (``hospital_b`` -> ``Hospital B``)."""
    if site_name and site_name.strip():
        return site_name.strip()
    words = [w for w in re.split(r"[_\-]+", site_id) if w]
    return " ".join(w.upper() if len(w) == 1 else w[:1].upper() + w[1:] for w in words) or site_id


def format_n_effective(v: float) -> str:
    """Effective n as an integer when it is whole (``32``), otherwise to one decimal (``31.4``)."""
    text = f"{v:,.1f}"
    return text[:-2] if text.endswith(".0") else text


# --------------------------------------------------------------------------- small helpers


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pct(v: float | None, dp: int = 0) -> str:
    return "n/a" if v is None else f"{100 * v:.{dp}f}%"


def _mm(v: float | None, dp: int = 1, signed: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.{dp}f} mm" if signed else f"{v:.{dp}f} mm"


def _num(v: object) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        if not math.isfinite(v):
            return "n/a"
        if v == int(v) and abs(v) < 1e6:
            return f"{int(v):,}"
        return f"{v:.3g}" if abs(v) < 1 else f"{v:,.2f}"
    return str(v)


def _pill(cls: str, glyph: str, label: str) -> str:
    # The glyph is decorative; the text label carries the status (colour is never the only signal).
    return f'<span class="pill {cls}"><span aria-hidden="true">{glyph}</span> {_e(label)}</span>'


def _status_pill(status: CheckStatus) -> str:
    return _pill(_STATUS_CLASS[status], _STATUS_GLYPH[status], _STATUS_LABEL[status])


def _ci(m: BinMetricsV0, which: str) -> str:
    if which == "sens":
        p, lo, hi, k, n = m.sens, m.sens_lo, m.sens_hi, m.tp, m.n_aaa
    else:
        p, lo, hi, k, n = m.spec, m.spec_lo, m.spec_hi, m.tn, m.n_not_aaa
    if p is None:
        return "n/a (none in sample)"
    return f"{_pct(p)} ({k}/{n}); 95% CI {_pct(lo)} to {_pct(hi)}"


# --------------------------------------------------------------------------- SVG pieces


def _svg_ci_rows(rows: Sequence[tuple[str, float | None, float | None, float | None]], *, label: str) -> str:
    """Point-and-whisker rows on a 0-100% axis. ``rows`` = (name, point, lo, hi)."""
    left, width, row_h, top = 210, 360, 26, 8
    h = top + row_h * len(rows) + 26
    parts = [f'<svg class="chart" viewBox="0 0 {left + width + 20} {h}" role="img" aria-label="{_e(label)}">',
             f"<title>{_e(label)}</title>"]
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        x = left + width * t
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{h - 22}" class="grid"/>')
        parts.append(f'<text x="{x:.1f}" y="{h - 8}" text-anchor="middle" class="tick">{int(t * 100)}%</text>')
    for i, (name, p, lo, hi) in enumerate(rows):
        y = top + row_h * i + row_h / 2
        parts.append(f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" class="lbl">{_e(name)}</text>')
        if p is None or lo is None or hi is None:
            parts.append(f'<text x="{left + 6}" y="{y + 4:.1f}" class="tick">n/a</text>')
            continue
        x0, x1, xp = left + width * lo, left + width * hi, left + width * p
        parts.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" class="whisker"/>')
        for xe in (x0, x1):
            parts.append(f'<line x1="{xe:.1f}" y1="{y - 5:.1f}" x2="{xe:.1f}" y2="{y + 5:.1f}" class="whisker"/>')
        parts.append(f'<circle cx="{xp:.1f}" cy="{y:.1f}" r="5" class="dot"/>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_share_bar(share: float | None, *, label: str, marker: float | None = None) -> str:
    """A 0-100% horizontal bar with an optional target tick."""
    w, h = 260, 16
    parts = [f'<svg class="bar" viewBox="0 0 {w} {h}" role="img" aria-label="{_e(label)}"><title>{_e(label)}</title>',
             f'<rect x="0" y="2" width="{w}" height="{h - 4}" rx="3" class="track"/>']
    if share is not None:
        parts.append(f'<rect x="0" y="2" width="{w * max(0.0, min(1.0, share)):.1f}" height="{h - 4}" rx="3" '
                     'class="fill"/>')
    if marker is not None:
        x = w * max(0.0, min(1.0, marker))
        parts.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{h}" class="target"/>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_dice_gauge(median: float, mean: float, markers: tuple[float, float] | None) -> str:
    """Dice on a 0.5-1.0 scale with the profile's basic and clinical markers."""
    lo_v, left, width, h = 0.5, 20, 560, 70

    def x(v: float) -> float:
        return left + width * (max(lo_v, min(1.0, v)) - lo_v) / (1.0 - lo_v)

    label = f"Dice median {median:.3f}, mean {mean:.3f}" + (
        f"; markers at {markers[0]:.2f} (basic) and {markers[1]:.2f} (clinical)" if markers else "")
    parts = [f'<svg class="chart" viewBox="0 0 {left * 2 + width} {h}" role="img" aria-label="{_e(label)}">',
             f"<title>{_e(label)}</title>",
             f'<rect x="{left}" y="22" width="{width}" height="12" rx="3" class="track"/>']
    for t in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        parts.append(f'<text x="{x(t):.1f}" y="52" text-anchor="middle" class="tick">{t:.1f}</text>')
    if markers:
        for v, name in ((markers[0], "basic"), (markers[1], "clinical")):
            parts.append(f'<line x1="{x(v):.1f}" y1="16" x2="{x(v):.1f}" y2="40" class="target"/>')
            parts.append(f'<text x="{x(v):.1f}" y="12" text-anchor="middle" class="tick">{name} {v:.2f}</text>')
    parts.append(f'<rect x="{left}" y="22" width="{x(median) - left:.1f}" height="12" rx="3" class="fill"/>')
    parts.append(f'<circle cx="{x(mean):.1f}" cy="28" r="5" class="dot-alt"/>')
    parts.append(f'<text x="{left}" y="66" class="tick">bar = median {median:.3f}; ring = mean {mean:.3f}'
                 f'{"; values under 0.5 sit at the left edge" if min(median, mean) < lo_v else ""}</text>')
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- sections


class _Ctx:
    """Everything the section renderers need, read once from the result (never defaulted)."""

    def __init__(self, result: AssessmentResult, *, show_scores: bool, registry: SchemaCheckRegistry | None) -> None:
        self.r = result
        self.show_scores = show_scores
        self.site = display_site_name(result.site_id, result.site_name)
        self.descriptors: dict[str, CheckDescriptor] = dict((registry or DEFAULT_CHECK_REGISTRY).as_mapping())
        self.results: dict[str, CheckResult] = {c.check_id: c for c in result.verdict.results}
        t = result.thresholds
        self.thresholds = t
        self.decision_line = t.aaa.decision_line_mm if t is not None and t.aaa is not None else None
        self.icc = t.parameters.get("repeat_scan_icc") if t is not None else None
        self.markers = ((t.dice_markers.lower, t.dice_markers.upper)
                        if t is not None and t.dice_markers is not None else None)
        self.targets: dict[str, int] = dict(t.check_targets) if t is not None else {}

    def title(self, check_id: str) -> str:
        d = self.descriptors.get(check_id)
        return d.title if d else check_id

    def sub_title(self, check_id: str, sub: str) -> str:
        d = self.descriptors.get(check_id)
        if d:
            for s in d.sub_factors:
                if s.id == sub:
                    return s.title
        return sub


def _verdict_section(c: _Ctx) -> str:
    v = c.r.verdict
    final = v.final_outcome
    titles = {cid: c.title(cid) for cid in [*c.results, *v.not_evaluated]}
    problems = [titles[r.check_id] for r in v.results if r.status is CheckStatus.PROBLEM]
    watches = [titles[r.check_id] for r in v.results if r.status is CheckStatus.WATCH]
    not_eval = [titles[cid] for cid in v.not_evaluated]
    total = len(c.r.checks)
    if v.outcome is VerdictOutcome.NO_GO:
        sentence = (f"{len(problems)} of {total} checks found a problem ({', '.join(problems)}), so this AI should "
                    "not be turned on for these patients and scanners until those are resolved.")
    elif v.outcome is VerdictOutcome.BORDERLINE:
        bits = []
        if watches:
            bits.append(f"{', '.join(watches)} need{'s' if len(watches) == 1 else ''} a closer look")
        if not_eval:
            bits.append(f"{', '.join(not_eval)} could not be evaluated")
        sentence = (f"No check found a clear problem, but {' and '.join(bits)}, so decide only after a review.")
    else:
        sentence = (f"All {total} checks passed on this sample, so the AI looks like a fit for these patients and "
                    "scanners.")
    parts = [
        '<section id="verdict" class="verdict ' + _VERDICT_CLASS[final] + '" aria-labelledby="verdict-h">',
        '<h2 id="verdict-h">Verdict</h2>',
        '<p class="verdict-line"><span class="verdict-badge">'
        f'<span aria-hidden="true">{_VERDICT_GLYPH[final]}</span> {_VERDICT_LABEL[final]}</span></p>',
        f'<p class="rationale">{_e(sentence)}</p>',
    ]
    counts = {s: sum(1 for r in v.results if r.status is s) for s in CheckStatus}
    parts.append(
        f'<p class="counts">{counts[CheckStatus.PROBLEM]} problem, {counts[CheckStatus.WATCH]} watch, '
        f'{counts[CheckStatus.OK]} ok, {len([x for x in c.r.checks if x.state is not CheckRunState.EVALUATED])} '
        "not evaluated.</p>"
    )
    if v.override is not None:
        o = v.override
        parts.append(
            f'<p class="override"><strong>Human decision:</strong> the derived verdict was '
            f'{_e(_VERDICT_LABEL[v.outcome])}; {_e(o.by)} set it to {_e(_VERDICT_LABEL[o.outcome])} on '
            f'{_e(o.at.isoformat())}. Reason: {_e(o.note)}</p>'
        )
    if not_eval:
        parts.append(f'<p class="warn"><strong>Not evaluated:</strong> {_e(", ".join(not_eval))}. A check that did '
                     "not run never counts as passed.</p>")
    parts.append(f'<p class="disclaimer-short">{_e(DISCLAIMER)}</p>')
    parts.append("</section>")
    return "".join(parts)


_DICT_LITERAL = re.compile(r"\{'[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")


def _readable(text: str) -> str:
    """Rewrite Python dict literals in a finding sentence (e.g. the no-answer breakdown,
    ``{'sex': {'F': 0.117}}``) as ``sex F 12%``. Display only; the stored text is unchanged."""

    def fmt(m: re.Match[str]) -> str:
        try:
            value = ast.literal_eval(m.group(0))
        except (ValueError, SyntaxError):
            return m.group(0)
        if not isinstance(value, dict):
            return m.group(0)
        parts = []
        for k, v in value.items():
            if isinstance(v, dict):
                inner = ", ".join(f"{kk} {_pct(vv) if isinstance(vv, float) else vv}" for kk, vv in v.items())
                parts.append(f"{_GROUP_LABEL.get(str(k), str(k)).lower()} {inner}")
            else:
                parts.append(f"{k} {_pct(v) if isinstance(v, float) else v}")
        return "; ".join(parts)

    return _GROUP_REF.sub(_group_ref, _DICT_LITERAL.sub(fmt, text))


# ``contrast_phase=arterial (n=16)`` or ``sex=F``, as the checks write subgroup names.
_GROUP_REF = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)*)=([^\s,;()]+)(?: \(n=(\d+)\))?")


def _group_ref(m: re.Match[str]) -> str:
    """``contrast_phase=arterial (n=16)`` -> ``Contrast phase: arterial (16 cases)``.

    Only known data columns, or any ``name=level (n=k)``, are rewritten, so text such as
    ``p=0.004`` is left alone."""
    col, level, n = m.group(1), m.group(2), m.group(3)
    if col not in _GROUP_LABEL and n is None:
        return m.group(0)
    tail = ""
    if n is None and level.endswith("."):  # sentence end, not part of the level
        level, tail = level[:-1], "."
    if level == MISSING:
        level = "missing"
    out = f"{humanize_column(col)}: {level}"
    if n is not None:
        out += f" ({int(n):,} case{'' if int(n) == 1 else 's'})"
    return out + tail


def _findings(res: CheckResult) -> list[tuple[CheckStatus, str]]:
    out = []
    for ev in res.evidence:
        if "." in ev.key or ev.text is None or not isinstance(ev.value, str) or ev.value not in _SEVERITY_STATUS:
            continue
        out.append((_SEVERITY_STATUS[ev.value], _readable(ev.text)))
    return out


def _is_score_evidence(ev: Evidence) -> bool:
    return ev.key == "score_basis" or ev.key.startswith("score_part.") or ev.key.startswith("score.")


def _evidence_table(res: CheckResult, show_scores: bool) -> str:
    rows = []
    for ev in res.evidence:
        if not show_scores and _is_score_evidence(ev):
            continue
        if ev.key == "failing_factor_without_sub_factor":
            continue
        value = _readable(ev.value) if isinstance(ev.value, str) else _num(ev.value)
        if ev.unit:
            value += f" {ev.unit}"
        text = f'<span class="muted">{_e(ev.text)}</span>' if ev.text and ev.key == "not_evaluated" else ""
        rows.append(f"<tr><th scope=\"row\"><code>{_e(ev.key)}</code></th><td>{_e(value)} {text}</td></tr>")
    if not rows:
        return ""
    return ('<details><summary>Show the numbers</summary><div class="scroll"><table class="evidence">'
            '<thead><tr><th scope="col">Item</th><th scope="col">Value</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div></details>")


def _check_card(c: _Ctx, run: CheckRun) -> str:
    cid = run.check_id
    title = c.title(cid)
    asks = _ASKS.get(cid) or (c.descriptors[cid].definition if cid in c.descriptors else "")
    head = [f'<article class="card" id="check-{_e(cid)}" data-check-id="{_e(cid)}" aria-labelledby="h-{_e(cid)}">']
    if run.state is not CheckRunState.EVALUATED:
        label = "Not evaluated" if run.state is CheckRunState.SKIPPED else "Failed"
        cls = "skip" if run.state is CheckRunState.SKIPPED else "problem"
        glyph = "–" if run.state is CheckRunState.SKIPPED else "✕"
        head += [
            f'<header><h3 id="h-{_e(cid)}">{_e(title)}</h3>{_pill(cls, glyph, label)}</header>',
            f'<p class="asks">{_e(asks)}</p>',
            f'<p><strong>Why:</strong> {_e(run.reason or "")}</p>',
            f'<p class="means"><strong>What this means:</strong> {_e(_MEANS_NOT_RUN)}</p>',
            "</article>",
        ]
        return "".join(head)
    res = c.results[cid]
    n_line = f"Based on {res.n:,} scans"
    if res.subjects is not None:
        n_line += f" from {res.subjects:,} people"
    if res.n_effective is not None:
        n_line += f"; effective n {format_n_effective(res.n_effective)}"
    head += [
        f'<header><h3 id="h-{_e(cid)}">{_e(title)}</h3>{_status_pill(res.status)}</header>',
        f'<p class="asks">{_e(asks)}</p>',
        f'<p class="n">{_e(n_line)}.</p>',
    ]
    if res.failing_sub_factors:
        items = "".join(f"<li>{_e(c.sub_title(cid, s))}</li>" for s in res.failing_sub_factors)
        head.append(f'<div class="failing"><strong>Failing sub-factors:</strong><ul>{items}</ul></div>')
    flagged = [(s, t) for s, t in _findings(res) if s is not CheckStatus.OK]
    if flagged:
        head.append('<ul class="findings">' + "".join(
            f'<li><span class="sev {_STATUS_CLASS[s]}">{_STATUS_LABEL[s]}:</span> {_e(t)}</li>' for s, t in flagged
        ) + "</ul>")
    else:
        head.append(f'<p class="findings-none">{_e(_readable(res.summary or "Nothing to flag."))}</p>')
    means = _MEANS.get(cid, _MEANS_GENERIC)[res.status]
    head.append(f'<p class="means"><strong>What this means:</strong> {_e(means)}</p>')
    if c.show_scores and res.score is not None:
        target = c.targets.get(cid)
        tgt = f" (target {target})" if target is not None else ""
        head.append(
            f'<div class="score"><span>Provisional score: <strong>{res.score:.0f}</strong> / 100{_e(tgt)} '
            f'<span class="muted">[{_e(res.score_method or "")}, not validated]</span></span>'
            + _svg_share_bar(res.score / 100, label=f"Provisional score {res.score:.0f} of 100{tgt}",
                             marker=None if target is None else target / 100)
            + "</div>"
        )
    head.append(_evidence_table(res, c.show_scores))
    head.append("</article>")
    return "".join(head)


def _checks_section(c: _Ctx) -> str:
    cards = "".join(_check_card(c, run) for run in c.r.checks)
    return ('<section id="checks" aria-labelledby="checks-h"><h2 id="checks-h">Health checks</h2>'
            '<p class="lead">Each check compares your data with the reference. Status is Problem, Watch or OK; '
            "a check that could not run is shown as Not evaluated and never counts as passed. "
            "<em>n</em> is the number of scans the check used; <em>effective n</em> discounts repeat scans of "
            "the same person.</p>"
            f'<div class="cards">{cards}</div></section>')


def _performance_section(c: _Ctx) -> str:
    perf = c.r.performance
    parts = ['<section id="performance" aria-labelledby="perf-h"><h2 id="perf-h">AI performance on your sample</h2>']
    wrong, answered = perf.aaa_missing_as_wrong, perf.aaa_when_answered
    if wrong is None or answered is None:
        parts.append('<p class="warn">Not evaluated: needs both labels and model predictions.</p>')
    else:
        parts += [
            '<h3>Finding aneurysms (AAA yes or no)</h3>',
            '<p class="lead">The primary numbers count a missing AI answer as wrong. The "when answered" numbers '
            f"leave out the {wrong.n_no_answer} scan(s) with no answer. Ranges are 95% Wilson intervals.</p>",
            '<div class="scroll"><table><thead><tr><th scope="col">Measure</th>'
            '<th scope="col">Missing counts as wrong (primary)</th><th scope="col">When answered</th></tr></thead>'
            "<tbody>",
            f'<tr><th scope="row">Sensitivity (aneurysms caught)</th><td>{_e(_ci(wrong, "sens"))}</td>'
            f'<td>{_e(_ci(answered, "sens"))}</td></tr>',
            f'<tr><th scope="row">Specificity (normals called normal)</th><td>{_e(_ci(wrong, "spec"))}</td>'
            f'<td>{_e(_ci(answered, "spec"))}</td></tr>',
            f'<tr><th scope="row">Balanced accuracy</th><td>{_e(_pct(wrong.bal_acc))}</td>'
            f'<td>{_e(_pct(answered.bal_acc))}</td></tr>',
            f'<tr><th scope="row">Scans</th><td>{wrong.n} ({wrong.n_aaa} aneurysm, {wrong.n_not_aaa} not; '
            f'{wrong.n_no_answer} no answer)</td><td>{answered.n}</td></tr>',
            "</tbody></table></div>",
            _svg_ci_rows(
                [
                    ("Sensitivity, primary", wrong.sens, wrong.sens_lo, wrong.sens_hi),
                    ("Sensitivity, when answered", answered.sens, answered.sens_lo, answered.sens_hi),
                    ("Specificity, primary", wrong.spec, wrong.spec_lo, wrong.spec_hi),
                    ("Specificity, when answered", answered.spec, answered.spec_lo, answered.spec_hi),
                ],
                label="Sensitivity and specificity with 95% Wilson intervals",
            ),
        ]
    dm = perf.diameter
    parts.append("<h3>Measuring the aorta (AI minus label)</h3>")
    if dm is None:
        parts.append('<p class="warn">Not evaluated: needs labelled and predicted diameters.</p>')
    elif dm.mae is None:
        parts.append(f"<p>Too few paired measurements ({dm.n}; at least {dm.min_n} needed).</p>")
    else:
        parts.append(
            '<div class="scroll"><table><tbody>'
            f'<tr><th scope="row">Pairs</th><td>{dm.n}</td></tr>'
            f'<tr><th scope="row">Average difference (bias)</th><td>{_e(_mm(dm.bias, 2, signed=True))}</td></tr>'
            f'<tr><th scope="row">95% limits of agreement</th><td>{_e(_mm(dm.loa_low, 1, True))} to '
            f'{_e(_mm(dm.loa_high, 1, True))} (bias &plusmn; 1.96 &times; population SD {_e(_mm(dm.sd, 2))})</td></tr>'
            f'<tr><th scope="row">Mean absolute error</th><td>{_e(_mm(dm.mae, 2))} (RMSE {_e(_mm(dm.rmse, 2))})</td></tr>'
            f'<tr><th scope="row">Spearman correlation</th><td>{_e(_num(dm.spearman))}</td></tr>'
            "</tbody></table></div>"
        )
        role_name = {ToleranceRole.BLAND_ALTMAN: "agreement tolerance", ToleranceRole.SIZE: "size tolerance"}
        rows = []
        for w in sorted(dm.within_tolerance, key=lambda w: w.tolerance_mm):
            lbl = f"Within {w.tolerance_mm:g} mm ({role_name[w.role]} from the profile)"
            rows.append(f'<div class="barrow"><span class="barlabel">{_e(lbl)}</span>'
                        + _svg_share_bar(w.share, label=f"{lbl}: {_pct(w.share)}")
                        + f'<span class="barval">{_e(_pct(w.share))}</span></div>')
        parts.append('<div class="bars">' + "".join(rows) + "</div>")
    parts.append("<h3>Outline quality (Dice)</h3>")
    dice = perf.dice
    if dice is None:
        parts.append('<p class="warn">Not evaluated: no Dice values in the predictions.</p>')
    else:
        parts.append(
            f"<p>Median {dice.median:.3f}, mean {dice.mean:.3f}; {_e(_pct(dice.share_below_0_90))} of scans below "
            f"0.90 and {_e(_pct(dice.share_below_0_85))} below 0.85.</p>"
            + _svg_dice_gauge(dice.median, dice.mean, c.markers)
        )
    parts.append("</section>")
    return "".join(parts)


def _strata_section(c: _Ctx) -> str:
    st = c.r.strata
    head = '<section id="strata" aria-labelledby="strata-h"><h2 id="strata-h">Results by group</h2>'
    if st is None:
        return head + f'<p class="warn">No by-group table: {_e(NOT_RECORDED)}.</p></section>'
    head += (f'<p class="lead">Groups with fewer than {st.min_group_size} scans show "Too few": their numbers would '
             f"be noise. Sensitivity needs at least {st.min_aaa_for_sensitivity} aneurysms in the group. Size "
             f"tolerance {st.size_tolerance_mm:g} mm.</p>")
    if not st.rows:
        return head + '<p class="warn">No groups to show.</p></section>'
    body = []
    current = None
    for r in st.rows:
        if r.variable != current:
            current = r.variable
            body.append(f'<tr class="group"><th scope="rowgroup" colspan="7">'
                        f'{_e(humanize_column(r.variable))}</th></tr>')
        lvl = "missing" if r.level == MISSING else r.level
        if r.too_few:
            body.append(f'<tr><th scope="row">{_e(lvl)}</th><td>{r.n}</td><td>{r.people}</td>'
                        f'<td colspan="4" class="toofew">Too few (fewer than {st.min_group_size} scans)</td></tr>')
            continue
        metrics = (f"<td>{_e(_mm(r.bias_mm, 2, True))}</td><td>{_e(_mm(r.mae_mm, 2))}</td>"
                   f"<td>{_e(_pct(r.within_tolerance))}</td>")
        if r.sens_too_few:
            why = "no aneurysms" if r.n_aaa == 0 else f"{r.n_aaa} aneurysm{'s' if r.n_aaa != 1 else ''}"
            sens = f'<td class="toofew">Too few ({why})</td>'
        else:
            sens = f"<td>{_e(_pct(r.sens))} ({_e(_pct(r.sens_lo))} to {_e(_pct(r.sens_hi))})</td>"
        body.append(f'<tr><th scope="row">{_e(lvl)}</th><td>{r.n}</td><td>{r.people}</td>{metrics}{sens}</tr>')
    return (head + '<div class="scroll"><table class="strata"><thead><tr><th scope="col">Group</th>'
            '<th scope="col">Scans</th><th scope="col">People</th><th scope="col">Bias</th>'
            f'<th scope="col">MAE</th><th scope="col">Within {st.size_tolerance_mm:g} mm</th>'
            '<th scope="col">Sensitivity (95% CI)</th></tr></thead><tbody>'
            + "".join(body) + "</tbody></table></div></section>")


_MAX_CASES = 40


def _reason_text(k: ReviewCase, reason: ReviewReason, tolerance_mm: float) -> str:
    if reason is ReviewReason.SIZE_ERROR and k.error_mm is not None:
        return f"Size off by {k.error_mm:+.1f} mm (tolerance {tolerance_mm:g} mm)"
    return {
        ReviewReason.MISSED_ANEURYSM: "Missed aneurysm",
        ReviewReason.NO_ANSWER_ON_ANEURYSM: "No AI answer on a labelled aneurysm",
        ReviewReason.NO_ANSWER: "No AI answer",
        ReviewReason.SIZE_ERROR: "Size off",
        ReviewReason.FALSE_ALARM: "False alarm",
    }[reason]


def _cases_section(c: _Ctx) -> str:
    cr = c.r.cases_to_review
    head = '<section id="cases" aria-labelledby="cases-h"><h2 id="cases-h">Cases to review</h2>'
    if cr is None:
        return head + f'<p class="warn">No cases-to-review list: {_e(NOT_RECORDED)}.</p></section>'
    tol = cr.size_tolerance_mm
    head += ("<p class=\"lead\">Scans where the AI missed an aneurysm, gave no answer, measured the aorta outside "
             f"the {tol:g} mm size tolerance, or raised a false alarm. Open these in your viewer first.</p>")
    cases = cr.cases
    if not cases:
        return head + "<p>No scans need review on these rules.</p></section>"

    def yn(v: bool | None) -> str:
        return "no answer" if v is None else ("AAA" if v else "no AAA")

    rows = []
    for k in cases[:_MAX_CASES]:
        why = "; ".join(_reason_text(k, r, tol) for r in k.reasons)
        rows.append(
            f'<tr><th scope="row"><code>{_e(k.case_id)}</code></th><td>{_e(k.person_group)}</td>'
            f'<td>{_e(why)}</td><td>{_e("n/a" if k.aaa is None else yn(k.aaa))}</td>'
            f"<td>{_e(yn(k.ai_aaa))}</td><td>{_e(_mm(k.reference_diameter_mm))}</td>"
            f"<td>{_e(_mm(k.ai_diameter_mm))}</td><td>{_e(_mm(k.error_mm, 1, True))}</td></tr>"
        )
    more = (f'<p class="muted">{len(cases) - _MAX_CASES} more case(s) not shown; all are in result.json.</p>'
            if len(cases) > _MAX_CASES else "")
    return (head + f"<p>{len(cases)} of {cr.n_scans} scans flagged.</p>"
            '<div class="scroll"><table class="cases"><thead><tr><th scope="col">Case</th>'
            '<th scope="col">Person</th><th scope="col">Why</th><th scope="col">Label</th>'
            '<th scope="col">AI call</th><th scope="col">Label size</th><th scope="col">AI size</th>'
            '<th scope="col">Difference</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
            + more + "</section>")


def _notes_section(c: _Ctx) -> str:
    if not c.r.notes:
        return ""
    items = "".join(f"<li>{_e(_readable(n))}</li>" for n in c.r.notes)
    return f'<section id="notes" aria-labelledby="notes-h"><h2 id="notes-h">Notes from the run</h2><ul>{items}</ul></section>'


def _methods_section(c: _Ctx) -> str:
    ref = c.r.reference
    line = f"{c.decision_line:g} mm" if c.decision_line is not None else f"decision line {NOT_RECORDED}"
    icc = f" (ICC {c.icc:g})" if c.icc is not None else ""
    methods = [
        "The reference standard is your hospital's own labels and measurements, not an independent read.",
        "Primary sensitivity and specificity count a missing AI answer as wrong; the secondary "
        "“when answered” pair leaves those scans out.",
        "All ranges for proportions are 95% Wilson score intervals.",
        "Agreement uses AI minus label; the standard deviation divides by n (population SD).",
        (f"Groups with fewer than {c.r.strata.min_group_size} scans are shown as “Too few”; sensitivity needs at "
         f"least {c.r.strata.min_aaa_for_sensitivity} aneurysms. These rules count scans, not people."
         if c.r.strata is not None else f"By-group suppression rules: {NOT_RECORDED}."),
        f"Effective n is Kish's design-effect sample size over real people{icc}: repeat scans of one person "
        "carry less information than scans of different people.",
    ]
    limits = [
        f"The reference is “{ref.reference_id}”, built from site “{ref.site_id}” "
        f"({ref.n_cases} cases). A fit check is only as good as its reference; ask the vendor for the model's own "
        "training or validation distribution.",
        "The verdict rule is status-based: any Problem gives NO-GO, any Watch or check not run gives BORDERLINE, "
        "otherwise GO. It was inferred from the proof-of-concept and is pending ratification.",
        f"The label rule ({line}) is specific to abdominal aortic aneurysm; the other checks apply to imaging AI "
        "generally.",
        "Input today is a curated set of four parquet files. Readers for raw DICOM or PACS exports are not built yet.",
        "This is a sample, not a trial: wide intervals mean the data cannot settle the question either way.",
    ]
    if not c.show_scores:
        limits.append("0 to 100 check scores exist only as an unvalidated draft and are not shown in this report.")
    return ('<section id="methods" aria-labelledby="methods-h"><h2 id="methods-h">Methods and limits</h2>'
            "<h3>Methods</h3><ol>" + "".join(f"<li>{_e(m)}</li>" for m in methods) + "</ol>"
            "<h3>Limits</h3><ul>" + "".join(f"<li>{_e(m)}</li>" for m in limits) + "</ul></section>")


def _provenance_section(c: _Ctx) -> str:
    r = c.r
    ref = r.reference
    items: list[tuple[str, str]] = [
        ("Site", c.site if c.site == r.site_id else f"{c.site} (site id {r.site_id})"),
        ("Reference profile", f"{ref.reference_id} (site {ref.site_id}, {ref.n_cases} cases)"),
        ("Reference fingerprint", ref.fingerprint or "n/a"),
        ("Threshold profile", r.profile_id),
        ("Model", r.model_id),
        ("Embedding space", r.embedding_space_id or "none"),
        ("Dataset fingerprint", r.dataset_fingerprint or "n/a"),
        ("Schema version", r.schema_version),
        ("Generated at", r.generated_at.isoformat()),
        ("Generated by", r.generator),
        ("Report rendered by", f"slicepoint-core {__version__} (schema {SCHEMA_VERSION})"),
        ("Verdict rule", r.verdict.rationale),
    ]
    if c.thresholds is None:
        items.append(("Thresholds", f"The threshold values were {NOT_RECORDED} (written before slicepoint-core "
                                    "0.2.0); the report shows them as not recorded and assumes none."))
    dl = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in items)
    step_cls = {StepState.OK: ("ok", "✓", "Ran"), StepState.SKIPPED: ("skip", "–", "Skipped"),
                StepState.FAILED: ("problem", "✕", "Failed")}
    rows = []
    for s in r.steps:
        cls, glyph, label = step_cls[s.state]
        rows.append(f'<tr class="step-{s.state.value}"><th scope="row"><code>{_e(s.step)}</code></th>'
                    f"<td>{_pill(cls, glyph, label)}</td><td>{_e(s.detail or '')}</td></tr>")
    n_skip = sum(1 for s in r.steps if s.state is StepState.SKIPPED)
    n_fail = sum(1 for s in r.steps if s.state is StepState.FAILED)
    return ('<section id="provenance" aria-labelledby="prov-h"><h2 id="prov-h">Provenance</h2>'
            f'<dl class="prov">{dl}</dl>'
            f"<h3>Pipeline steps</h3><p>{len(r.steps)} steps: {n_skip} skipped, {n_fail} failed. A skipped step "
            "never counts as passed.</p>"
            '<div class="scroll"><table class="steps"><thead><tr><th scope="col">Step</th><th scope="col">State'
            '</th><th scope="col">Detail</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
            "</section>")


# --------------------------------------------------------------------------- page

_CSS = """
:root{color-scheme:light dark;--bg:#ffffff;--fg:#1b1e23;--muted:#56606e;--border:#d5dae1;--card:#f6f7f9;
--accent:#1f4f99;--track:#e2e6ec;--fill:#1f4f99;--target:#1b1e23;
--ok:#17663a;--ok-bg:#e3f2e8;--watch:#7a4f00;--watch-bg:#fff1cc;--problem:#a01d17;--problem-bg:#fbe4e2;
--skip:#3f4650;--skip-bg:#e8ebef}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--fg:#e7e9ec;--muted:#a7afba;--border:#343a43;--card:#1b1e23;
--accent:#8fb6ff;--track:#2c3139;--fill:#8fb6ff;--target:#e7e9ec;
--ok:#8ee0a9;--ok-bg:#163a24;--watch:#f5c860;--watch-bg:#3a2e0f;--problem:#ffa39b;--problem-bg:#46201d;
--skip:#c9ced6;--skip-bg:#2a2f36}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,
"Helvetica Neue",Arial,sans-serif}
main{max-width:1120px;margin:0 auto;padding:16px}
h1{font-size:1.6rem;margin:.2rem 0}
h2{font-size:1.3rem;margin:2rem 0 .6rem;padding-bottom:.25rem;border-bottom:1px solid var(--border)}
h3{font-size:1.05rem;margin:1.2rem 0 .4rem}
.sub,.muted,.lead,.asks,.n{color:var(--muted)}
.lead{max-width:75ch}
code{font:0.85em/1.3 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;word-break:break-all}
nav ul{list-style:none;padding:0;margin:.6rem 0 0;display:flex;flex-wrap:wrap;gap:.3rem 1rem}
a{color:var(--accent)}
.pill{display:inline-flex;align-items:center;gap:.3em;padding:.1em .6em;border-radius:999px;font-weight:600;
font-size:.85rem;white-space:nowrap;border:1px solid currentColor}
.pill.ok,.sev.ok{color:var(--ok);background:var(--ok-bg)}
.pill.watch,.sev.watch{color:var(--watch);background:var(--watch-bg)}
.pill.problem,.sev.problem{color:var(--problem);background:var(--problem-bg)}
.pill.skip{color:var(--skip);background:var(--skip-bg)}
.sev{font-weight:600;padding:0 .25em;border-radius:3px}
.verdict{border:2px solid currentColor;border-radius:10px;padding:4px 18px 10px;margin-top:1rem}
.verdict h2{border:0;margin:.6rem 0 0;font-size:1rem;text-transform:uppercase;letter-spacing:.05em}
.verdict.ok{color:var(--ok);background:var(--ok-bg)}
.verdict.watch{color:var(--watch);background:var(--watch-bg)}
.verdict.problem{color:var(--problem);background:var(--problem-bg)}
.verdict p{color:var(--fg)}
.verdict .verdict-line{margin:.2rem 0}
.verdict-badge{font-size:2rem;font-weight:800;letter-spacing:.02em}
.verdict .verdict-line,.verdict .verdict-badge{color:inherit}
.rationale{font-size:1.1rem;max-width:80ch;margin:.3rem 0}
.counts,.disclaimer-short{font-size:.9rem}
.warn{border-left:4px solid var(--watch);padding:.3rem .7rem;background:var(--watch-bg)}
.banner{border:2px dashed var(--watch);background:var(--watch-bg);color:var(--fg);padding:.6rem 1rem;
border-radius:8px;margin-top:1rem;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 14px;
display:flex;flex-direction:column;gap:.15rem;min-width:0}
.card header{display:flex;justify-content:space-between;align-items:flex-start;gap:.6rem}
.card h3{margin:0;font-size:1.08rem}
.card p{margin:.25rem 0}
.card ul{margin:.2rem 0 .2rem 1.1rem;padding:0}
.findings li{margin:.2rem 0}
.failing ul{margin-top:0}
.means{border-top:1px solid var(--border);padding-top:.4rem;margin-top:.4rem!important}
.score{display:flex;flex-direction:column;gap:.2rem;margin:.3rem 0}
details{margin-top:.3rem}
summary{cursor:pointer;color:var(--accent)}
.scroll{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;width:100%;margin:.4rem 0;font-size:.92rem}
th,td{text-align:left;padding:.3rem .55rem;border-bottom:1px solid var(--border);vertical-align:top}
thead th{border-bottom:2px solid var(--border);white-space:nowrap}
tbody th{font-weight:600}
table.evidence th{font-weight:400}
table.strata td,table.cases td{white-space:nowrap}
table.cases td:nth-child(3){white-space:normal;min-width:14rem}
tr.group th{background:var(--card);padding-top:.5rem}
.toofew{color:var(--muted);font-style:italic}
tr.step-skipped td,tr.step-failed td,tr.step-skipped th,tr.step-failed th{background:var(--card)}
.chart{width:100%;max-width:640px;height:auto;display:block;margin:.4rem 0}
.bar{width:260px;max-width:100%;height:16px;display:block}
.bars{display:grid;grid-template-columns:max-content 260px max-content;align-items:center;gap:.35rem .8rem;margin:.4rem 0}
.barrow{display:contents}
.barval{font-weight:600}
svg .grid{stroke:var(--border);stroke-width:1}
svg .tick{fill:var(--muted);font-size:11px}
svg .lbl{fill:var(--fg);font-size:12px}
svg .whisker{stroke:var(--fg);stroke-width:2}
svg .dot{fill:var(--fill)}
svg .dot-alt{fill:var(--bg);stroke:var(--fg);stroke-width:2}
svg .track{fill:var(--track)}
svg .fill{fill:var(--fill)}
svg .target{stroke:var(--target);stroke-width:2}
dl.prov{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem;margin:.4rem 0}
dl.prov dt{font-weight:600}
dl.prov dd{margin:0;word-break:break-word}
footer{margin:2.5rem 0 1rem;padding-top:.8rem;border-top:1px solid var(--border)}
.disclaimer{font-weight:600}
@media (max-width:600px){dl.prov{grid-template-columns:1fr}dl.prov dd{margin-bottom:.4rem}
.bars{grid-template-columns:1fr;gap:.1rem}.bars .barval{margin-bottom:.4rem}
.verdict-badge{font-size:1.6rem}}
@media print{
:root{--bg:#fff;--fg:#000;--muted:#333;--border:#999;--card:#fff;--accent:#000;--track:#ddd;--fill:#333;--target:#000;
--ok:#0b4d26;--ok-bg:#fff;--watch:#5c3b00;--watch-bg:#fff;--problem:#7d120d;--problem-bg:#fff;--skip:#333;--skip-bg:#fff}
body{font-size:9.5pt;line-height:1.4}
#checks .lead,.verdict .counts{display:none}
h2{margin-top:.6rem}
.verdict{padding:2px 12px 4px}
main{max-width:none;padding:0}
nav,details,.noprint{display:none!important}
h2{margin-top:1rem}
.cards{display:block;columns:2;column-gap:10px}
.card{display:block;margin:0 0 8px;padding:6px 9px}
.card .asks,.card .findings,.card .findings-none{display:none}
.card,.verdict,tr,.bars,svg{break-inside:avoid}
.verdict-badge{font-size:1.5rem}
#performance{break-before:page}
a{color:inherit;text-decoration:none}
.scroll{overflow:visible}
}
"""

_PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<meta name="referrer" content="no-referrer">
<meta name="generator" content="$generator">
<title>$title</title>
<style>$css</style>
</head>
<body>
<main>
<header class="page">
<h1>SlicePoint fit check: $site</h1>
<p class="sub">$subtitle</p>
<nav aria-label="Sections"><ul>
<li><a href="#verdict">Verdict</a></li><li><a href="#checks">Checks</a></li>
<li><a href="#performance">Performance</a></li><li><a href="#strata">By group</a></li>
<li><a href="#cases">Cases to review</a></li><li><a href="#methods">Methods and limits</a></li>
<li><a href="#provenance">Provenance</a></li></ul></nav>
</header>
$banner
$verdict
$checks
$performance
$strata
$cases
$notes
$methods
$provenance
<footer>
<p class="disclaimer">$disclaimer</p>
<p class="muted">Generated on this computer by slicepoint-core. This file makes no network requests and sends nothing
anywhere. To save a PDF, use your browser's Print and choose Save as PDF.</p>
</footer>
</main>
</body>
</html>
""")


def render_html(
    result: AssessmentResult | AssessmentReport,
    *,
    show_provisional_scores: bool = False,
    registry: SchemaCheckRegistry | None = None,
) -> str:
    """Render one self-contained HTML document for ``result``.

    Everything shown comes from ``result``: the thresholds (``result.thresholds``), the
    by-group table and the cases to review. Nothing is recomputed or defaulted.
    ``registry`` gives check titles and sub-factor names for checks beyond the default five.
    """
    res: AssessmentResult = result if isinstance(result, AssessmentResult) else result.result
    c = _Ctx(res, show_scores=show_provisional_scores, registry=registry)
    banner = (f'<div class="banner" role="note" id="provisional-banner">{_e(PROVISIONAL_BANNER)}</div>'
              if show_provisional_scores else "")
    subtitle = (f"{c.site} (site id {res.site_id}) compared with reference {res.reference.reference_id} "
                f"(site {res.reference.site_id}) for model {res.model_id}, threshold profile {res.profile_id}. "
                f"Generated {res.generated_at.strftime('%Y-%m-%d %H:%M %Z').strip()}.")
    return _PAGE.substitute(
        generator=_e(f"slicepoint-core {__version__}"),
        title=_e(f"SlicePoint report: {c.site}"),
        css=_CSS,
        site=_e(c.site),
        subtitle=_e(subtitle),
        banner=banner,
        verdict=_verdict_section(c),
        checks=_checks_section(c),
        performance=_performance_section(c),
        strata=_strata_section(c),
        cases=_cases_section(c),
        notes=_notes_section(c),
        methods=_methods_section(c),
        provenance=_provenance_section(c),
        disclaimer=_e(DISCLAIMER),
    )


def write_html(
    result: AssessmentResult | AssessmentReport,
    path: str | Path,
    *,
    show_provisional_scores: bool = False,
    registry: SchemaCheckRegistry | None = None,
) -> Path:
    """Render and write the report to ``path`` (UTF-8). Returns the path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render_html(result, show_provisional_scores=show_provisional_scores, registry=registry),
        encoding="utf-8",
    )
    return out


def render_iframe(
    result: AssessmentResult | AssessmentReport,
    *,
    height_px: int = 900,
    show_provisional_scores: bool = False,
) -> str:
    """The report inside an ``<iframe srcdoc>``, for ``IPython.display.HTML`` in a notebook.

    The iframe keeps the report's page styles from restyling the notebook, and the
    report's own Content-Security-Policy still applies inside it.
    """
    doc = render_html(result, show_provisional_scores=show_provisional_scores)
    return (f'<iframe title="SlicePoint report" srcdoc="{html.escape(doc, quote=True)}" '
            f'style="width:100%;height:{int(height_px)}px;border:1px solid #ccc;border-radius:6px" '
            'sandbox=""></iframe>')


def summarize(
    result: AssessmentResult | AssessmentReport, *, show_provisional_scores: bool = False
) -> dict[str, object]:
    """A compact, JSON-ready summary: verdict, one row per check, skipped/failed steps.

    This is what ``slicepoint assess --json`` prints (plus ``outputs`` and ``exit_code``)
    and what the quickstart notebook shows as its check table. A check that did not run
    has ``status`` ``skipped`` or ``failed``, ``n`` null and a ``reason``; it never reads
    as ok. Provisional scores are included only with ``show_provisional_scores``.
    """
    res: AssessmentResult = result if isinstance(result, AssessmentResult) else result.result
    titles = {d.id: d.title for d in DEFAULT_CHECK_REGISTRY.checks}
    by_id = {r.check_id: r for r in res.verdict.results}
    checks: list[dict[str, object]] = []
    for run in res.checks:
        r = by_id.get(run.check_id)
        item: dict[str, object] = {"id": run.check_id, "title": titles.get(run.check_id, run.check_id)}
        if r is None:
            item.update(status=run.state.value, n=None, n_effective=None, failing_sub_factors=[],
                        reason=run.reason)
        else:
            item.update(status=r.status.value, n=r.n, n_effective=r.n_effective,
                        failing_sub_factors=list(r.failing_sub_factors))
            if show_provisional_scores:
                item.update(provisional_score=r.score, score_method=r.score_method)
        checks.append(item)
    v = res.verdict
    return {
        "site_id": res.site_id,
        "reference_id": res.reference.reference_id,
        "profile_id": res.profile_id,
        "verdict": v.final_outcome.value,
        "verdict_rationale": v.rationale,
        "not_evaluated": list(v.not_evaluated),
        "checks": checks,
        "skipped_steps": [st.step for st in res.steps if st.state is StepState.SKIPPED],
        "failed_steps": [st.step for st in res.steps if st.state is StepState.FAILED],
    }
