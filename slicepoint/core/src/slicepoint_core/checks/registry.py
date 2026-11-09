"""The check registry: a check is a descriptor (data) plus one function.

A check function takes a :class:`CheckContext` and returns a :class:`CheckOutput` (its
findings, its own ``n``, an optional score). :func:`evaluate` turns that into a schemas
:class:`~slicepoint_schemas.checks.CheckResult`:

* status = the worst severity among the findings (``ok`` if none was raised);
* failing sub-factors = the registry sub-factors of the non-ok findings;
* evidence = one entry per finding plus the check's own numbers;
* ``subjects`` and Kish ``n_effective`` over the cases the check used.

A check whose required inputs are missing is **skipped** (never ``ok``). Adding a sixth
check means writing one function and registering a :class:`CheckSpec` with its
descriptor; the descriptor joins the schemas registry used for validation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import numpy.typing as npt
from slicepoint_schemas.checks import (
    CHECK_REGISTRY_CONTEXT_KEY,
    CheckDescriptor,
    CheckResult,
    CheckStatus,
    Evidence,
)
from slicepoint_schemas.checks import CheckRegistry as SchemaCheckRegistry

from .context import CheckContext, EvidenceValue, Finding, Severity, clean_value

SCORE_METHOD = "provisional-v0"
"""ADR 0001 open question 2: provisional, unvalidated; not to be shown to a hospital."""

N_EFFECTIVE_METHOD = "kish_design_effect_per_person"


class Requirement(str, Enum):
    """Inputs a check cannot run without."""

    LABELS = "labels"
    PREDICTIONS = "predictions"
    EMBEDDINGS = "embeddings"
    REFERENCE_EMBEDDINGS = "reference_embeddings"
    REFERENCE_LABELS = "reference_labels"


class CheckSkipped(Exception):
    """Raised by a check function when an input it needs turns out to be unusable."""


@dataclass
class CheckOutput:
    findings: list[Finding]
    case_mask: npt.NDArray[np.bool_] | None = None
    """Cases the check used (``None`` = all scans). Drives n, subjects, n_effective."""
    score: float | None = None
    evidence: list[Evidence] = field(default_factory=list)
    not_evaluated_parts: dict[str, str] = field(default_factory=dict)
    """Optional parts that could not run (part -> reason). Recorded as evidence."""


CheckFn = Callable[[CheckContext], CheckOutput]


@dataclass(frozen=True)
class CheckSpec:
    descriptor: CheckDescriptor
    run: CheckFn
    requires: frozenset[Requirement] = frozenset()
    sub_factor_of: Mapping[str, str] = field(default_factory=dict)
    """Finding factor -> descriptor sub-factor id. Unmapped factors are still evidence."""

    def __post_init__(self) -> None:
        known = {s.id for s in self.descriptor.sub_factors}
        bad = {v for v in self.sub_factor_of.values() if v not in known}
        if bad:
            raise ValueError(f"check {self.descriptor.id}: unknown sub-factors {sorted(bad)}")

    @property
    def id(self) -> str:
        return self.descriptor.id


def missing_requirements(spec: CheckSpec, ctx: CheckContext) -> list[str]:
    have = {
        Requirement.LABELS: ctx.dataset.has_labels,
        Requirement.PREDICTIONS: ctx.dataset.has_predictions,
        Requirement.EMBEDDINGS: ctx.has_embeddings,
        Requirement.REFERENCE_EMBEDDINGS: ctx.reference_has_embeddings,
        Requirement.REFERENCE_LABELS: ctx.reference.summary.has_labels,
    }
    return [r.value for r in spec.requires if not have[r]]


class CheckRegistry:
    """Ordered collection of :class:`CheckSpec`."""

    def __init__(self, specs: Iterable[CheckSpec] = ()) -> None:
        self._specs: dict[str, CheckSpec] = {}
        for s in specs:
            self.register(s)

    def register(self, spec: CheckSpec) -> None:
        if spec.id in self._specs:
            raise ValueError(f"check {spec.id!r} already registered")
        self._specs[spec.id] = spec

    def __iter__(self) -> Iterator[CheckSpec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    def __getitem__(self, check_id: str) -> CheckSpec:
        return self._specs[check_id]

    def schema_registry(self) -> SchemaCheckRegistry:
        return SchemaCheckRegistry(checks=tuple(s.descriptor for s in self))

    def validation_context(self) -> dict[str, object]:
        return {CHECK_REGISTRY_CONTEXT_KEY: self.schema_registry()}


def _evidence_from(f: Finding) -> list[Evidence]:
    out = [Evidence(key=f.factor, value=f.severity.value, text=f.text)]
    for k, v in f.evidence.items():
        out.append(Evidence(key=f"{f.factor}.{k}", value=clean_value(v)))
    return out


@dataclass(frozen=True)
class EvaluatedCheck:
    result: CheckResult
    notes: list[str]
    """Texts of the ``info`` findings (the POC's notes)."""
    findings: list[Finding]


def evaluate(spec: CheckSpec, ctx: CheckContext, registry: CheckRegistry) -> EvaluatedCheck:
    """Run one check and turn its output into a validated :class:`CheckResult`."""
    out = spec.run(ctx)
    graded = [f for f in out.findings if f.severity is not Severity.INFO]
    notes = [f.text for f in out.findings if f.severity is Severity.INFO]
    statuses = [s for s in (f.severity.status for f in graded) if s is not None]
    status = max(statuses, key=lambda s: s.rank) if statuses else CheckStatus.OK

    failing: list[str] = []
    for f in graded:
        sub = spec.sub_factor_of.get(f.factor)
        if f.severity is not Severity.OK and sub is not None and sub not in failing:
            failing.append(sub)
    unmapped = [f.factor for f in graded if f.severity is not Severity.OK and f.factor not in spec.sub_factor_of]

    worst_texts = [f.text for f in graded if f.severity.status is status]
    summary = " ".join(worst_texts[:2]) if worst_texts else "Nothing to flag."

    evidence: list[Evidence] = []
    for f in graded:
        evidence.extend(_evidence_from(f))
    for factor in unmapped:
        evidence.append(Evidence(key="failing_factor_without_sub_factor", value=factor))
    for part, reason in out.not_evaluated_parts.items():
        evidence.append(Evidence(key="not_evaluated", value=part, text=reason))
    evidence.extend(out.evidence)

    n, subjects, n_eff = ctx.people_stats(out.case_mask)
    data: dict[str, object] = {
        "check_id": spec.id,
        "status": status,
        "n": n,
        "subjects": subjects,
        "failing_sub_factors": tuple(failing),
        "summary": summary,
        "evidence": tuple(evidence),
    }
    if n_eff is not None:
        data.update(n_effective=n_eff, n_effective_method=N_EFFECTIVE_METHOD)
    if out.score is not None:
        data.update(score=max(0.0, min(100.0, out.score)), score_method=SCORE_METHOD)
    result = CheckResult.model_validate(data, context=registry.validation_context())
    return EvaluatedCheck(result=result, notes=notes, findings=list(out.findings))


def evidence(key: str, value: object, *, unit: str | None = None, text: str | None = None) -> Evidence:
    v: EvidenceValue = clean_value(value)
    return Evidence(key=key, value=v, unit=unit, text=text)
