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
* the by-group table (:class:`Strata`) and the :class:`CasesToReview` list, computed by
  the runner so a renderer only displays them, and the resolved
  :class:`~slicepoint_schemas.thresholds.ThresholdProfile` the run used.

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
from .checks import CheckDescriptor
from .embedding import SpaceId
from .legacy import BinMetricsV0, DiceMetricsV0
from .thresholds import ThresholdProfile
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


PersonGroup = Annotated[str, StringConstraints(pattern=r"^p\d+$")]
ColumnName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class StratumRow(ContractModel):
    """One group (``variable`` = ``level``) of the by-group table.

    ``too_few`` (fewer than ``Strata.min_group_size`` scans) suppresses every metric.
    ``sens_too_few`` (too few scans, or fewer than ``min_aaa_for_sensitivity``
    aneurysms) suppresses sensitivity. Both rules count scans, not people. A missing
    value of the variable is the level ``MISSING``.
    """

    variable: ColumnName
    level: str = Field(min_length=1)
    n: int = Field(ge=0)
    people: int = Field(ge=0)
    n_aaa: int = Field(ge=0)
    too_few: StrictBool
    bias_mm: float | None = None
    mae_mm: NonNegativeFloat | None = None
    within_tolerance: UnitInterval | None = Field(
        default=None, description="Share of the group's paired cases within Strata.size_tolerance_mm."
    )
    sens: UnitInterval | None = None
    sens_lo: UnitInterval | None = None
    sens_hi: UnitInterval | None = None
    sens_too_few: StrictBool

    @model_validator(mode="after")
    def _consistent(self) -> StratumRow:
        if self.people > self.n or self.n_aaa > self.n:
            raise ValueError(f"{self.variable}={self.level}: people and n_aaa cannot exceed n")
        if self.too_few:
            if not self.sens_too_few:
                raise ValueError(f"{self.variable}={self.level}: a too-few group also suppresses sensitivity")
            if any(v is not None for v in (self.bias_mm, self.mae_mm, self.within_tolerance)):
                raise ValueError(f"{self.variable}={self.level}: a too-few group has no metrics")
        if self.sens_too_few and any(v is not None for v in (self.sens, self.sens_lo, self.sens_hi)):
            raise ValueError(f"{self.variable}={self.level}: suppressed sensitivity must be null")
        if (self.sens is None) != (self.sens_lo is None) or (self.sens is None) != (self.sens_hi is None):
            raise ValueError(f"{self.variable}={self.level}: sens, sens_lo and sens_hi are present together")
        if self.sens is not None:
            assert self.sens_lo is not None and self.sens_hi is not None
            if not self.sens_lo - _EPS <= self.sens <= self.sens_hi + _EPS:
                raise ValueError(f"{self.variable}={self.level}: sens must lie within its interval")
        return self


class Strata(ContractModel):
    """The by-group (stratified) table, computed by the runner. The suppression rules and
    the size tolerance it used are recorded with it, so a reader never has to guess them."""

    min_group_size: int = Field(gt=0)
    min_aaa_for_sensitivity: int = Field(gt=0)
    size_tolerance_mm: float = Field(gt=0)
    rows: tuple[StratumRow, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> Strata:
        keys = [(r.variable, r.level) for r in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate (variable, level) in strata rows")
        for r in self.rows:
            if r.too_few != (r.n < self.min_group_size):
                raise ValueError(f"{r.variable}={r.level}: too_few disagrees with min_group_size")
        return self


class ReviewReason(str, Enum):
    """Why a scan is listed for review. Priority: 1 missed or unanswered aneurysm,
    2 no answer, 3 size error beyond the tolerance, 4 false alarm."""

    MISSED_ANEURYSM = "missed_aneurysm"
    NO_ANSWER_ON_ANEURYSM = "no_answer_on_aneurysm"
    NO_ANSWER = "no_answer"
    SIZE_ERROR = "size_error"
    FALSE_ALARM = "false_alarm"

    @property
    def priority(self) -> int:
        return _REASON_PRIORITY[self]


_REASON_PRIORITY = {
    ReviewReason.MISSED_ANEURYSM: 1,
    ReviewReason.NO_ANSWER_ON_ANEURYSM: 1,
    ReviewReason.NO_ANSWER: 2,
    ReviewReason.SIZE_ERROR: 3,
    ReviewReason.FALSE_ALARM: 4,
}


class ReviewCase(ContractModel):
    """A scan worth a human look. ``priority`` is the most urgent of its ``reasons``;
    ``error_mm`` is ``ai_diameter_mm - reference_diameter_mm`` when both exist."""

    case_id: CaseId
    person_group: PersonGroup
    reasons: tuple[ReviewReason, ...] = Field(min_length=1)
    priority: int = Field(ge=1, le=4)
    aaa: StrictBool | None = None
    ai_aaa: StrictBool | None = None
    reference_diameter_mm: float | None = None
    ai_diameter_mm: float | None = None
    error_mm: float | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ReviewCase:
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError(f"case {self.case_id}: duplicate reasons")
        if self.priority != min(r.priority for r in self.reasons):
            raise ValueError(f"case {self.case_id}: priority must be the most urgent reason's")
        both = self.ai_diameter_mm is not None and self.reference_diameter_mm is not None
        if both != (self.error_mm is not None):
            raise ValueError(f"case {self.case_id}: error_mm is present exactly when both diameters are")
        if both:
            assert self.ai_diameter_mm is not None and self.reference_diameter_mm is not None
            assert self.error_mm is not None
            if abs(self.error_mm - (self.ai_diameter_mm - self.reference_diameter_mm)) > 1e-6:
                raise ValueError(f"case {self.case_id}: error_mm must be ai minus reference diameter")
        if ReviewReason.SIZE_ERROR in self.reasons and self.error_mm is None:
            raise ValueError(f"case {self.case_id}: a size error needs both diameters")
        return self


class CasesToReview(ContractModel):
    """Every flagged scan, most urgent first (priority, then the larger diameter error,
    then case id). ``n_scans`` is how many scans were screened."""

    size_tolerance_mm: float = Field(gt=0)
    n_scans: int = Field(ge=0)
    cases: tuple[ReviewCase, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> CasesToReview:
        ids = [c.case_id for c in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate case_id in cases_to_review")
        if len(ids) > self.n_scans:
            raise ValueError("more cases to review than scans screened")
        return self


class AssessmentResult(VersionedModel):
    """The full result of one assessment of one site against one reference.

    ``thresholds``, ``strata``, ``cases_to_review`` and ``site_name`` were added after the
    first 0.1.0 files were written, so they are optional: an older file still validates,
    and a reader shows "not recorded" rather than assuming defaults. ``check_descriptors``
    (schemas 0.2.1) follows the same rule: a reader without it falls back to its own copy
    of the default registry.

    A site compared with its own reference data is visible from the two fingerprints
    (:attr:`is_self_comparison`); it is derived, not stored, so it cannot disagree with them.
    """

    result_type: Literal["slicepoint.assessment_result"] = "slicepoint.assessment_result"
    site_id: SiteId
    site_name: str | None = Field(
        default=None, min_length=1, max_length=200,
        description="Human-readable site name for display, e.g. 'St. Mary's Hospital'. Never used as a key.",
    )
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
    thresholds: ThresholdProfile | None = Field(
        default=None,
        description="The resolved threshold profile the run used (same profile_id). Readers take group sizes, "
                    "tolerances, markers and trigger lines from here, never from defaults.",
    )
    strata: Strata | None = Field(default=None, description="The by-group table; null when there are no scans.")
    cases_to_review: CasesToReview | None = Field(
        default=None, description="Scans flagged for a human look; null when there are no scans."
    )
    check_descriptors: tuple[CheckDescriptor, ...] | None = Field(
        default=None,
        description="The descriptors (titles, definitions, sub-factors) of the check registry the run used, so a "
                    "reader renders check cards from the result, not from its own copy. Null in files written "
                    "before schemas 0.2.1; readers then fall back to the default registry.",
    )

    @property
    def is_self_comparison(self) -> bool:
        """True when the site's dataset is the reference's own dataset (equal fingerprints).
        The shift checks then cannot detect anything; the result is only a sanity check."""
        return self.dataset_fingerprint is not None and self.dataset_fingerprint == self.reference.fingerprint

    @model_validator(mode="after")
    def _consistent(self) -> AssessmentResult:
        if self.thresholds is not None and self.thresholds.profile_id != self.profile_id:
            raise ValueError(
                f"thresholds.profile_id {self.thresholds.profile_id!r} differs from profile_id {self.profile_id!r}"
            )
        if self.cases_to_review is not None and self.scans:
            known = {s.case_id for s in self.scans}
            unknown = [c.case_id for c in self.cases_to_review.cases if c.case_id not in known]
            if unknown:
                raise ValueError(f"cases_to_review lists case ids not in scans: {unknown[:5]}")
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
        if self.check_descriptors is not None:
            self._descriptors_cover_checks(self.check_descriptors)
        return self

    def _descriptors_cover_checks(self, descriptors: tuple[CheckDescriptor, ...]) -> None:
        by_id = {d.id: d for d in descriptors}
        if len(by_id) != len(descriptors):
            raise ValueError("duplicate ids in check_descriptors")
        missing = [c.check_id for c in self.checks if c.check_id not in by_id]
        if missing:
            raise ValueError(f"check_descriptors has no descriptor for checks {missing}")
        for r in self.verdict.results:
            subs = {s.id for s in by_id[r.check_id].sub_factors}
            unknown = [f for f in r.failing_sub_factors if f not in subs]
            if unknown:
                raise ValueError(f"check {r.check_id}: failing sub-factors {unknown} are not in its descriptor")


__all__ = [
    "AssessmentResult",
    "CasesToReview",
    "ReviewCase",
    "ReviewReason",
    "Strata",
    "StratumRow",
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
