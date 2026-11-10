"""The FastAPI application: ``create_app(settings)``.

Routes are thin. Validation is pydantic, the analysis is slicepoint-core, job state is
:mod:`slicepoint_api.jobs`, and the pipeline is :mod:`slicepoint_api.pipeline`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import slicepoint_core
import slicepoint_schemas
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, Response
from slicepoint_core import ReferenceProfile, default_registry
from slicepoint_core.ports import ServicePort
from slicepoint_schemas.assessment import AssessmentResult
from slicepoint_schemas.checks import CheckDescriptor
from slicepoint_schemas.thresholds import HACKATHON_DEFAULT_PROFILE

from . import __version__
from .datasets import DatasetPathError, list_datasets, resolve_dataset
from .jobs import REPORT_FILE, RESULT_FILE, JobRunner, JobStore, ThreadPoolJobRunner, utcnow
from .models import (
    JOB_ID_PATTERN,
    REFERENCE_ID_PATTERN,
    AssessmentRequest,
    DatasetList,
    ErrorDetail,
    Health,
    JobAccepted,
    JobAudit,
    JobList,
    JobRecord,
    JobRequestSummary,
    JobState,
    JobSummary,
    ReferenceBuildRequest,
    ReferenceInfo,
    ReferenceList,
)
from .pipeline import INTERNAL_ERROR, JobContext, initial_steps, load_dataset, run_job, scrub, user_message
from .references import ReferenceExists, ReferenceStore
from .security import SecurityMiddleware
from .settings import Settings

_log = logging.getLogger(__name__)

USER_HEADER = "X-SlicePoint-User"
"""Optional, self-reported name of the person making the request (recorded for audit)."""

JobId = Annotated[str, PathParam(pattern=JOB_ID_PATTERN, description="Job id (32 hex characters).")]
RefId = Annotated[str, PathParam(pattern=REFERENCE_ID_PATTERN, description="Reference profile id.")]
RequestedBy = Annotated[str | None, Header(alias=USER_HEADER, description="Who is asking (for the audit record).")]

_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorDetail, "description": "Bad dataset name or reference"},
    401: {"model": ErrorDetail, "description": "Missing or wrong bearer token"},
}


def _requested_by(value: str | None) -> str:
    if not value:
        return "unknown"
    clean = "".join(ch for ch in value if ch.isprintable()).strip()[:128]
    return clean or "unknown"


def create_app(settings: Settings, *, services: Mapping[str, ServicePort] | None = None,
               runner: JobRunner | None = None) -> FastAPI:
    """Build the app. ``settings`` must carry a valid token (validated by :class:`Settings`);
    the data root must exist. Finished jobs already in the results folder are loaded."""
    settings = settings.checked()
    data_root, results_dir = settings.data_root, settings.results_dir
    roots = {"<data root>": data_root, "<results>": results_dir}
    store = JobStore(results_dir)
    store.load_from_disk()
    references = ReferenceStore(results_dir)
    job_runner: JobRunner = runner or ThreadPoolJobRunner(settings.max_concurrent_jobs)
    svc = dict(services or {})

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        job_runner.shutdown()

    app = FastAPI(
        title="SlicePoint API",
        version=__version__,
        description="Job-based SlicePoint assessments over slicepoint-core. All routes except /healthz need "
                    "`Authorization: Bearer <token>`.",
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        lifespan=lifespan,
    )
    app.add_middleware(SecurityMiddleware, token=settings.token.get_secret_value(),
                       max_body_bytes=settings.max_body_bytes)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Leave out "input" and "ctx": never echo request values back.
        errors = [{"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
                  for e in exc.errors()]
        return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)

    def _dataset(name: str) -> Path:
        try:
            return resolve_dataset(data_root, name)
        except DatasetPathError as exc:
            raise HTTPException(400, str(exc)) from None

    # ------------------------------------------------------------------ meta

    @app.get("/healthz", response_model=Health, tags=["meta"])
    def healthz() -> Health:
        """Liveness only. No authentication; says nothing about data or jobs."""
        return Health()

    @app.get("/v1/checks", response_model=list[CheckDescriptor], tags=["meta"], responses=_ERRORS)
    def checks() -> list[CheckDescriptor]:
        """Descriptors of the registered checks (the UI renders cards from these)."""
        return [spec.descriptor for spec in default_registry()]

    @app.get("/v1/datasets", response_model=DatasetList, tags=["data"], responses=_ERRORS)
    def datasets() -> DatasetList:
        """Dataset folders under the server's data root (folders holding features.parquet). Names only."""
        return DatasetList(datasets=list_datasets(data_root))

    # ------------------------------------------------------------------ references

    @app.post("/v1/references", response_model=ReferenceInfo, status_code=201, tags=["references"],
              responses={**_ERRORS, 409: {"model": ErrorDetail, "description": "Reference id already exists"},
                         422: {"description": "Invalid request or input data"}})
    def build_reference(body: ReferenceBuildRequest, requested_by: RequestedBy = None) -> ReferenceInfo:
        """Build a reference profile from a dataset and store it. Runs synchronously."""
        folder = _dataset(body.dataset)
        ref_id = body.reference_id or f"ref-{body.site_id}"
        if references.exists(ref_id):
            raise HTTPException(409, f"reference {ref_id!r} already exists")
        profile = body.profile or HACKATHON_DEFAULT_PROFILE
        try:
            data = load_dataset(folder, body.dataset, body.site_id, body.on_inconsistency)
            ref = ReferenceProfile.build(data, profile, reference_id=ref_id)
        except Exception as exc:  # noqa: BLE001 - mapped to a clean client message or a 500
            shown = user_message(exc)
            if shown is None:
                _log.exception("building reference %s failed", ref_id)
                raise HTTPException(500, INTERNAL_ERROR) from None
            raise HTTPException(422, scrub(shown, roots)) from None
        try:
            return references.save(ref, dataset=body.dataset, requested_by=_requested_by(requested_by))
        except ReferenceExists:
            raise HTTPException(409, f"reference {ref_id!r} already exists") from None

    @app.get("/v1/references", response_model=ReferenceList, tags=["references"], responses=_ERRORS)
    def list_references() -> ReferenceList:
        return ReferenceList(references=references.list())

    @app.get("/v1/references/{reference_id}", response_model=ReferenceInfo, tags=["references"],
             responses={**_ERRORS, 404: {"model": ErrorDetail}})
    def get_reference(reference_id: RefId) -> ReferenceInfo:
        info = references.info(reference_id)
        if info is None:
            raise HTTPException(404, "reference not found")
        return info

    # ------------------------------------------------------------------ assessments

    @app.post("/v1/assessments", response_model=JobAccepted, status_code=202, tags=["assessments"],
              responses={**_ERRORS, 404: {"model": ErrorDetail, "description": "Stored reference not found"},
                         503: {"model": ErrorDetail, "description": "Too many jobs queued"}})
    def submit_assessment(body: AssessmentRequest, response: Response,
                          requested_by: RequestedBy = None) -> JobAccepted:
        """Queue an assessment. Poll ``GET /v1/assessments/{job_id}`` for per-step progress."""
        site_dir = _dataset(body.dataset)
        ref_dir = _dataset(body.reference_dataset) if body.reference_dataset is not None else None
        if body.reference_id is not None and not references.exists(body.reference_id):
            raise HTTPException(404, f"reference {body.reference_id!r} not found")
        if store.active_count() >= settings.max_queued_jobs:
            raise HTTPException(503, "too many jobs queued; retry later", headers={"Retry-After": "30"})
        profile = body.profile or HACKATHON_DEFAULT_PROFILE
        job_id = uuid.uuid4().hex
        record = JobRecord(
            job_id=job_id,
            state=JobState.QUEUED,
            created_at=utcnow(),
            request=JobRequestSummary(
                dataset=body.dataset, site_id=body.site_id, site_name=body.site_name,
                reference_id=body.reference_id, reference_dataset=body.reference_dataset,
                reference_site_id=body.reference_site_id, profile_id=profile.profile_id,
                on_inconsistency=body.on_inconsistency, show_provisional_scores=body.show_provisional_scores,
            ),
            steps=initial_steps(),
            audit=JobAudit(
                requested_by=_requested_by(requested_by), api_version=__version__,
                core_version=slicepoint_core.__version__, schemas_version=slicepoint_schemas.__version__,
                profile_id=profile.profile_id, model_id=profile.model_id,
            ),
        )
        store.add(record)
        ctx = JobContext(job_id=job_id, request=body, profile=profile, site_dir=site_dir, reference_dir=ref_dir,
                         references=references, out_dir=store.job_dir(job_id), services=svc)
        job_runner.submit(lambda: run_job(store, ctx, roots))
        base = f"/v1/assessments/{job_id}"
        response.headers["Location"] = base
        return JobAccepted(job_id=job_id, state=JobState.QUEUED, status_url=base,
                           result_url=f"{base}/result", report_url=f"{base}/report.html")

    @app.get("/v1/assessments", response_model=JobList, tags=["assessments"], responses=_ERRORS)
    def list_assessments() -> JobList:
        """Every job this service knows about (in memory and on disk), newest first."""
        return JobList(jobs=[
            JobSummary(job_id=r.job_id, state=r.state, created_at=r.created_at, finished_at=r.finished_at,
                       site_id=r.request.site_id, dataset=r.request.dataset, verdict=r.audit.verdict)
            for r in store.all()
        ])

    def _job(job_id: str) -> JobRecord:
        rec = store.get(job_id)
        if rec is None:
            raise HTTPException(404, "job not found")
        return rec

    @app.get("/v1/assessments/{job_id}", response_model=JobRecord, tags=["assessments"],
             responses={**_ERRORS, 404: {"model": ErrorDetail}})
    def get_assessment(job_id: JobId) -> JobRecord:
        """Job status with every step: pending, running, succeeded, failed or skipped."""
        return _job(job_id)

    def _artifact(job_id: str, name: str) -> bytes:
        rec = _job(job_id)
        if rec.state is not JobState.SUCCEEDED:
            raise HTTPException(409, f"job is {rec.state.value}; results exist only for succeeded jobs")
        path = store.job_dir(job_id) / name
        if not path.is_file():
            raise HTTPException(404, f"{name} is missing for this job")
        return path.read_bytes()

    @app.get("/v1/assessments/{job_id}/result", response_model=AssessmentResult, tags=["assessments"],
             responses={**_ERRORS, 404: {"model": ErrorDetail},
                        409: {"model": ErrorDetail, "description": "Job not finished, or failed"}})
    def get_result(job_id: JobId) -> Response:
        """The versioned AssessmentResult. Provisional scores are absent unless the job asked for them."""
        return Response(_artifact(job_id, RESULT_FILE), media_type="application/json")

    @app.get("/v1/assessments/{job_id}/report.html", response_class=HTMLResponse, tags=["assessments"],
             responses={**_ERRORS, 404: {"model": ErrorDetail}, 409: {"model": ErrorDetail}})
    def get_report(job_id: JobId) -> HTMLResponse:
        """The self-contained HTML report."""
        return HTMLResponse(_artifact(job_id, REPORT_FILE))

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, description=app.description,
                                 routes=app.routes)
            schema.setdefault("components", {})["securitySchemes"] = {
                "bearer": {"type": "http", "scheme": "bearer"}}
            schema["security"] = [{"bearer": []}]
            schema["paths"]["/healthz"]["get"]["security"] = []
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app
