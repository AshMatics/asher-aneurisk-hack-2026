"""Checks: status, descriptors, results and the registry (ADR 0001, section 6).

Status is primary. The POC notebook only ever emits a categorical status per check
(``OK`` / ``Watch`` / ``Problem``). The 0-100 scores shown in the POC UI have **no
formula anywhere in the repo**, so ``score`` is optional and must name its
``score_method`` when present.

Adding a check is data-only: add a :class:`CheckDescriptor` to a :class:`CheckRegistry`
and pass that registry through the validation context
(``model_validate(data, context={CHECK_REGISTRY_CONTEXT_KEY: registry})``).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Literal

from pydantic import Field, ValidationInfo, model_validator

from .common import CheckId, ContractModel, VersionedModel

CHECK_REGISTRY_CONTEXT_KEY = "check_registry"


class CheckStatus(str, Enum):
    """Categorical outcome of one check. Ordered ok < watch < problem."""

    OK = "ok"
    WATCH = "watch"
    PROBLEM = "problem"

    @property
    def rank(self) -> int:
        return _RANK[self]

    @classmethod
    def from_legacy(cls, value: str) -> CheckStatus:
        """Map POC ``OK`` / ``Watch`` / ``Problem`` (slicepoint.json findings)."""
        try:
            return _LEGACY[value]
        except KeyError:
            raise ValueError(f"unknown legacy status {value!r}") from None

    @classmethod
    def from_severity(cls, value: str) -> CheckStatus:
        """Map notebook severities ``red`` / ``yellow`` / ``ok``.

        ``info`` is not a status: the notebook routes it to notes, so it raises here.
        """
        try:
            return _SEVERITY[value]
        except KeyError:
            raise ValueError(f"severity {value!r} has no check status (info goes to notes)") from None

    @classmethod
    def from_trigger(cls, value: str) -> CheckStatus | None:
        """Map monitor trigger status ``GREEN`` / ``YELLOW`` / ``RED``; ``n/a`` -> None."""
        if value == "n/a":
            return None
        try:
            return _TRIGGER[value]
        except KeyError:
            raise ValueError(f"unknown trigger status {value!r}") from None


_RANK = {CheckStatus.OK: 0, CheckStatus.WATCH: 1, CheckStatus.PROBLEM: 2}
_LEGACY = {"OK": CheckStatus.OK, "Watch": CheckStatus.WATCH, "Problem": CheckStatus.PROBLEM}
_SEVERITY = {"ok": CheckStatus.OK, "yellow": CheckStatus.WATCH, "red": CheckStatus.PROBLEM}
_TRIGGER = {"GREEN": CheckStatus.OK, "YELLOW": CheckStatus.WATCH, "RED": CheckStatus.PROBLEM}


class Audience(str, Enum):
    """Who a check card is written for. INFERRED from ADR 0001 section 7 (decision
    committee, clinicians, analysts); the POC has no such field."""

    COMMITTEE = "committee"
    CLINICIAN = "clinician"
    ANALYST = "analyst"


class SubFactor(ContractModel):
    id: CheckId
    title: str = Field(min_length=1)


class CheckDescriptor(ContractModel):
    """What a check is, independent of any result. The UI renders cards from this."""

    id: CheckId
    title: str = Field(min_length=1, description="UI title.")
    definition: str = Field(min_length=1)
    target: int | None = Field(
        default=None, ge=0, le=100, description="Default target score from the POC spec."
    )
    sub_factors: tuple[SubFactor, ...] = ()
    audience: tuple[Audience, ...] = (Audience.COMMITTEE,)
    legacy_check_key: str | None = Field(
        default=None, description="The `check` value used in POC slicepoint.json findings."
    )

    @model_validator(mode="after")
    def _unique_sub_factors(self) -> CheckDescriptor:
        ids = [s.id for s in self.sub_factors]
        if len(ids) != len(set(ids)):
            raise ValueError(f"check {self.id}: duplicate sub-factor ids")
        return self


class CheckRegistry(VersionedModel):
    """A set of check descriptors, keyed by id. Serializable, so it can be config."""

    checks: tuple[CheckDescriptor, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> CheckRegistry:
        ids = [c.id for c in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate check ids in registry")
        return self

    def as_mapping(self) -> Mapping[str, CheckDescriptor]:
        return MappingProxyType({c.id: c for c in self.checks})


def _sf(id_: str, title: str) -> SubFactor:
    return SubFactor(id=id_, title=title)


DEFAULT_CHECK_REGISTRY = CheckRegistry(
    checks=(
        CheckDescriptor(
            id="repeats",
            title="Different people",
            definition=(
                "Scans per distinct person: guards against repeat scans and patient "
                "leakage inflating accuracy. Notebook logic: near-duplicate groups "
                "(cosine > 0.95 or same patient_id) and the random vs by-patient split test."
            ),
            target=90,
            sub_factors=(
                _sf("scans", "Scans"),
                _sf("people", "People"),
                _sf("leakage", "Random vs by-person split leakage"),
            ),
            legacy_check_key="repeats",
        ),
        CheckDescriptor(
            id="scanning",
            title="Scan settings match",
            definition=(
                "Similarity of the acquisition mix to the reference; the card shows the "
                "lowest of scanner, contrast and slice thickness. Notebook logic: TVD, "
                "HU/kVp/slice Wasserstein, embedding domain AUC, coverage, impossible values."
            ),
            target=70,
            sub_factors=(
                _sf("scanner_vendor", "Scanner"),
                _sf("contrast_phase", "Contrast"),
                _sf("slice_thickness_class", "Slice thickness"),
                _sf("domain_auc", "Scans distinguishable from the reference (domain AUC)"),
                _sf("coverage", "Scans outside the reference's coverage"),
                _sf("hu_shift", "Aorta brightness (HU) shift"),
                _sf("kvp_shift", "Tube voltage (kVp) shift"),
            ),
            legacy_check_key="scanning",
        ),
        CheckDescriptor(
            id="patients",
            title="Patients match",
            definition=(
                "Similarity of the patient mix to the reference; the card shows the lowest "
                "of sex, age and AAA size class. Notebook logic: TVD on sex/age, prevalence "
                "Fisher test, diameter Wasserstein (routed here by keyword)."
            ),
            target=70,
            sub_factors=(
                _sf("sex", "Sex"),
                _sf("age_band", "Age"),
                _sf("aaa_size_class", "AAA size class"),
            ),
            legacy_check_key="patients",
        ),
        CheckDescriptor(
            id="labels",
            title="Labels follow 30 mm rule",
            definition=(
                "Share of labels consistent with the AAA decision line. Notebook logic: "
                "conflict share, smallest labelled AAA, best-cutoff range vs reference."
            ),
            target=90,
            sub_factors=(
                _sf("rule_conflicts", "Labels disagreeing with the decision line"),
                _sf("cutoff_alignment", "Cutoff alignment with reference"),
            ),
            legacy_check_key="labels",
        ),
        CheckDescriptor(
            id="accuracy",
            title="AI accuracy",
            definition=(
                "Composite of segmentation Dice, size within tolerance and aneurysms "
                "caught. Notebook logic: binary/diameter/Dice metrics, subgroups, "
                "silent failures (no-answers), measurement outliers."
            ),
            target=88,
            sub_factors=(
                _sf("dice", "Outline quality (Dice)"),
                _sf("size_within_tolerance", "Size within tolerance"),
                _sf("aneurysms_caught", "Aneurysms caught"),
                _sf("no_answers", "Model gave no answer"),
                _sf("specificity", "False alarms (specificity)"),
                _sf("subgroups", "Problems in subgroups"),
            ),
            audience=(Audience.COMMITTEE, Audience.CLINICIAN),
            legacy_check_key="accuracy",
        ),
    )
)
"""The five POC checks. Titles and targets from the POC spec (p.24-25); sub-factor ids
for ``labels`` are INFERRED from the feeding notebook logic (the spec lists none). The
sub-factors after the spec's three per card (leakage, domain_auc, coverage, hu_shift,
kvp_shift, no_answers, specificity, subgroups) were added by reviewer decision
2026-11-09 so every notebook rule has a named sub-factor. The spec's card shows "the
lowest of" its first three; the UI keeps that rule."""

CHECK_REGISTRY: Mapping[str, CheckDescriptor] = DEFAULT_CHECK_REGISTRY.as_mapping()


def registry_from_context(info: ValidationInfo | None) -> Mapping[str, CheckDescriptor]:
    """Registry passed in the validation context, else the default five checks."""
    ctx = info.context if info is not None else None
    if isinstance(ctx, Mapping):
        reg = ctx.get(CHECK_REGISTRY_CONTEXT_KEY)
        if isinstance(reg, CheckRegistry):
            return reg.as_mapping()
        if isinstance(reg, Mapping):
            return reg
    return CHECK_REGISTRY


class Evidence(ContractModel):
    """One named piece of evidence behind a result (e.g. ``tvd = 0.40``)."""

    key: str = Field(min_length=1)
    value: bool | int | float | str | None = None
    unit: str | None = None
    text: str | None = None


class CheckResult(ContractModel):
    """The outcome of one check for one assessment.

    * ``status`` is primary.
    * ``score`` (0-100) is optional; when present it must name ``score_method`` so a reader
      knows which formula produced it. No formula is agreed yet (ADR open question 2).
    * ``n`` is required: the number of cases (scans) this check actually used, so thin
      evidence is visible. New checks must report their own per-check ``n`` (for example
      the cases with labels, or the AAA-positive cases for sensitivity). Only the legacy
      converter falls back to the file's scan count, because the POC never recorded it.
    * ``n_effective`` (optional) is the effective sample size and must name
      ``n_effective_method`` (e.g. ``kish_design_effect_per_person``, ``cluster_icc``),
      mirroring score/score_method; ``0 < n_effective <= n``. Rationale: repeat scans of the
      same person (hospital_b has 80 scans from 40 real people) and clustering within a
      site are correlated, so they carry less information than ``n`` independent cases.
      That matters for Wilson intervals and for the "too few to judge" suppression, which
      should use the effective size, not the raw scan count.
    * ``subjects`` (optional) is the number of distinct people behind the ``n`` cases, and
      ``subjects <= n``.
    * ``failing_sub_factors`` must be sub-factors of the registered check, and must be empty
      when the status is ``ok``.
    """

    check_id: CheckId
    status: CheckStatus
    n: int = Field(ge=0, description="Cases this check actually used (per-check, not per-file).")
    n_effective: float | None = Field(
        default=None, gt=0, description="Effective sample size; requires n_effective_method."
    )
    n_effective_method: str | None = Field(default=None, min_length=1)
    subjects: int | None = Field(default=None, ge=0, description="Distinct people behind n.")
    score: float | None = Field(default=None, ge=0, le=100)
    score_method: str | None = Field(default=None, min_length=1)
    failing_sub_factors: tuple[CheckId, ...] = ()
    summary: str | None = None
    evidence: tuple[Evidence, ...] = ()
    source: Literal["computed", "legacy_v0"] = "computed"

    @model_validator(mode="after")
    def _consistent(self, info: ValidationInfo) -> CheckResult:
        if self.score is not None and self.score_method is None:
            raise ValueError("score requires score_method")
        if self.score is None and self.score_method is not None:
            raise ValueError("score_method given without a score")
        if self.n_effective is not None and self.n_effective_method is None:
            raise ValueError("n_effective requires n_effective_method")
        if self.n_effective is None and self.n_effective_method is not None:
            raise ValueError("n_effective_method given without n_effective")
        if self.n_effective is not None and self.n_effective > self.n:
            raise ValueError("n_effective cannot exceed n")
        if self.subjects is not None and self.subjects > self.n:
            raise ValueError("subjects cannot exceed n")
        registry = registry_from_context(info)
        descriptor = registry.get(self.check_id)
        if descriptor is None:
            raise ValueError(f"unknown check_id {self.check_id!r}")
        known = {s.id for s in descriptor.sub_factors}
        unknown = [f for f in self.failing_sub_factors if f not in known]
        if unknown:
            raise ValueError(f"check {self.check_id}: unknown sub-factors {unknown}")
        if len(set(self.failing_sub_factors)) != len(self.failing_sub_factors):
            raise ValueError("duplicate failing_sub_factors")
        if self.status is CheckStatus.OK and self.failing_sub_factors:
            raise ValueError("an ok check cannot have failing sub-factors")
        return self
