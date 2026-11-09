"""The local, in-process assessment runner (ADR 0001 sections 5 and 9).

``Assessment(dataset, reference, profile).run()`` executes a fixed, sequential list of
steps. Each step records ``ok``, ``skipped`` (an input or service is missing) or
``failed`` (it raised), and the run returns an :class:`AssessmentReport` wrapping the
versioned :class:`~slicepoint_schemas.assessment.AssessmentResult`. There is no
orchestration engine yet; this runner is deliberately trivial.
"""

from __future__ import annotations

import datetime as dt
import traceback
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field

import numpy as np
from slicepoint_schemas.assessment import (
    AssessmentResult,
    CheckRun,
    CheckRunState,
    PerformanceSummary,
    ReferenceRef,
    ScanSummary,
    StepRecord,
    StepState,
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
from .ports import SEGMENTATION, ServicePort
from .reference import ReferenceProfile


@dataclass
class AssessmentReport:
    """What :meth:`Assessment.run` returns: the contract result plus convenience views."""

    result: AssessmentResult
    findings: Mapping[str, list[Finding]] = field(default_factory=dict)
    """Per-check findings in notebook order (for the legacy export and the parity suite)."""

    @property
    def verdict(self) -> Verdict:
        return self.result.verdict

    @property
    def checks(self) -> dict[str, CheckResult]:
        return {r.check_id: r for r in self.result.verdict.results}

    @property
    def performance(self) -> PerformanceSummary:
        return self.result.performance

    def to_json(self, *, indent: int | None = 2) -> str:
        return self.result.model_dump_json(indent=indent)


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
    ) -> None:
        self.dataset = dataset if isinstance(dataset, TabularDataset) else TabularDataset.from_curated(dataset)
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
                traceback.print_exc()
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

        result = AssessmentResult.model_validate(
            {
                "site_id": ds.site_id,
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
                "scans": self._scans(),
                "notes": notes,
            },
            context=self.registry.validation_context(),
        )
        return AssessmentReport(result=result, findings=findings)

    # ------------------------------------------------------------------ pieces

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

