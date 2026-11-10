"""Thresholds are configuration, not constants (ADR 0001, section 6).

A :class:`ThresholdProfile` belongs to a model (and optionally a site) and records where
every number came from. :data:`HACKATHON_DEFAULT_PROFILE` reproduces the POC values.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, ValidationInfo, model_validator

from .checks import CheckStatus, registry_from_context
from .common import ContractModel, SiteId, UnitInterval, VersionedModel

ProfileId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class Worse(str, Enum):
    """Which direction of a trigger value is bad."""

    HIGH = "high"
    LOW = "low"


class TriggerKind(str, Enum):
    """Display unit of a trigger value (history.csv ``kind``)."""

    PCT = "pct"
    PP = "pp"
    SD = "sd"
    MM = "mm"
    NUM2 = "num2"


class TriggerThreshold(ContractModel):
    """A yellow/red threshold pair with a direction.

    Ordering must agree with ``worse``: for ``high`` red > yellow, for ``low`` red < yellow.
    Comparisons are strict, as in ``monitor.evaluate``.
    """

    yellow: float
    red: float
    worse: Worse
    kind: TriggerKind | None = None

    @model_validator(mode="after")
    def _ordering(self) -> TriggerThreshold:
        if self.worse is Worse.HIGH and not self.red > self.yellow:
            raise ValueError(f"worse=high needs red > yellow (got red={self.red}, yellow={self.yellow})")
        if self.worse is Worse.LOW and not self.red < self.yellow:
            raise ValueError(f"worse=low needs red < yellow (got red={self.red}, yellow={self.yellow})")
        return self

    def classify(self, value: float | None) -> CheckStatus | None:
        """The monitor.py status rule. ``None`` stands for monitor's ``n/a``.

        Exception not captured here: monitor overrides "Aneurysms the model caught" to RED
        when the Wilson *upper* bound is below 0.70, not when the point value is.
        """
        if value is None or value != value:
            return None
        if self.worse is Worse.HIGH:
            bad_red, bad_yellow = value > self.red, value > self.yellow
        else:
            bad_red, bad_yellow = value < self.red, value < self.yellow
        if bad_red:
            return CheckStatus.PROBLEM
        if bad_yellow:
            return CheckStatus.WATCH
        return CheckStatus.OK


class Provenance(ContractModel):
    source: str = Field(min_length=1)
    author: str = Field(min_length=1)
    date: dt.date
    notes: str | None = None


class AaaRules(ContractModel):
    """AAA-specific decision rules. Other imaging AI would carry a different block; the
    checks themselves generalize."""

    decision_line_mm: float = Field(gt=0, description="AAA if max diameter >= this.")
    large_aneurysm_line_mm: float = Field(gt=0, description="Boundary of the >=55mm class.")
    nearby_window_mm: float = Field(gt=0, description="'Near the decision line' window (+/-).")
    size_tolerance_mm: float = Field(gt=0, description="Size-within-tolerance cutoff.")
    bland_altman_tolerance_mm: float = Field(gt=0)

    @model_validator(mode="after")
    def _lines(self) -> AaaRules:
        if not self.decision_line_mm < self.large_aneurysm_line_mm:
            raise ValueError("decision_line_mm must be below large_aneurysm_line_mm")
        return self


class DiceMarkers(ContractModel):
    """UI markers on the Dice chart."""

    lower: UnitInterval
    upper: UnitInterval

    @model_validator(mode="after")
    def _order(self) -> DiceMarkers:
        if not self.lower < self.upper:
            raise ValueError("Dice markers must satisfy lower < upper")
        return self


def _resolve_path(root: BaseModel, path: str) -> bool:
    node: object = root
    for part in path.split("."):
        if isinstance(node, BaseModel) and part in type(node).model_fields:
            node = getattr(node, part)
        elif isinstance(node, Mapping) and part in node:
            node = node[part]
        else:
            return False
    return True


class ThresholdProfile(VersionedModel):
    """All configurable numbers for one model (and optionally one site).

    ``check_targets`` keys are the checks this profile expects; a verdict treats any of
    them that did not run as *not evaluated*. ``value_sources`` maps a dotted field path
    (``aaa.decision_line_mm``, ``triggers.No-answer rate``) to a citation.
    """

    profile_id: ProfileId
    model_id: str = Field(min_length=1)
    site_id: SiteId | None = None
    provenance: Provenance
    aaa: AaaRules | None = None
    dice_markers: DiceMarkers | None = None
    min_group_size: int = Field(gt=0, description="Minimum subgroup n for subgroup flags.")
    check_targets: dict[str, int] = Field(min_length=1)
    triggers: dict[str, TriggerThreshold] = Field(default_factory=dict)
    value_sources: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self, info: ValidationInfo) -> ThresholdProfile:
        registry = registry_from_context(info)
        for check_id, target in self.check_targets.items():
            if check_id not in registry:
                raise ValueError(f"check_targets: unknown check_id {check_id!r}")
            if not 0 <= target <= 100:
                raise ValueError(f"check_targets[{check_id}] must be in 0..100")
        for path in self.value_sources:
            if not _resolve_path(self, path):
                raise ValueError(f"value_sources: {path!r} does not name a field of this profile")
        return self


_SPEC = "docs/Slicepoint POC Reconstruction Spec.pdf p.24-25 (UI constants; no code backs them)"
_MON = "slicepoint/python_notebooks/monitor.py evaluate() L46-155"
_NB = "slicepoint/python_notebooks/test_your_hospital.ipynb"

_TRIGGERS: dict[str, TriggerThreshold] = {
    "No-answer rate": TriggerThreshold(yellow=0.02, red=0.04, worse=Worse.HIGH, kind=TriggerKind.PCT),
    "Change in share of scans called AAA": TriggerThreshold(
        yellow=0.05, red=0.10, worse=Worse.HIGH, kind=TriggerKind.PP
    ),
    "Shift in predicted aorta size": TriggerThreshold(
        yellow=0.25, red=0.50, worse=Worse.HIGH, kind=TriggerKind.SD
    ),
    "Scanner brand mix": TriggerThreshold(yellow=0.15, red=0.30, worse=Worse.HIGH, kind=TriggerKind.PCT),
    "Contrast phase mix": TriggerThreshold(yellow=0.15, red=0.30, worse=Worse.HIGH, kind=TriggerKind.PCT),
    "Slice thickness mix": TriggerThreshold(yellow=0.15, red=0.30, worse=Worse.HIGH, kind=TriggerKind.PCT),
    "Sex mix": TriggerThreshold(yellow=0.15, red=0.30, worse=Worse.HIGH, kind=TriggerKind.PCT),
    "Age mix": TriggerThreshold(yellow=0.15, red=0.30, worse=Worse.HIGH, kind=TriggerKind.PCT),
    "Shift in aorta brightness (HU)": TriggerThreshold(
        yellow=0.25, red=0.50, worse=Worse.HIGH, kind=TriggerKind.SD
    ),
    "Rise in missing scanner/patient details": TriggerThreshold(
        yellow=0.05, red=0.10, worse=Worse.HIGH, kind=TriggerKind.PCT
    ),
    "Scans unlike anything in the reference": TriggerThreshold(
        yellow=0.10, red=0.20, worse=Worse.HIGH, kind=TriggerKind.PCT
    ),
    "Near-duplicate scans": TriggerThreshold(yellow=0.01, red=0.03, worse=Worse.HIGH, kind=TriggerKind.PCT),
    "Duplicates filed under different patient IDs": TriggerThreshold(
        yellow=0.005, red=0.02, worse=Worse.HIGH, kind=TriggerKind.PCT
    ),
    "Broken aorta 3D shapes": TriggerThreshold(
        yellow=0.05, red=0.15, worse=Worse.HIGH, kind=TriggerKind.PCT
    ),
    "Aneurysms the model caught": TriggerThreshold(
        yellow=0.80, red=0.70, worse=Worse.LOW, kind=TriggerKind.PCT
    ),
    "Average diameter error": TriggerThreshold(yellow=2.0, red=3.0, worse=Worse.HIGH, kind=TriggerKind.MM),
    "Labels that disagree with the 30 mm rule": TriggerThreshold(
        yellow=0.02, red=0.05, worse=Worse.HIGH, kind=TriggerKind.PCT
    ),
    "Outline quality (Dice)": TriggerThreshold(
        yellow=0.90, red=0.85, worse=Worse.LOW, kind=TriggerKind.NUM2
    ),
}

HACKATHON_DEFAULT_PROFILE = ThresholdProfile(
    profile_id="hackathon-default-v0",
    model_id="hackathon-baseline-aaa",
    site_id=None,
    provenance=Provenance(
        source="SlicePoint hackathon POC (notebooks + POC spec), via data-contract-inventory.md",
        author="SlicePoint student team; transcribed by slicepoint-schemas",
        date=dt.date(2026, 11, 9),
        notes=(
            "Reproduces the POC, not a clinical recommendation. Conflicts: (1) min group "
            "size is 12-14 in the spec vs n>=15 in the notebook flag_row; the notebook "
            "value 15 is used. (2) The spec's Dice UI markers (0.81/0.90) differ from the "
            "notebook/monitor Dice thresholds (red 0.85 / yellow 0.90), which are kept in "
            "triggers. (3) The spec says population SD; the notebook mixes population and "
            "sample SD. Not encoded. (4) monitor.py emits the 'Aneurysms the model caught' "
            "row with worse='high' when there are fewer than 3 aneurysms (value n/a); the "
            "intended direction is low and that is what is stored here."
        ),
    ),
    aaa=AaaRules(
        decision_line_mm=30.0,
        large_aneurysm_line_mm=55.0,
        nearby_window_mm=5.0,
        size_tolerance_mm=3.0,
        bland_altman_tolerance_mm=2.0,
    ),
    dice_markers=DiceMarkers(lower=0.81, upper=0.90),
    min_group_size=15,
    check_targets={"repeats": 90, "scanning": 70, "patients": 70, "labels": 90, "accuracy": 88},
    triggers=_TRIGGERS,
    value_sources={
        "aaa.decision_line_mm": f"{_NB}:80 AAA_CUTOFF_MM = 30; monitor.py:147-148; spec",
        "aaa.large_aneurysm_line_mm": f"{_NB} cell 15 size-class expectation (<55 -> 30-54mm); spec",
        "aaa.nearby_window_mm": _SPEC,
        "aaa.size_tolerance_mm": f"{_SPEC}; matches performance.diameter.within_3mm",
        "aaa.bland_altman_tolerance_mm": f"{_SPEC}; matches performance.diameter.within_2mm",
        "dice_markers.lower": _SPEC,
        "dice_markers.upper": _SPEC,
        "min_group_size": f"{_NB}:944 flag_row n >= 15 (spec says 12-14; notebook wins)",
        "check_targets.repeats": _SPEC,
        "check_targets.scanning": _SPEC,
        "check_targets.patients": _SPEC,
        "check_targets.labels": _SPEC,
        "check_targets.accuracy": _SPEC,
        **{f"triggers.{name}": _MON for name in _TRIGGERS},
    },
)
"""POC thresholds with per-value provenance. See ``provenance.notes`` for conflicts."""
