"""The versioned top-level result of one assessment (ADR 0001, sections 5 and 9).

:class:`AssessmentResult` is what ``slicepoint-core``'s local runner returns. It is also
the payload the future static viewer renders and the API serves. It bundles:

* the per-step run record (``ok`` / ``skipped`` / ``failed``). A step that needed a
  missing input or service is **skipped**, never silently passed (ADR section 5).
* one :class:`CheckRun` per registered check. A check that was not evaluated says why,
  and its id appears in ``verdict.not_evaluated`` when the profile expects it.
* the :class:`~slicepoint_schemas.verdict.Verdict`, which embeds the evaluated
  :class:`~slicepoint_schemas.checks.CheckResult` objects.
* the performance blocks (binary AAA call, diameter agreement, Dice). Their shape is
  the POC's, so they reuse the legacy metric models and their arithmetic validators.
* a per-scan table for the viewer, and free-text notes (the POC's ``info`` items).

Persistence and audit (who ran it, stored where) are out of scope (ADR section 8).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StrictBool, StringConstraints, model_validator

from .common import (
    AaaSizeClass,
    AgeBand,
    CaseId,
    CheckId,
    ContractModel,
    ContrastPhase,
    NonNegativeFloat,
    OpenScannerVendor,
    OpenSex,
    Sha256Hex,
    SiteId,
    SliceThicknessClass,
    UnitInterval,
    VersionedModel,
)
from .embedding import SpaceId
from .legacy import BinMetricsV0, DiceMetricsV0
from .verdict import Verdict

StepId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class StepState(str, Enum):
    """Outcome of one pipeline step."""

    OK = "ok"
    SKIPPED = "skipped"
    FAILED = "failed"


class StepRecord(ContractModel):
    """One step of the assessment pipeline. ``detail`` is required unless the step is ok."""

    step: StepId
    state: StepState
    detail: str | None = None

    @model_validator(mode="after")
    def _detail(self) -> StepRecord:
        if self.state is not StepState.OK and not (self.detail and self.detail.strip()):
            raise ValueError(f"step {self.step}: a {self.state.value} step must say why")
        return self


class CheckRunState(str, Enum):
    EVALUATED = "evaluated"
    SKIPPED = "skipped"
    FAILED = "failed"


class CheckRun(ContractModel):
    """Whether a registered check ran. ``skipped`` means its required inputs were missing
    (for example no labels or no embeddings); ``failed`` means it raised. Neither is ok."""

    check_id: CheckId
    state: CheckRunState
    reason: str | None = None

    @model_validator(mode="after")
    def _reason(self) -> CheckRun:
        if self.state is not CheckRunState.EVALUATED and not (self.reason and self.reason.strip()):
            raise ValueError(f"check {self.check_id}: a {self.state.value} check must give a reason")
        return self


class ReferenceRef(ContractModel):
    """Which reference profile the site was compared against."""

    reference_id: str = Field(min_length=1)
    site_id: SiteId
    n_cases: int = Field(ge=0)
    embedding_space_id: SpaceId | None = None
    fingerprint: Sha256Hex | None = Field(
        default=None, description="sha256 of the reference dataset content."
    )


_EPS = 1e-9


class ToleranceRole(str, Enum):
    BLAND_ALTMAN = "bland_altman"
    SIZE = "size"


class WithinTolerance(ContractModel):
    """Share of cases with ``|predicted - reference| <= tolerance_mm``. The tolerance
    comes from the threshold profile (``aaa.bland_altman_tolerance_mm`` /
    ``aaa.size_tolerance_mm``); ``share`` is null when there are too few pairs."""

    role: ToleranceRole
    tolerance_mm: float = Field(gt=0)
    share: UnitInterval | None


class DiameterAgreement(ContractModel):
    """Bland-Altman style agreement of the model's diameter with the reference label.

    ``error = predicted - reference``. ``sd`` is the **population** SD of the error and
    the 95% limits of agreement are ``bias +/- 1.96 sd``. Every float is null when
    ``n < min_n`` (3 in the POC). Tolerances are profile-driven, unlike the legacy
    ``DiameterMetricsV0`` whose ``within_2mm`` / ``within_3mm`` names fix them.
    """

    n: int = Field(ge=0)
    min_n: int = Field(default=3, ge=1)
    mae: NonNegativeFloat | None
    rmse: NonNegativeFloat | None
    bias: float | None
    sd: NonNegativeFloat | None
    loa_low: float | None
    loa_high: float | None
    within_tolerance: tuple[WithinTolerance, ...]
    spearman: Annotated[float, Field(ge=-1.0, le=1.0)] | None

    @model_validator(mode="after")
    def _consistent(self) -> DiameterAgreement:
        floats = (self.mae, self.rmse, self.bias, self.sd, self.loa_low, self.loa_high)
        shares = [w.share for w in self.within_tolerance]
        if self.n < self.min_n:
            if any(v is not None for v in (*floats, *shares, self.spearman)):
                raise ValueError(f"with n < {self.min_n} every diameter metric must be null")
            return self
        if any(v is None for v in (*floats, *shares)):
            raise ValueError("mae, rmse, bias, sd, loa and every within-tolerance share are required")
        roles = [w.role for w in self.within_tolerance]
        if len(roles) != len(set(roles)):
            raise ValueError("one within-tolerance entry per role")
        assert self.mae is not None and self.rmse is not None
        if self.rmse + _EPS < self.mae:
            raise ValueError("rmse cannot be below mae")
        assert self.bias is not None and self.sd is not None and self.loa_low is not None and self.loa_high is not None
        if abs(self.loa_low - (self.bias - 1.96 * self.sd)) > 1e-6 or abs(self.loa_high - (self.bias + 1.96 * self.sd)) > 1e-6:
            raise ValueError("limits of agreement must be bias +/- 1.96 sd")
        ordered = sorted(self.within_tolerance, key=lambda w: w.tolerance_mm)
        for a, b in zip(ordered, ordered[1:]):
            if a.share is not None and b.share is not None and a.share > b.share + _EPS:
                raise ValueError("a wider tolerance cannot cover fewer cases")
        return self

    def share_within(self, role: ToleranceRole) -> float | None:
        return next((w.share for w in self.within_tolerance if w.role is role), None)


class PerformanceSummary(ContractModel):
    """Model performance on this site. Each block is null when its inputs were missing.

    The binary-call and Dice blocks keep the POC shapes (``BinMetricsV0``,
    ``DiceMetricsV0``) and their arithmetic validators. The diameter block is the
    profile-driven :class:`DiameterAgreement`; ``DiameterMetricsV0`` is for legacy files.
    """

    aaa_missing_as_wrong: BinMetricsV0 | None = None
    aaa_when_answered: BinMetricsV0 | None = None
    diameter: DiameterAgreement | None = None
    dice: DiceMetricsV0 | None = None

    @model_validator(mode="after")
    def _modes_agree(self) -> PerformanceSummary:
        wrong, answered = self.aaa_missing_as_wrong, self.aaa_when_answered
        if (wrong is None) != (answered is None):
            raise ValueError("aaa_missing_as_wrong and aaa_when_answered are present together")
        if wrong is not None and answered is not None:
            if answered.n_no_answer != 0:
                raise ValueError("aaa_when_answered.n_no_answer is always 0")
            if answered.n != wrong.n - wrong.n_no_answer:
                raise ValueError("aaa_when_answered.n must equal missing_as_wrong.n - n_no_answer")
        return self


class ScanSummary(ContractModel):
    """One scan as the viewer shows it. ``person_group`` is the real-person grouping
    (same patient id OR near-identical embedding), so it can join scans under different
    patient ids. ``ai_aaa`` null means the model gave no answer, never "normal"."""

    case_id: CaseId
    person_group: Annotated[str, StringConstraints(pattern=r"^p\d+$")]
    sex: OpenSex | None = None
    age_band: AgeBand | None = None
    scanner_vendor: OpenScannerVendor | None = None
    contrast_phase: ContrastPhase | None = None
    slice_thickness_class: SliceThicknessClass | None = None
    aaa_size_class: AaaSizeClass | None = None
    aaa: StrictBool | None = None
    reference_diameter_mm: float | None = None
    ai_diameter_mm: float | None = None
    ai_aaa: StrictBool | None = None


class AssessmentResult(VersionedModel):
    """The full result of one assessment of one site against one reference."""

    result_type: Literal["slicepoint.assessment_result"] = "slicepoint.assessment_result"
    site_id: SiteId
    reference: ReferenceRef
    profile_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    embedding_space_id: SpaceId | None = None
    dataset_fingerprint: Sha256Hex | None = None
    generated_at: AwareDatetime
    generator: str = Field(min_length=1, description="Producer and version, e.g. slicepoint-core 0.1.0.")
    steps: tuple[StepRecord, ...]
    checks: tuple[CheckRun, ...] = Field(min_length=1)
    verdict: Verdict
    performance: PerformanceSummary
    scans: tuple[ScanSummary, ...] = ()
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> AssessmentResult:
        steps = [s.step for s in self.steps]
        if len(steps) != len(set(steps)):
            raise ValueError("duplicate step ids")
        ids = [c.check_id for c in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate check ids in checks")
        evaluated = {c.check_id for c in self.checks if c.state is CheckRunState.EVALUATED}
        in_verdict = {r.check_id for r in self.verdict.results}
        if evaluated != in_verdict:
            raise ValueError(
                "evaluated checks must be exactly the verdict's results "
                f"(evaluated={sorted(evaluated)}, verdict={sorted(in_verdict)})"
            )
        not_run = {c.check_id for c in self.checks if c.state is not CheckRunState.EVALUATED}
        # Every expected check that produced no result must be listed here with its reason.
        # A skipped check the profile does not expect is allowed.
        unexplained = set(self.verdict.not_evaluated) - not_run
        if unexplained:
            raise ValueError(f"verdict.not_evaluated has checks with no skipped/failed entry: {sorted(unexplained)}")
        if self.verdict.site_id is not None and self.verdict.site_id != self.site_id:
            raise ValueError("verdict.site_id differs from site_id")
        case_ids = [s.case_id for s in self.scans]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("duplicate case_id in scans")
        return self


__all__ = [
    "AssessmentResult",
    "DiameterAgreement",
    "ToleranceRole",
    "WithinTolerance",
    "CheckRun",
    "CheckRunState",
    "PerformanceSummary",
    "ReferenceRef",
    "ScanSummary",
    "StepRecord",
    "StepState",
]
