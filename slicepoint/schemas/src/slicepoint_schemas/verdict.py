"""The three-state verdict.

The rule is **INFERRED**. The POC spec states "GO when all five checks meet target" and
marks that rule itself as inferred; the scores it refers to have no formula. The notebook's
own verdict is "any red -> REVIEW NEEDED, else any yellow -> PROCEED WITH CARE, else LOOKS
COMPARABLE". :func:`derive_verdict` combines the two on status alone:

1. any check ``problem``                         -> ``no_go``
2. else any check ``watch``                      -> ``borderline``
3. else any expected check did not run           -> ``borderline`` (never a silent pass)
4. else                                          -> ``go``

Scores and targets do not enter the rule until a score formula is agreed.

A human (for example the decision committee) may override the derived outcome, but only
through a :class:`VerdictOverride` record that names who, when and why. ``outcome`` always
stays the *derived* outcome and stays consistent with the results; the overriding outcome
lives in ``override.outcome``, and :attr:`Verdict.final_outcome` gives the one to act on.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from .checks import CheckResult, CheckStatus
from .common import CheckId, ContractModel, SiteId, VersionedModel
from .thresholds import ThresholdProfile


class VerdictOutcome(str, Enum):
    GO = "go"
    NO_GO = "no_go"
    BORDERLINE = "borderline"


OVERRIDE_NOTE_MIN_CHARS = 20
"""Minimum length of an override justification, after trimming. Long enough to rule out
"ok", "n/a" or "approved", short enough not to force padding. It is a floor, not a
quality check: the note should say which checks were overridden and on what evidence."""


class VerdictOverride(ContractModel):
    """A human decision that replaces the derived outcome.

    Overriding to ``go`` while checks are ``problem`` or not evaluated is allowed, but only
    through this record, so the departure from the rule is always attributed and justified.
    """

    outcome: VerdictOutcome = Field(description="The final outcome, replacing the derived one.")
    by: Annotated[str, StringConstraints(min_length=1, pattern=r"\S")] = Field(
        description="Who made the decision (person or committee identifier)."
    )
    at: AwareDatetime = Field(description="When, with a timezone.")
    note: str = Field(
        description=f"Required justification, at least {OVERRIDE_NOTE_MIN_CHARS} characters "
        "after trimming whitespace."
    )

    @field_validator("note")
    @classmethod
    def _note_long_enough(cls, value: str) -> str:
        if len(value.strip()) < OVERRIDE_NOTE_MIN_CHARS:
            raise ValueError(
                f"override note must be a justification of at least {OVERRIDE_NOTE_MIN_CHARS} characters"
            )
        return value


class Verdict(VersionedModel):
    """A verdict with its rationale and the results it rests on.

    Validated invariants (hold for any verdict, including a human override):

    * ``go`` requires at least one result, every included result ``ok`` and nothing in
      ``not_evaluated``.
    * ``no_go`` requires at least one ``problem``.
    * check ids are unique and ``not_evaluated`` does not overlap the results.

    These apply to the derived ``outcome``. ``override`` (optional) carries a human
    decision. It must differ from the derived outcome, and :attr:`final_outcome` returns it.
    """

    outcome: VerdictOutcome
    rationale: str = Field(min_length=1)
    results: tuple[CheckResult, ...]
    not_evaluated: tuple[CheckId, ...] = Field(
        default=(), description="Checks the profile expects that produced no result."
    )
    site_id: SiteId | None = None
    profile_id: str | None = None
    model_id: str | None = None
    override: VerdictOverride | None = None

    @property
    def final_outcome(self) -> VerdictOutcome:
        """The outcome to act on: the override's if present, else the derived one."""
        return self.override.outcome if self.override is not None else self.outcome

    def with_override(self, override: VerdictOverride) -> Verdict:
        """Return a validated copy carrying ``override``."""
        fields = {name: getattr(self, name) for name in type(self).model_fields}
        fields["override"] = override
        return Verdict.model_validate(fields)

    @model_validator(mode="after")
    def _consistent(self) -> Verdict:
        ids = [r.check_id for r in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate check_id in verdict results")
        if set(ids) & set(self.not_evaluated):
            raise ValueError("a check cannot be both evaluated and not_evaluated")
        statuses = {r.status for r in self.results}
        if self.outcome is VerdictOutcome.GO:
            if not self.results:
                raise ValueError("go requires at least one check result")
            if statuses != {CheckStatus.OK}:
                raise ValueError("go requires every included check to be ok")
            if self.not_evaluated:
                raise ValueError("go requires every expected check to have been evaluated")
        if self.outcome is VerdictOutcome.NO_GO and CheckStatus.PROBLEM not in statuses:
            raise ValueError("no_go requires at least one check with status problem")
        if self.override is not None and self.override.outcome is self.outcome:
            raise ValueError("override outcome must differ from the derived outcome")
        return self


def derive_verdict(
    results: Iterable[CheckResult],
    profile: ThresholdProfile,
    *,
    site_id: str | None = None,
) -> Verdict:
    """Apply the inferred rule (module docstring) and return a validated :class:`Verdict`."""
    res = tuple(results)
    present = {r.check_id for r in res}
    missing = tuple(c for c in profile.check_targets if c not in present)
    problems = sorted(r.check_id for r in res if r.status is CheckStatus.PROBLEM)
    watches = sorted(r.check_id for r in res if r.status is CheckStatus.WATCH)

    if problems:
        outcome = VerdictOutcome.NO_GO
        rationale = f"Problem in: {', '.join(problems)}."
    elif watches:
        outcome = VerdictOutcome.BORDERLINE
        rationale = f"No problems; watch in: {', '.join(watches)}."
    elif missing or not res:
        outcome = VerdictOutcome.BORDERLINE
        rationale = "All evaluated checks ok, but some expected checks were not evaluated."
    else:
        outcome = VerdictOutcome.GO
        rationale = "All expected checks ok."
    if missing:
        rationale += f" Not evaluated: {', '.join(missing)}."
    rationale += " (Rule inferred from the POC spec and notebook; status-based, scores unused.)"

    return Verdict(
        outcome=outcome,
        rationale=rationale,
        results=res,
        not_evaluated=missing,
        site_id=site_id if site_id is not None else profile.site_id,
        profile_id=profile.profile_id,
        model_id=profile.model_id,
    )
