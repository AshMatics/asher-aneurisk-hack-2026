"""The assessment pipeline as a declarative list of steps (ADR 0001 section 5).

Every step is a :class:`StepSpec`: an id, a title and a function of the
:class:`JobContext`. It returns ``succeeded`` or ``skipped`` with a message, or raises.
Steps that need a service outside SlicePoint go through the ports in
``slicepoint_core.ports``; a missing or unavailable service makes the step **skipped**,
which never counts as a pass (the verdict is derived by core, which reports
not-evaluated checks and cannot return GO on them).

The analysis itself is ``slicepoint_core``: ``ParquetAdapter`` -> ``ReferenceProfile`` ->
``Assessment.run()``, the same path as the CLI and the notebook.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from slicepoint_core import Assessment, AssessmentReport, InputError, ParquetAdapter, ReferenceProfile, TabularDataset
from slicepoint_core.ports import EMBEDDING, FORGE_PGM, OPENCPU, SEGMENTATION, ServicePort
from slicepoint_schemas.embedding import IncomparableEmbeddingSpacesError
from slicepoint_schemas.thresholds import ThresholdProfile

from .jobs import REPORT_FILE, RESULT_FILE, JobStore, atomic_write_text, utcnow
from .models import AssessmentRequest, JobAudit, JobState, JobStep, OnInconsistency, StepStatus
from .references import ReferenceStore

_log = logging.getLogger(__name__)

INTERNAL_ERROR = "internal error; details are in the server log"
NOT_CONFIGURED = "service not configured"
NOT_WIRED = "service is configured but not wired into the pipeline yet (M4)"


@dataclass
class JobContext:
    job_id: str
    request: AssessmentRequest
    profile: ThresholdProfile
    site_dir: Path
    reference_dir: Path | None
    """Reference dataset folder (when the reference is built for this job)."""
    references: ReferenceStore
    out_dir: Path
    services: Mapping[str, ServicePort] = field(default_factory=dict)
    site: TabularDataset | None = None
    reference: ReferenceProfile | None = None
    report: AssessmentReport | None = None


@dataclass(frozen=True)
class StepOutcome:
    status: StepStatus
    message: str | None = None


@dataclass(frozen=True)
class StepSpec:
    id: str
    title: str
    run: Callable[[JobContext], StepOutcome]


def load_dataset(folder: Path, name: str, site_id: str, on_inconsistency: OnInconsistency) -> TabularDataset:
    """Load a server-side folder; the dataset's ``source`` is the relative name, never the server path."""
    ds = ParquetAdapter(site_id, on_inconsistency=on_inconsistency).load_tabular(folder)
    return dataclasses.replace(ds, source=name)


# --------------------------------------------------------------------------- steps


def _ingest_site(ctx: JobContext) -> StepOutcome:
    r = ctx.request
    ctx.site = load_dataset(ctx.site_dir, r.dataset, r.site_id, r.on_inconsistency)
    extra = f"; {len(ctx.site.notes)} ingestion note(s)" if ctx.site.notes else ""
    return StepOutcome(StepStatus.SUCCEEDED, f"{len(ctx.site)} cases from {r.dataset}{extra}")


def _load_reference(ctx: JobContext) -> StepOutcome:
    r = ctx.request
    if r.reference_id is not None:
        ctx.reference = ctx.references.load(r.reference_id)
        how = "loaded stored reference"
    else:
        assert ctx.reference_dir is not None and r.reference_dataset is not None and r.reference_site_id is not None
        data = load_dataset(ctx.reference_dir, r.reference_dataset, r.reference_site_id, r.on_inconsistency)
        ctx.reference = ReferenceProfile.build(data, ctx.profile)
        how = f"built from {r.reference_dataset}"
    s = ctx.reference.summary
    return StepOutcome(StepStatus.SUCCEEDED, f"{how}: {s.reference_id} (site {s.site_id}, {s.n_cases} cases)")


def _port(ctx: JobContext, name: str) -> ServicePort | None:
    port = ctx.services.get(name)
    return port if port is not None and port.available() else None


def _embedding(ctx: JobContext) -> StepOutcome:
    assert ctx.site is not None
    if ctx.site.space is not None:
        return StepOutcome(StepStatus.SUCCEEDED, f"precomputed embeddings, space {ctx.site.space.space_id}")
    if _port(ctx, EMBEDDING) is None:
        return StepOutcome(StepStatus.SKIPPED,
                           f"{NOT_CONFIGURED}; no precomputed embeddings, so embedding-based checks are not evaluated")
    return StepOutcome(StepStatus.SKIPPED, NOT_WIRED)


def _port_step(name: str, consequence: str) -> Callable[[JobContext], StepOutcome]:
    def run(ctx: JobContext) -> StepOutcome:
        if _port(ctx, name) is None:
            return StepOutcome(StepStatus.SKIPPED, f"{NOT_CONFIGURED}; {consequence}")
        return StepOutcome(StepStatus.SKIPPED, NOT_WIRED)

    return run


def _run_checks(ctx: JobContext) -> StepOutcome:
    assert ctx.site is not None and ctx.reference is not None
    r = ctx.request
    ctx.report = Assessment(ctx.site, ctx.reference, ctx.profile, site_name=r.site_name,
                            services=ctx.services).run()
    v = ctx.report.verdict
    msg = f"verdict {v.final_outcome.value}; {len(v.results)} check(s) evaluated"
    if v.not_evaluated:
        msg += f"; not evaluated (never a pass): {', '.join(v.not_evaluated)}"
    return StepOutcome(StepStatus.SUCCEEDED, msg)


def _render_report(ctx: JobContext) -> StepOutcome:
    assert ctx.report is not None
    show = ctx.request.show_provisional_scores
    atomic_write_text(ctx.out_dir / RESULT_FILE, ctx.report.to_json(show_provisional_scores=show) + "\n")
    atomic_write_text(ctx.out_dir / REPORT_FILE, ctx.report.to_html(show_provisional_scores=show))
    return StepOutcome(StepStatus.SUCCEEDED, f"wrote {RESULT_FILE} and {REPORT_FILE}"
                       + (" (provisional scores shown)" if show else ""))


STEPS: tuple[StepSpec, ...] = (
    StepSpec("ingest_site", "Load the site dataset", _ingest_site),
    StepSpec("load_reference", "Load or build the reference profile", _load_reference),
    StepSpec("embedding", "Embeddings (encoder service unless precomputed)", _embedding),
    StepSpec("segmentation", "GPU segmentation worker",
             _port_step(SEGMENTATION, "Dice is taken from predictions.parquet")),
    StepSpec("forge_pgm", "FORGE cohort planning and PGM synthesis",
             _port_step(FORGE_PGM, "no cohort sizing or synthetic reference population")),
    StepSpec("opencpu", "OpenCPU (R statistics)", _port_step(OPENCPU, "R-validated statistics not run")),
    StepSpec("run_checks", "Run the checks and derive the verdict", _run_checks),
    StepSpec("render_report", "Write result.json and report.html", _render_report),
)


def initial_steps() -> list[JobStep]:
    return [JobStep(id=s.id, title=s.title) for s in STEPS]


# --------------------------------------------------------------------------- errors

_ABS_PATH = re.compile(r"(?<![\w.<])/(?:[^\s:'\"/]+/)*[^\s:'\"/]+")


def scrub(message: str, roots: Mapping[str, Path]) -> str:
    """One line, with server folders replaced by their names and any other absolute path removed."""
    text = " ".join(message.split())
    for label, root in roots.items():
        text = text.replace(f"{root}/", "").replace(str(root), label)
    text = _ABS_PATH.sub("<path>", text)
    return text[:500]


def _first_validation_error(exc: ValidationError) -> str:
    errs = exc.errors()
    if not errs:
        return "invalid data"
    e = errs[0]
    loc = ".".join(str(x) for x in e["loc"]) or "(top level)"
    more = f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""
    return f"{loc}: {e['msg']}{more}"


def user_message(exc: BaseException) -> str | None:
    """A message the client may see, or ``None`` if the error is internal."""
    if isinstance(exc, ValidationError):
        return _first_validation_error(exc)
    if isinstance(exc, (InputError, FileNotFoundError, IncomparableEmbeddingSpacesError)):
        return str(exc)
    return None


# --------------------------------------------------------------------------- runner


def run_job(store: JobStore, ctx: JobContext, roots: Mapping[str, Path],
            steps: tuple[StepSpec, ...] = STEPS) -> None:
    """Execute ``steps`` for one job, recording each step's status in ``store``."""
    job_id = ctx.job_id
    with store.edit(job_id) as rec:
        rec.state = JobState.RUNNING
        rec.started_at = utcnow()
    for i, spec in enumerate(steps):
        started = utcnow()
        t0 = time.perf_counter()
        with store.edit(job_id) as rec:
            rec.steps[i].status = StepStatus.RUNNING
            rec.steps[i].started_at = started
        try:
            outcome = spec.run(ctx)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded on the job
            shown = user_message(exc)
            if shown is None:
                _log.exception("job %s: step %s failed", job_id, spec.id)
                message = INTERNAL_ERROR
            else:
                _log.info("job %s: step %s failed on input: %s", job_id, spec.id, shown)
                message = scrub(shown, roots)
            with store.edit(job_id) as rec:
                _finish_step(rec.steps[i], StepStatus.FAILED, message, t0)
                rec.state = JobState.FAILED
                rec.error = f"{spec.id}: {message}"
                rec.finished_at = utcnow()
            return
        with store.edit(job_id) as rec:
            _finish_step(rec.steps[i], outcome.status, outcome.message, t0)
            _record_audit(rec.audit, ctx)
    with store.edit(job_id) as rec:
        rec.state = JobState.SUCCEEDED
        rec.finished_at = utcnow()


def _finish_step(step: JobStep, status: StepStatus, message: str | None, t0: float) -> None:
    step.status = status
    step.message = message
    step.finished_at = utcnow()
    step.duration_ms = int((time.perf_counter() - t0) * 1000)


def _record_audit(audit: JobAudit, ctx: JobContext) -> None:
    if ctx.site is not None:
        audit.dataset_fingerprint = ctx.site.fingerprint()
        audit.embedding_space_id = ctx.site.space.space_id if ctx.site.space else None
    if ctx.reference is not None:
        audit.reference_id = ctx.reference.summary.reference_id
        audit.reference_fingerprint = ctx.reference.summary.provenance.dataset_fingerprint
    if ctx.report is not None:
        audit.verdict = ctx.report.verdict.final_outcome
