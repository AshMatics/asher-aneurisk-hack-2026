"""Faithful models of the hackathon POC payloads, so existing files keep loading.

* :class:`SlicePointFileV0`: ``<hospital>_slicepoint.json`` (test_your_hospital.ipynb
  cell 34). Fact: all six samples in ``python_notebooks/hospital_test_output`` validate.
* :class:`MonthlySummaryV0`: ``<hospital>_monthly_summary.json``
  (monthly_golive_reports.ipynb cell 14). No sample is in the repo.
* :class:`DiceSummaryV0`: ``<hospital>_dice.json``. **INFERRED**: no writer exists in the
  repo; shape taken from the POC spec p.24.
* :class:`CompareResponseV1`: JSON body of the segmentation service ``POST /v1/compare``.

Legacy payloads carry no ``schema_version`` (V0) or carry their own (``"1.0"`` for
compare); they are not :class:`~slicepoint_schemas.common.VersionedModel`.

Converters to the new contract are at the bottom. They map only what is well-defined:
statuses and verdicts. Scores and failing sub-factors are left empty because the POC
never computed them.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from .checks import CheckResult, CheckStatus
from .common import (
    AaaSizeClass,
    AgeBand,
    ContractModel,
    ContrastPhase,
    NonNegativeFloat,
    ScannerVendor,
    Sex,
    Sha256Hex,
    ShortCaseId,
    SliceThicknessClass,
    UnitInterval,
    site_id_from_legacy_hospital_name,
)
from .thresholds import HACKATHON_DEFAULT_PROFILE, ThresholdProfile
from .verdict import Verdict, VerdictOutcome, derive_verdict

_EPS = 1e-9

# =========================================================================== slicepoint.json

SCAN_KEYS: tuple[str, ...] = (
    "id",
    "personGroup",
    "sex",
    "age_band",
    "scanner_vendor",
    "contrast_phase",
    "slice_thickness_class",
    "aaa_size_class",
    "aaa",
    "referenceDiameterMm",
    "aiDiameterMm",
    "aiAaa",
)
"""Exact key order the POC exporter checks (``list(s) == SCAN_KEYS``, ipynb:1594)."""

_ALIAS_KEYS = frozenset({"personGroup", "referenceDiameterMm", "aiDiameterMm", "aiAaa"})

LegacyCheck = Literal["repeats", "scanning", "labels", "accuracy", "patients"]
LegacyStatus = Literal["OK", "Watch", "Problem"]


class ScanV0(ContractModel):
    """One scan row. Every value except ``id``/``personGroup`` may be null.

    ``personGroup`` is a connected-component label over (same patient_id OR embedding
    cosine > 0.95), not a patient id. ``id`` is the first 8 characters of ``case_id``;
    the exporter checks uniqueness but does not enforce it, and neither do we.
    """

    id: ShortCaseId
    person_group: Annotated[str, StringConstraints(pattern=r"^p\d+$")] = Field(alias="personGroup")
    sex: Sex | None
    age_band: AgeBand | None
    scanner_vendor: ScannerVendor | None
    contrast_phase: ContrastPhase | None
    slice_thickness_class: SliceThicknessClass | None
    aaa_size_class: AaaSizeClass | None
    aaa: StrictBool | None
    reference_diameter_mm: float | None = Field(alias="referenceDiameterMm")
    ai_diameter_mm: float | None = Field(alias="aiDiameterMm")
    ai_aaa: StrictBool | None = Field(alias="aiAaa", description="null = the AI gave no answer")

    @model_validator(mode="before")
    @classmethod
    def _exact_keys(cls, data: Any) -> Any:
        # Only JSON-shaped input (camelCase keys) is held to the exporter's exact order;
        # Python construction by field name is checked by the normal field validation.
        if isinstance(data, dict) and _ALIAS_KEYS & set(data) and tuple(data) != SCAN_KEYS:
            raise ValueError(f"scan keys must be exactly {list(SCAN_KEYS)} in order; got {list(data)}")
        return data

    @model_validator(mode="after")
    def _no_answer_together(self) -> ScanV0:
        if (self.ai_aaa is None) != (self.ai_diameter_mm is None):
            raise ValueError("aiAaa must be null if and only if aiDiameterMm is null")
        return self


class FindingV0(ContractModel):
    """One check's finding: the worst status among the notebook findings mapped to it."""

    check: LegacyCheck
    status: LegacyStatus
    sentence: str = Field(min_length=1)


class BinMetricsV0(ContractModel):
    """Binary AAA-call metrics (``bin_metrics``, ipynb:835).

    Count arithmetic is exact by construction in the notebook and is enforced:
    ``tp+fn == n_aaa``, ``tn+fp == n_not_aaa``, ``n_aaa+n_not_aaa == n``, and every no-answer
    is counted as wrong, so ``n_no_answer <= fn+fp``. Rates are null exactly when their
    denominator is 0, and ``*_lo <= point <= *_hi`` (95% Wilson).
    """

    n: int = Field(ge=0)
    n_aaa: int = Field(ge=0)
    n_not_aaa: int = Field(ge=0)
    tp: int = Field(ge=0)
    fn: int = Field(ge=0)
    tn: int = Field(ge=0)
    fp: int = Field(ge=0)
    n_no_answer: int = Field(ge=0)
    sens: UnitInterval | None
    sens_lo: UnitInterval | None
    sens_hi: UnitInterval | None
    spec: UnitInterval | None
    spec_lo: UnitInterval | None
    spec_hi: UnitInterval | None
    bal_acc: UnitInterval | None
    g_mean: UnitInterval | None

    @model_validator(mode="after")
    def _arithmetic(self) -> BinMetricsV0:
        if self.tp + self.fn != self.n_aaa:
            raise ValueError("tp + fn must equal n_aaa")
        if self.tn + self.fp != self.n_not_aaa:
            raise ValueError("tn + fp must equal n_not_aaa")
        if self.n_aaa + self.n_not_aaa != self.n:
            raise ValueError("n_aaa + n_not_aaa must equal n")
        if self.n_no_answer > self.fn + self.fp:
            raise ValueError("every no-answer counts as wrong, so n_no_answer <= fn + fp")
        _rate("sens", self.sens, self.sens_lo, self.sens_hi, self.tp, self.n_aaa)
        _rate("spec", self.spec, self.spec_lo, self.spec_hi, self.tn, self.n_not_aaa)
        both = self.sens is not None and self.spec is not None
        if (self.bal_acc is not None) != both or (self.g_mean is not None) != both:
            raise ValueError("bal_acc and g_mean are null exactly when sens or spec is null")
        if self.sens is not None and self.spec is not None:
            if self.bal_acc is not None and abs(self.bal_acc - (self.sens + self.spec) / 2) > _EPS:
                raise ValueError("bal_acc must equal (sens + spec) / 2")
            if self.g_mean is not None and abs(self.g_mean - math.sqrt(self.sens * self.spec)) > _EPS:
                raise ValueError("g_mean must equal sqrt(sens * spec)")
        return self


def _rate(
    name: str, point: float | None, lo: float | None, hi: float | None, k: int, n: int
) -> None:
    if n == 0:
        if point is not None or lo is not None or hi is not None:
            raise ValueError(f"{name} and its bounds must be null when the denominator is 0")
        return
    if point is None or lo is None or hi is None:
        raise ValueError(f"{name} and its bounds are required when the denominator is > 0")
    if abs(point - k / n) > _EPS:
        raise ValueError(f"{name} must equal {k}/{n}")
    if not (lo - _EPS <= point <= hi + _EPS):
        raise ValueError(f"Wilson bounds must satisfy {name}_lo <= {name} <= {name}_hi")


class DiameterMetricsV0(ContractModel):
    """Diameter agreement (``diam_metrics``). If ``n < 3`` every float is null."""

    n: int = Field(ge=0)
    mae: NonNegativeFloat | None
    rmse: NonNegativeFloat | None
    bias: float | None
    loa_low: float | None
    loa_high: float | None
    within_2mm: UnitInterval | None
    within_3mm: UnitInterval | None
    spearman: Annotated[float, Field(ge=-1.0, le=1.0)] | None

    @model_validator(mode="after")
    def _consistent(self) -> DiameterMetricsV0:
        floats = (self.mae, self.rmse, self.bias, self.loa_low, self.loa_high, self.within_2mm, self.within_3mm)
        if self.n < 3 and any(v is not None for v in (*floats, self.spearman)):
            raise ValueError("with n < 3 every diameter metric must be null")
        if self.n >= 3 and any(v is None for v in floats):
            # spearman may still be NaN->null (constant input), the rest cannot.
            raise ValueError("with n >= 3 mae, rmse, bias, loa and within_* are required")
        if self.mae is not None and self.rmse is not None and self.rmse + _EPS < self.mae:
            raise ValueError("rmse cannot be below mae")
        if self.loa_low is not None and self.loa_high is not None and self.bias is not None:
            if not (self.loa_low - _EPS <= self.bias <= self.loa_high + _EPS):
                raise ValueError("bias must lie within the limits of agreement")
        if self.within_2mm is not None and self.within_3mm is not None and self.within_2mm > self.within_3mm + _EPS:
            raise ValueError("within_2mm cannot exceed within_3mm")
        return self


class DiceMetricsV0(ContractModel):
    """Per-dataset Dice summary. Key names contain a dot, hence the aliases."""

    median: UnitInterval
    mean: UnitInterval
    share_below_0_90: UnitInterval = Field(alias="share_below_0.90")
    share_below_0_85: UnitInterval = Field(alias="share_below_0.85")

    @model_validator(mode="after")
    def _nested(self) -> DiceMetricsV0:
        if self.share_below_0_85 > self.share_below_0_90 + _EPS:
            raise ValueError("share below 0.85 cannot exceed share below 0.90")
        return self


class EmptyObject(ContractModel):
    """``{}``: written when there is no ``pred_aorta_dice`` column."""


class PerformanceV0(ContractModel):
    aaa_missing_as_wrong: BinMetricsV0
    aaa_when_answered: BinMetricsV0
    diameter: DiameterMetricsV0
    dice: DiceMetricsV0 | EmptyObject

    @model_validator(mode="after")
    def _modes_agree(self) -> PerformanceV0:
        wrong, answered = self.aaa_missing_as_wrong, self.aaa_when_answered
        if answered.n_no_answer != 0:
            raise ValueError("aaa_when_answered.n_no_answer is always 0")
        if answered.n != wrong.n - wrong.n_no_answer:
            raise ValueError("aaa_when_answered.n must equal missing_as_wrong.n - n_no_answer")
        if answered.n_aaa > wrong.n_aaa or answered.n_not_aaa > wrong.n_not_aaa:
            raise ValueError("dropping no-answers cannot add cases")
        return self


class DiceBlockV0(ContractModel):
    average: UnitInterval = Field(description="Rounded to 3 dp.")
    note: Literal["Baseline model Dice.", "Our team's segmentation."]


class SlicePointFileV0(ContractModel):
    """``<hospital>_slicepoint.json`` as uploaded to the Base44 POC."""

    file_type: Literal["hospital_data"] = Field(alias="fileType")
    hospital_name: str = Field(alias="hospitalName", min_length=1)
    scans: tuple[ScanV0, ...] = Field(min_length=1)
    findings: tuple[FindingV0, ...] = Field(max_length=5)
    notes: tuple[str, ...]
    performance: PerformanceV0
    dice: DiceBlockV0 | None = None

    @model_validator(mode="after")
    def _file_consistent(self) -> SlicePointFileV0:
        checks = [f.check for f in self.findings]
        if len(checks) != len(set(checks)):
            raise ValueError("at most one finding per check")
        wrong = self.performance.aaa_missing_as_wrong
        if wrong.n != len(self.scans):
            raise ValueError("performance.aaa_missing_as_wrong.n must equal the number of scans")
        if wrong.n_no_answer != sum(s.ai_aaa is None for s in self.scans):
            raise ValueError("n_no_answer must equal the number of scans with aiAaa null")
        if all(s.aaa is not None for s in self.scans) and wrong.n_aaa != sum(s.aaa is True for s in self.scans):
            raise ValueError("n_aaa must equal the number of scans with aaa true")
        perf_dice = self.performance.dice
        if (
            self.dice is not None
            and self.dice.note == "Baseline model Dice."
            and isinstance(perf_dice, DiceMetricsV0)
            and abs(self.dice.average - round(perf_dice.mean, 3)) > 5e-4 + _EPS
        ):
            raise ValueError("dice.average (baseline) must be performance.dice.mean rounded to 3 dp")
        return self

    @property
    def site_id(self) -> str:
        return site_id_from_legacy_hospital_name(self.hospital_name)

    def to_legacy_dict(self) -> dict[str, Any]:
        """Dump back to the POC JSON shape (aliases, optional ``dice`` omitted when absent)."""
        out = self.model_dump(mode="json", by_alias=True)
        if self.dice is None:
            del out["dice"]
        return out


# =========================================================================== monthly summary

YearMonth = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
MonthlyVerdictText = Literal["Review needed", "Proceed with care", "Comparable to validation"]


class MonthV0(ContractModel):
    month: YearMonth
    n_scans: int = Field(ge=0)
    labels: StrictBool = Field(description="True if the month had any confirmed labels.")
    red: int = Field(ge=0)
    yellow: int = Field(ge=0)
    green: int = Field(ge=0)
    verdict: MonthlyVerdictText
    red_triggers: tuple[str, ...]
    yellow_triggers: tuple[str, ...]

    @model_validator(mode="after")
    def _consistent(self) -> MonthV0:
        if len(self.red_triggers) != self.red or len(self.yellow_triggers) != self.yellow:
            raise ValueError("trigger lists must match the red/yellow counts")
        expected = "Review needed" if self.red else ("Proceed with care" if self.yellow else "Comparable to validation")
        if self.verdict != expected:
            raise ValueError(f"verdict must be {expected!r} for red={self.red}, yellow={self.yellow}")
        return self


class MonthlySummaryV0(ContractModel):
    """``<hospital>_monthly_summary.json``. ``hospital`` is the raw HOSPITAL_NAME
    (e.g. ``demo_hospital``), unlike slicepoint.json's title-cased name."""

    hospital: str
    reference: str
    scenario: Literal["stable", "drift", "no_answer", "real data"]
    first_month_with_a_red_alert: YearMonth | None
    history_file: str
    months: tuple[MonthV0, ...]

    @model_validator(mode="after")
    def _consistent(self) -> MonthlySummaryV0:
        names = [m.month for m in self.months]
        if names != sorted(set(names)):
            raise ValueError("months must be unique and ascending")
        first_red = next((m.month for m in self.months if m.red), None)
        if self.first_month_with_a_red_alert != first_red:
            raise ValueError("first_month_with_a_red_alert must be the first month with red > 0")
        return self


# =========================================================================== dice.json (INFERRED)


class DiceSummaryV0(ContractModel):
    """**INFERRED** contract for ``<hospital>_dice.json``.

    No writer exists in the repo; the segmentation notebook that produced it was never
    committed. The POC spec (p.24) says it carries mean Dice, with median and share below
    0.90 optional and "missing in the demo". Unknown extra keys are tolerated, and both
    ``share_below_0_90`` and ``share_below_0.90`` spellings are accepted.
    """

    model_config = ConfigDict(extra="allow")

    average: UnitInterval
    median: UnitInterval | None = None
    share_below_0_90: UnitInterval | None = Field(
        default=None, validation_alias=AliasChoices("share_below_0_90", "share_below_0.90")
    )


# =========================================================================== /v1/compare


class CompareMetricsV1(ContractModel):
    dice: UnitInterval
    iou: UnitInterval
    prediction_volume_ml: NonNegativeFloat
    reference_volume_ml: NonNegativeFloat
    hd95_mm: NonNegativeFloat | None
    empty_prediction: StrictBool
    empty_reference: StrictBool
    hd95_status: Literal["ok", "both_empty", "empty_mask", "sheared_grid"]

    @model_validator(mode="after")
    def _consistent(self) -> CompareMetricsV1:
        status, hd = self.hd95_status, self.hd95_mm
        if status == "ok" and hd is None:
            raise ValueError("hd95_status ok requires hd95_mm")
        if status == "both_empty" and (hd != 0.0 or not (self.empty_prediction and self.empty_reference)):
            raise ValueError("both_empty requires both masks empty and hd95_mm == 0")
        if status in ("empty_mask", "sheared_grid") and hd is not None:
            raise ValueError(f"hd95_status {status} requires hd95_mm null")
        if self.empty_prediction and self.empty_reference and self.dice != 1.0:
            raise ValueError("Dice of two empty masks is defined as 1.0")
        return self


class AgreementThresholdsV1(ContractModel):
    high_agreement: str
    review_with_caution: str
    low_agreement: str


class AgreementAssessmentV1(ContractModel):
    status: Literal["empty_mask_review", "high_agreement", "review_with_caution", "low_agreement"]
    review_priority: Literal["high", "low", "medium"]
    message: str
    dice_percent: Annotated[float, Field(ge=0.0, le=100.0)]
    clinical_correctness_established: Literal[False]
    interpretation: str
    thresholds: AgreementThresholdsV1


class ModelProvenanceV1(ContractModel):
    model: Literal["TotalSegmentator"]
    version: str
    task: Literal["total"]
    roi: Literal["aorta"]
    fast: StrictBool
    device: str
    elapsed_seconds: NonNegativeFloat
    input_sha256: Sha256Hex
    mask_sha256: Sha256Hex


class DisplayV1(ContractModel):
    plane: Literal["axial"]
    canonical_slice_index: int = Field(ge=0)
    selection: str
    ct_window_hu: tuple[float, float]
    score_dimension: Literal["3D"]


class ImageV1(ContractModel):
    media_type: Literal["image/png"]
    data_url: Annotated[str, StringConstraints(pattern=r"^data:image/png;base64,")]


class PredictedMaskV1(ContractModel):
    media_type: Literal["application/gzip"]
    filename: str
    base64: str


_ASSESSMENT_RULE = {"high_agreement": "low", "review_with_caution": "medium", "low_agreement": "high",
                    "empty_mask_review": "high"}


class CompareResponseV1(ContractModel):
    """JSON body of ``POST /v1/compare`` (``response_format=json``).

    Agreement status follows ``presentation.agreement_assessment``: empty mask ->
    empty_mask_review, Dice > 0.9 high, >= 0.7 review_with_caution, else low. Agreement is
    not clinical correctness (``clinical_correctness_established`` is always false).
    """

    schema_version: Literal["1.0"]
    comparison_type: Literal["model_vs_vendor_mask_agreement"]
    metrics: CompareMetricsV1
    assessment: AgreementAssessmentV1
    model: ModelProvenanceV1
    display: DisplayV1
    limitation: str
    image: ImageV1 | None = None
    predicted_mask: PredictedMaskV1 | None = None

    @model_validator(mode="after")
    def _assessment_matches(self) -> CompareResponseV1:
        m, a = self.metrics, self.assessment
        if m.empty_prediction or m.empty_reference:
            expected = "empty_mask_review"
        elif m.dice > 0.9:
            expected = "high_agreement"
        elif m.dice >= 0.7:
            expected = "review_with_caution"
        else:
            expected = "low_agreement"
        if a.status != expected:
            raise ValueError(f"assessment.status must be {expected!r} for this Dice/emptiness")
        if a.review_priority != _ASSESSMENT_RULE[a.status]:
            raise ValueError("review_priority does not match status")
        if abs(a.dice_percent - round(m.dice * 100, 2)) > 0.005 + _EPS:
            raise ValueError("dice_percent must be dice * 100 rounded to 2 dp")
        return self


# =========================================================================== converters


def legacy_verdict_to_outcome(text: str) -> VerdictOutcome:
    """Map notebook/monthly verdict text to the new three-state outcome.

    ``REVIEW NEEDED`` / ``Review needed`` -> no_go, ``PROCEED WITH CARE`` -> borderline,
    ``LOOKS COMPARABLE`` / ``Comparable to validation`` -> go. Well-defined because both
    the notebook and the new rule are any-red / any-yellow / else.
    """
    key = text.strip().lower()
    table = {
        "review needed": VerdictOutcome.NO_GO,
        "proceed with care": VerdictOutcome.BORDERLINE,
        "looks comparable": VerdictOutcome.GO,
        "comparable to validation": VerdictOutcome.GO,
    }
    try:
        return table[key]
    except KeyError:
        raise ValueError(f"unknown legacy verdict text {text!r}") from None


def finding_to_check_result(finding: FindingV0, *, n: int) -> CheckResult:
    """One legacy finding -> :class:`CheckResult`. ``score`` and failing sub-factors are
    left empty: the POC never computed them."""
    return CheckResult(
        check_id=finding.check,
        status=CheckStatus.from_legacy(finding.status),
        n=n,
        summary=finding.sentence,
        source="legacy_v0",
    )


def slicepoint_file_to_check_results(file: SlicePointFileV0) -> tuple[CheckResult, ...]:
    """Every finding as a :class:`CheckResult`.

    LEGACY-ONLY stand-in: ``n`` is the number of scans in the file, because the POC never
    recorded how many cases each check used. New checks must report their own per-check
    ``n``; do not copy this convention.

    A check with no finding is *absent*, not ok: the POC drops a check when nothing mapped
    to it, which is not evidence that it passed.
    """
    n = len(file.scans)
    return tuple(finding_to_check_result(f, n=n) for f in file.findings)


def slicepoint_file_to_verdict(
    file: SlicePointFileV0, profile: ThresholdProfile = HACKATHON_DEFAULT_PROFILE
) -> Verdict:
    """Derive a verdict for a legacy file with :func:`derive_verdict`. Checks missing from
    the file are reported as not evaluated."""
    return derive_verdict(slicepoint_file_to_check_results(file), profile, site_id=file.site_id)
