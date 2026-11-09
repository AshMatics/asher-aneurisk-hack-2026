"""The local, in-process assessment runner (ADR 0001 sections 5 and 9).

``Assessment(dataset, reference, profile).run()`` executes a fixed, sequential list of
steps. Each step records ``ok``, ``skipped`` (an input or service is missing) or
``failed`` (it raised), and the run returns an :class:`AssessmentReport` wrapping the
versioned :class:`~slicepoint_schemas.assessment.AssessmentResult`. There is no
orchestration engine yet; this runner is deliberately trivial.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from slicepoint_schemas.assessment import (
    AssessmentResult,
    CasesToReview,
    CheckRun,
    CheckRunState,
    PerformanceSummary,
    ReferenceRef,
    ScanSummary,
    StepRecord,
    StepState,
    Strata,
)
from slicepoint_schemas.checks import CheckResult
from slicepoint_schemas.ingestion import CuratedDataset
from slicepoint_schemas.thresholds import HACKATHON_DEFAULT_PROFILE, ThresholdProfile
from slicepoint_schemas.verdict import Verdict, derive_verdict

from . import __version__
from .checks.builtin import default_registry
from .checks.context import CheckContext, Finding
from .checks.registry import CheckRegistry, CheckSkipped, evaluate, missing_requirements
from .ingestion import TabularDataset
from .params import MissingThresholdError
from .ports import SEGMENTATION, ServicePort
from .reference import ReferenceProfile
from .strata import cases_to_review, stratified_table

_log = logging.getLogger(__name__)

_SCORE_EVIDENCE_PREFIXES = ("score_part.", "score.")
_SCORE_KEYS: dict[str, Any] = {"verdict": {"results": {"__all__": {"score", "score_method"}}}}


def strip_provisional_scores(
    result: AssessmentResult, *, context: Mapping[str, object] | None = None
) -> AssessmentResult:
    """A copy of ``result`` without the provisional 0-100 scores.

    Removes ``score`` and ``score_method`` from every check result, and the evidence that
    spells a score out (``score_basis``, ``score_part.*``, ``score.*``). ADR 0001 open
    question 2: the ``provisional-v0`` scores must not reach a hospital until ratified.
    The verdict never uses scores, so it is unchanged. ``context`` is the validation
    context of the registry that produced ``result`` (needed for checks beyond the
    default five).
    """
    data = result.model_dump(mode="python")
    for r in data["verdict"]["results"]:
        r["score"] = None
        r["score_method"] = None
        r["evidence"] = [
            e for e in r["evidence"]
            if e["key"] != "score_basis" and not e["key"].startswith(_SCORE_EVIDENCE_PREFIXES)
        ]
    return AssessmentResult.model_validate(data, context=dict(context) if context is not None else None)


@dataclass
class AssessmentReport:
    """What :meth:`Assessment.run` returns: the contract result plus convenience views."""

    result: AssessmentResult
    findings: Mapping[str, list[Finding]] = field(default_factory=dict)
    """Per-check findings in notebook order (for the legacy export and the parity suite)."""
    validation_context: Mapping[str, object] | None = None
    """The check registry's validation context (for re-validating results with extra checks)."""

    @property
    def verdict(self) -> Verdict:
        return self.result.verdict

    @property
    def checks(self) -> dict[str, CheckResult]:
        return {r.check_id: r for r in self.result.verdict.results}

    @property
    def performance(self) -> PerformanceSummary:
        return self.result.performance

    def export(self, *, show_provisional_scores: bool = False) -> AssessmentResult:
        """The result as it should leave this process.

        By default the provisional 0-100 scores are stripped
        (:func:`strip_provisional_scores`); ``show_provisional_scores=True`` keeps them.
        """
        if show_provisional_scores:
            return self.result
        return strip_provisional_scores(self.result, context=self.validation_context)

    def to_json(self, *, indent: int | None = 2, show_provisional_scores: bool = False) -> str:
        """The versioned ``AssessmentResult`` JSON. Provisional scores are omitted unless
        ``show_provisional_scores`` is true."""
        if show_provisional_scores:
            return self.result.model_dump_json(indent=indent)
        # Stripped, and the keys left out altogether (the contract allows a check result without a score).
        return self.export().model_dump_json(indent=indent, exclude=_SCORE_KEYS)

    def to_html(self, *, show_provisional_scores: bool = False) -> str:
        """The self-contained HTML report (:func:`slicepoint_core.report.render_html`).

        Provisional 0-100 scores are hidden unless ``show_provisional_scores`` is true.
        """
        from .report import render_html

        return render_html(self.result, show_provisional_scores=show_provisional_scores)

    def write_html(self, path: str | Path, *, show_provisional_scores: bool = False) -> Path:
        """Write :meth:`to_html` to ``path`` and return it."""
        from .report import write_html

        return write_html(self.result, path, show_provisional_scores=show_provisional_scores)

    def to_notebook_html(self, *, height_px: int = 900, show_provisional_scores: bool = False) -> str:
        """The report in an isolated ``<iframe>`` for ``IPython.display.HTML``."""
        from .report import render_iframe

        return render_iframe(self.result, height_px=height_px, show_provisional_scores=show_provisional_scores)

    def summary(self, *, show_provisional_scores: bool = False) -> dict[str, object]:
        """Verdict and one row per check (:func:`slicepoint_core.report.summarize`)."""
        from .report import summarize

        return summarize(self.result, show_provisional_scores=show_provisional_scores)

    def write_json(self, path: str | Path, *, show_provisional_scores: bool = False) -> Path:
        """Write :meth:`to_json` to ``path`` and return it. Provisional scores are omitted
        unless ``show_provisional_scores`` is true."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.to_json(show_provisional_scores=show_provisional_scores) + "\n", encoding="utf-8")
        return out


class Assessment:
    """One site compared with one reference under one threshold profile.

    Raises :class:`~slicepoint_schemas.embedding.IncomparableEmbeddingSpacesError` at
    construction if the site's embeddings are in a different space from the reference.
    """

    def __init__(
        self,
        dataset: TabularDataset | CuratedDataset,
        reference: ReferenceProfile,
        profile: ThresholdProfile = HACKATHON_DEFAULT_PROFILE,
        *,
        registry: CheckRegistry | None = None,
        services: Mapping[str, ServicePort] | None = None,
        now: dt.datetime | None = None,
        site_name: str | None = None,
    ) -> None:
        """``site_name`` is an optional display name for the report (for example
        "St. Mary's Hospital"); it is stored in the result and never used as a key."""
        self.dataset = dataset if isinstance(dataset, TabularDataset) else TabularDataset.from_curated(dataset)
        self.site_name = site_name.strip() if site_name and site_name.strip() else None
        self.reference = reference
        self.profile = profile
        self.registry = registry or default_registry()
        self.services = dict(services or {})
        self.now = now
        self.context = CheckContext(self.dataset, reference, profile)

    def run(self) -> AssessmentReport:
        ds, ctx = self.dataset, self.context
        steps: list[StepRecord] = [
            StepRecord(step="ingest", state=StepState.OK, detail=f"{len(ds)} cases from {ds.source or 'memory'}"),
        ]
        if ds.space is not None:
            steps.append(StepRecord(step="embed", state=StepState.OK, detail=f"precomputed, space {ds.space.space_id}"))
        else:
            steps.append(StepRecord(step="embed", state=StepState.SKIPPED,
                                    detail="no precomputed embeddings and no embedding service in milestone 1"))
        steps.append(StepRecord(step="load_reference", state=StepState.OK,
                                detail=f"{self.reference.summary.reference_id} ({self.reference.summary.n_cases} cases)"))

        seg = self.services.get(SEGMENTATION)
        if seg is None or not seg.available():
            steps.append(StepRecord(step="segmentation", state=StepState.SKIPPED,
                                    detail="segmentation worker not configured; Dice taken from predictions.parquet"))
        else:
            steps.append(StepRecord(step="segmentation", state=StepState.SKIPPED,
                                    detail="segmentation port available but not wired in milestone 1"))

        runs: list[CheckRun] = []
        results: list[CheckResult] = []
        notes: list[str] = list(ds.notes)  # ingestion ("Files") notes first, as in the notebook
        findings: dict[str, list[Finding]] = {}
        if len(ds) < ctx.params.int("smallest_dataset_scans"):
            notes.append(f"Only {len(ds)} scans: every number below is rough, and subgroup results are very uncertain.")
        for spec in self.registry:
            step = f"check_{spec.id}"
            missing = missing_requirements(spec, ctx)
            if missing:
                reason = f"missing input: {', '.join(missing)}"
                runs.append(CheckRun(check_id=spec.id, state=CheckRunState.SKIPPED, reason=reason))
                steps.append(StepRecord(step=step, state=StepState.SKIPPED, detail=reason))
                continue
            try:
                done = evaluate(spec, ctx, self.registry)
            except CheckSkipped as exc:
                runs.append(CheckRun(check_id=spec.id, state=CheckRunState.SKIPPED, reason=str(exc)))
                steps.append(StepRecord(step=step, state=StepState.SKIPPED, detail=str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001 - a failing check must be recorded, not hide the others
                detail = f"{type(exc).__name__}: {exc}"
                runs.append(CheckRun(check_id=spec.id, state=CheckRunState.FAILED, reason=detail))
                steps.append(StepRecord(step=step, state=StepState.FAILED, detail=detail[:2000]))
                # One line by default; the traceback only at DEBUG (the CLI's --debug).
                _log.warning("check %s failed: %s", spec.id, detail)
                _log.debug("traceback for failed check %s", spec.id, exc_info=True)
                continue
            results.append(done.result)
            notes.extend(done.notes)
            findings[spec.id] = done.findings
            runs.append(CheckRun(check_id=spec.id, state=CheckRunState.EVALUATED))
            steps.append(StepRecord(step=step, state=StepState.OK))

        verdict = derive_verdict(results, self.profile, site_id=ds.site_id, registry=self.registry.schema_registry())
        steps.append(StepRecord(step="verdict", state=StepState.OK, detail=verdict.outcome.value))

        perf = self._performance()
        steps.append(StepRecord(
            step="performance",
            state=StepState.OK if perf.aaa_missing_as_wrong is not None else StepState.SKIPPED,
            detail=None if perf.aaa_missing_as_wrong is not None else "needs labels and predictions",
        ))

        scans = self._scans()
        strata, cases = self._review_tables(scans, steps)

        result = AssessmentResult.model_validate(
            {
                "site_id": ds.site_id,
                "site_name": self.site_name,
                "reference": ReferenceRef(
                    reference_id=self.reference.summary.reference_id,
                    site_id=self.reference.summary.site_id,
                    n_cases=self.reference.summary.n_cases,
                    embedding_space_id=self.reference.space.space_id if self.reference.space else None,
                    fingerprint=self.reference.summary.provenance.dataset_fingerprint,
                ),
                "profile_id": self.profile.profile_id,
                "model_id": self.profile.model_id,
                "embedding_space_id": ds.space.space_id if ds.space else None,
                "dataset_fingerprint": ds.fingerprint(),
                "generated_at": self.now or dt.datetime.now(dt.timezone.utc),
                "generator": f"slicepoint-core {__version__}",
                "steps": steps,
                "checks": runs,
                "verdict": verdict,
                "performance": perf,
                "scans": scans,
                "notes": notes,
                "thresholds": self.profile,
                "strata": strata,
                "cases_to_review": cases,
            },
            context=self.registry.validation_context(),
        )
        return AssessmentReport(result=result, findings=findings, validation_context=self.registry.validation_context())

    # ------------------------------------------------------------------ pieces

    def _review_tables(
        self, scans: list[ScanSummary], steps: list[StepRecord]
    ) -> tuple[Strata | None, CasesToReview | None]:
        """The by-group table and the cases-to-review list, recorded as steps."""
        if not scans:
            for step in ("strata", "cases_to_review"):
                steps.append(StepRecord(step=step, state=StepState.SKIPPED, detail="no scans"))
            return None, None
        try:
            size_tol = self.context.params.tolerances()[1]
            min_aaa = self.context.params.int("min_aaa_for_sensitivity")
        except MissingThresholdError as exc:
            detail = str(exc).strip("'\"")
            for step in ("strata", "cases_to_review"):
                steps.append(StepRecord(step=step, state=StepState.SKIPPED, detail=detail))
            return None, None
        strata = stratified_table(scans, size_tolerance_mm=size_tol, min_group_size=self.profile.min_group_size,
                                  min_aaa_for_sensitivity=min_aaa)
        cases = cases_to_review(scans, size_tolerance_mm=size_tol)
        steps.append(StepRecord(step="strata", state=StepState.OK, detail=f"{len(strata.rows)} groups"))
        steps.append(StepRecord(step="cases_to_review", state=StepState.OK,
                                detail=f"{len(cases.cases)} of {cases.n_scans} scans flagged"))
        return strata, cases

    def _performance(self) -> PerformanceSummary:
        ctx = self.context
        dm = ctx.diameter
        return PerformanceSummary(
            aaa_missing_as_wrong=ctx.bin_missing_as_wrong,
            aaa_when_answered=ctx.bin_when_answered,
            diameter=dm.to_model(*ctx.params.tolerances()) if dm is not None else None,
            dice=ctx.dice,
        )

    def _scans(self) -> list[ScanSummary]:
        df = self.dataset.frame
        labels = self.context.people.labels

        def text(row: Mapping[Hashable, object], key: str) -> str | None:
            v = row.get(key)
            return None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)

        def num(row: Mapping[Hashable, object], key: str) -> float | None:
            v = row.get(key)
            if v is None or not isinstance(v, (int, float, np.integer, np.floating)) or np.isnan(v):
                return None
            return float(v)

        out = []
        for i, row in enumerate(df.to_dict("records")):
            pred = num(row, "pred_aaa_f")
            aaa = row.get("aaa")
            out.append(ScanSummary.model_validate({
                "case_id": str(row["case_id"]),
                "person_group": f"p{int(labels[i])}",
                "sex": text(row, "sex"),
                "age_band": text(row, "age_band"),
                "scanner_vendor": text(row, "scanner_vendor"),
                "contrast_phase": text(row, "contrast_phase"),
                "slice_thickness_class": text(row, "slice_thickness_class"),
                "aaa_size_class": text(row, "aaa_size_class"),
                "aaa": None if aaa is None else bool(aaa),
                "reference_diameter_mm": num(row, "max_aortic_diameter_mm"),
                "ai_diameter_mm": num(row, "pred_max_diameter_mm"),
                "ai_aaa": None if pred is None else bool(pred),
            }))
        return out

