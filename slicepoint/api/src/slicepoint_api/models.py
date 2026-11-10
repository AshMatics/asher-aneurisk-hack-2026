"""Request and response models that belong to this service, not to the contract.

Results reuse ``slicepoint-schemas`` (``AssessmentResult``, ``CheckDescriptor``,
``ThresholdProfile``, ``VerdictOutcome``). Job and step status live here for now: no
other package consumes them yet. If the FORGE runner (ADR 0001 section 5) ends up
reading them, move :class:`JobState` and :class:`StepStatus` into slicepoint-schemas.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from slicepoint_schemas.common import SITE_ID_PATTERN
from slicepoint_schemas.thresholds import ThresholdProfile
from slicepoint_schemas.verdict import VerdictOutcome

from .datasets import DatasetName

JOB_ID_PATTERN = r"^[0-9a-f]{32}$"
REFERENCE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,79}$"  # room for the default "ref-" + a 64-char site id

SiteId = Annotated[str, StringConstraints(pattern=SITE_ID_PATTERN)]
ReferenceId = Annotated[str, StringConstraints(pattern=REFERENCE_ID_PATTERN)]
OnInconsistency = Literal["raise", "drop_and_note"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- status enums


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    """Every step finished as succeeded or skipped. Says nothing about the verdict."""
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    """The step did not run (for example its service is not configured). Never a pass."""


# --------------------------------------------------------------------------- requests


class ReferenceBuildRequest(ApiModel):
    dataset: DatasetName
    site_id: SiteId = Field(description="Stable id of the reference site. Required; never guessed from the folder.")
    reference_id: ReferenceId | None = Field(default=None, description="Id to store it under (default ref-<site_id>).")
    profile: ThresholdProfile | None = Field(
        default=None, description="Threshold profile used to fit the reference (default hackathon-default-v0)."
    )
    on_inconsistency: OnInconsistency = "raise"


class AssessmentRequest(ApiModel):
    """One site against one reference.

    Give either ``reference_id`` (a stored reference, see ``POST /v1/references``) or
    ``reference_dataset`` together with ``reference_site_id``.
    """

    dataset: DatasetName
    site_id: SiteId = Field(description="Stable id of the site being assessed. Required; never guessed.")
    site_name: str | None = Field(default=None, max_length=200, description="Display name for the report only.")
    reference_id: ReferenceId | None = None
    reference_dataset: DatasetName | None = None
    reference_site_id: SiteId | None = None
    profile: ThresholdProfile | None = Field(
        default=None, description="Threshold profile (default hackathon-default-v0)."
    )
    on_inconsistency: OnInconsistency = "raise"
    show_provisional_scores: bool = Field(
        default=False,
        description="Keep the unvalidated provisional-v0 0-100 scores in the result and report (ADR 0001 OQ 2).",
    )

    @model_validator(mode="after")
    def _one_reference(self) -> AssessmentRequest:
        if (self.reference_id is None) == (self.reference_dataset is None):
            raise ValueError("give exactly one of reference_id or reference_dataset")
        if self.reference_dataset is not None and self.reference_site_id is None:
            raise ValueError("reference_dataset needs reference_site_id (the reference site's stable id); "
                             "it is never guessed")
        if self.reference_dataset is None and self.reference_site_id is not None:
            raise ValueError("reference_site_id is only used with reference_dataset")
        return self


# --------------------------------------------------------------------------- responses


class Health(ApiModel):
    status: Literal["alive"] = "alive"
    note: str = "Liveness only"


class DatasetList(ApiModel):
    datasets: list[str] = Field(description="Dataset folders under the data root (names only).")


class ReferenceInfo(ApiModel):
    reference_id: str
    site_id: str
    dataset: str | None = Field(description="Dataset name it was built from, if built by this service.")
    n_cases: int
    n_people: int
    has_labels: bool
    embedding_space_id: str | None
    profile_id: str
    dataset_fingerprint: str
    built_at: dt.datetime
    built_by: str
    requested_by: str | None = None


class ReferenceList(ApiModel):
    references: list[ReferenceInfo]


class JobStep(ApiModel):
    id: str
    title: str
    status: StepStatus = StepStatus.PENDING
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    duration_ms: int | None = None
    message: str | None = None


class JobRequestSummary(ApiModel):
    """What was asked for (the inline profile is recorded by id; the full profile is in the result)."""

    dataset: str
    site_id: str
    site_name: str | None
    reference_id: str | None
    reference_dataset: str | None
    reference_site_id: str | None
    profile_id: str
    on_inconsistency: OnInconsistency
    show_provisional_scores: bool


class JobAudit(ApiModel):
    """Audit fields recorded with every job (ADR 0001 section 8; stored as JSON until a DB exists)."""

    requested_by: str = Field(description="From the X-SlicePoint-User header; self-reported, 'unknown' if absent.")
    api_version: str
    core_version: str
    schemas_version: str
    dataset_fingerprint: str | None = None
    reference_id: str | None = None
    reference_fingerprint: str | None = None
    profile_id: str | None = None
    model_id: str | None = None
    embedding_space_id: str | None = None
    verdict: VerdictOutcome | None = Field(default=None, description="Final outcome (after any override).")


class JobRecord(ApiModel):
    job_id: Annotated[str, StringConstraints(pattern=JOB_ID_PATTERN)]
    kind: Literal["assessment"] = "assessment"
    state: JobState
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    request: JobRequestSummary
    steps: list[JobStep]
    audit: JobAudit
    error: str | None = Field(default=None, description="Why the job failed (one line, no server paths).")


class JobSummary(ApiModel):
    job_id: str
    state: JobState
    created_at: dt.datetime
    finished_at: dt.datetime | None
    site_id: str
    dataset: str
    verdict: VerdictOutcome | None


class JobList(ApiModel):
    jobs: list[JobSummary]


class JobAccepted(ApiModel):
    job_id: str
    state: JobState
    status_url: str
    result_url: str
    report_url: str


class ErrorDetail(ApiModel):
    detail: str
