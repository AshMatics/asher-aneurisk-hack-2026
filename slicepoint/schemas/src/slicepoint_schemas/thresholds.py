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
    Comparisons are strict by default, as in ``monitor.evaluate``; ``inclusive=True`` makes
    them ``>=`` / ``<=`` (the notebook uses that for domain AUC and the cutoff shift).

    Either line may be absent, but not both. The notebook has red-only rules (repeats: any
    near-duplicate share above 1% is red, with no yellow band) and yellow-only rules
    (specificity below 0.90 is at most a watch).
    """

    yellow: float | None
    red: float | None
    worse: Worse
    kind: TriggerKind | None = None
    inclusive: bool = Field(
        default=False, description="Compare with >= / <= instead of the strict > / <."
    )

    @model_validator(mode="after")
    def _ordering(self) -> TriggerThreshold:
        if self.yellow is None and self.red is None:
            raise ValueError("a trigger needs a yellow line, a red line or both")
        if self.yellow is None or self.red is None:
            return self
        if self.worse is Worse.HIGH and not self.red > self.yellow:
            raise ValueError(f"worse=high needs red > yellow (got red={self.red}, yellow={self.yellow})")
        if self.worse is Worse.LOW and not self.red < self.yellow:
            raise ValueError(f"worse=low needs red < yellow (got red={self.red}, yellow={self.yellow})")
        return self

    def crosses(self, value: float, line: float | None) -> bool:
        """True if ``value`` is on the bad side of ``line`` (False when the line is absent)."""
        if line is None:
            return False
        if self.worse is Worse.HIGH:
            return value >= line if self.inclusive else value > line
        return value <= line if self.inclusive else value < line

    def classify(self, value: float | None) -> CheckStatus | None:
        """The monitor.py status rule. ``None`` stands for monitor's ``n/a``.

        Exception not captured here: monitor overrides "Aneurysms the model caught" to RED
        when the Wilson *upper* bound is below 0.70, not when the point value is.
        """
        if value is None or value != value:
            return None
        if self.crosses(value, self.red):
            return CheckStatus.PROBLEM
        if self.crosses(value, self.yellow):
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
    parameters: dict[str, float] = Field(
        default_factory=dict,
        description="Named numbers that are not yellow/red lines: similarity cut-offs, "
        "multipliers, grid bounds, plausible ranges, seeds. Keys are snake_case, no dots.",
    )
    value_sources: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self, info: ValidationInfo) -> ThresholdProfile:
        registry = registry_from_context(info)
        for check_id, target in self.check_targets.items():
            if check_id not in registry:
                raise ValueError(f"check_targets: unknown check_id {check_id!r}")
            if not 0 <= target <= 100:
                raise ValueError(f"check_targets[{check_id}] must be in 0..100")
        for key in (*self.triggers, *self.parameters):
            if "." in key:
                raise ValueError(f"trigger/parameter key {key!r} must not contain '.'")
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

_NB_LINES = (
    "slicepoint/python_notebooks/test_your_hospital.ipynb (see data-contract-inventory.md "
    "section 3, 'Notebook findings')"
)

_NOTEBOOK_TRIGGERS: dict[str, TriggerThreshold] = {
    # repeats (cell 11): red if share_with_near_duplicate > 0.01; no yellow band.
    "repeats_near_duplicate_share": TriggerThreshold(
        yellow=None, red=0.01, worse=Worse.HIGH, kind=TriggerKind.PCT
    ),
    # repeats (cell 11): yellow if any patient_id is missing.
    "repeats_missing_patient_id_count": TriggerThreshold(yellow=0, red=None, worse=Worse.HIGH),
    # leakage (cell 13): red if (honest MAE - random MAE) > 0.15 x honest MAE.
    "repeats_leakage_gap_ratio": TriggerThreshold(yellow=None, red=0.15, worse=Worse.HIGH),
    # scan content (cell 20): AUC >= 0.80 red, >= 0.65 yellow (inclusive).
    "scanning_domain_auc": TriggerThreshold(yellow=0.65, red=0.80, worse=Worse.HIGH, inclusive=True),
    # impossible values (cell 15): any value outside the plausible ranges is red.
    "scanning_implausible_value_count": TriggerThreshold(yellow=None, red=0, worse=Worse.HIGH),
    # embeddings (cell 26): yellow if acquisition signal > AAA signal + 0.10.
    "scanning_embedding_shortcut_margin": TriggerThreshold(yellow=0.10, red=None, worse=Worse.HIGH),
    # numeric Wasserstein permutation test (cell 19): red if p < 0.01 AND shift > 0.5 SD;
    # yellow if p < 0.05 AND shift > 0.25 SD. Both lines must be crossed.
    "numeric_shift_sd": TriggerThreshold(yellow=0.25, red=0.50, worse=Worse.HIGH, kind=TriggerKind.SD),
    "numeric_shift_p": TriggerThreshold(yellow=0.05, red=0.01, worse=Worse.LOW),
    # NEW vs POC (reviewer decision 2026-11-09): alert on the AAA size-class mix like the
    # other category mixes. The notebook never alerted on it.
    "AAA size class mix": TriggerThreshold(yellow=0.15, red=0.30, worse=Worse.HIGH, kind=TriggerKind.PCT),
    # AAA prevalence (cell 19): yellow if Fisher p < 0.05 AND |difference| > 0.05.
    "patients_prevalence_fisher_p": TriggerThreshold(yellow=0.05, red=None, worse=Worse.LOW),
    "patients_prevalence_abs_diff": TriggerThreshold(
        yellow=0.05, red=None, worse=Worse.HIGH, kind=TriggerKind.PP
    ),
    # labelling (cell 15): red if the smallest AAA label is more than 3 mm below the line.
    "labels_smallest_aaa_below_line_mm": TriggerThreshold(
        yellow=None, red=3.0, worse=Worse.HIGH, kind=TriggerKind.MM
    ),
    # labelling (cell 15): yellow if any size class disagrees with its own diameter.
    "labels_size_class_mismatch_count": TriggerThreshold(yellow=0, red=None, worse=Worse.HIGH),
    # labelling vs model (cell 24): |cutoff midpoint shift| >= 3 mm red, >= 2 mm yellow.
    "labels_cutoff_shift_mm": TriggerThreshold(
        yellow=2.0, red=3.0, worse=Worse.HIGH, kind=TriggerKind.MM, inclusive=True
    ),
    # AAA model (cell 22): specificity < 0.90 is a watch.
    "accuracy_specificity": TriggerThreshold(yellow=0.90, red=None, worse=Worse.LOW, kind=TriggerKind.PCT),
    # measurement outliers (cell 17): any |error| > 3 x SD(reference error) is a watch.
    "accuracy_measurement_outlier_count": TriggerThreshold(yellow=0, red=None, worse=Worse.HIGH),
    # subgroups (cell 23): any flagged subgroup is a watch.
    "accuracy_subgroup_flag_count": TriggerThreshold(yellow=0, red=None, worse=Worse.HIGH),
    # Dice (cell 29): median < 0.85 red, < 0.90 yellow; share below 0.90 > 0.10 yellow.
    "accuracy_dice_median": TriggerThreshold(yellow=0.90, red=0.85, worse=Worse.LOW, kind=TriggerKind.NUM2),
    "accuracy_dice_share_below_line": TriggerThreshold(
        yellow=0.10, red=None, worse=Worse.HIGH, kind=TriggerKind.PCT
    ),
}

_NOTEBOOK_PARAMETERS: dict[str, float] = {
    "near_duplicate_similarity": 0.95,  # SIM_DUP, ipynb:81
    "random_seed": 0,  # every random_state / default_rng seed in the notebook
    "cv_folds": 5,  # KFold / GroupKFold / StratifiedGroupKFold(5)
    "embedding_max_pcs": 32,  # PCA(min(32, ...)) in domain_auc, fit_reference, make_model
    "coverage_knn_k": 5,  # fit_reference k=5
    "coverage_percentile": 95,  # fit_reference dist_thr percentile
    "permutation_count": 1000,  # w_test n_perm
    "numeric_test_min_n": 5,  # w_test returns n/a below 5 values per side
    "min_aaa_for_sensitivity": 3,  # n_aaa >= 3 (AAA model, subgroups)
    "subgroup_mae_ref_multiple": 2.0,  # flag_row: mae > max(2.0, 2 x ref_mae)
    "subgroup_hospital_wide_share": 0.8,  # "hospital-wide" if hits >= 80% of eligible groups
    "evidence_gap_min_n": 10,  # evidence gaps: n >= 10 and n_aaa == 0
    "outlier_sd_multiple": 3.0,  # |err| > 3 x SD(reference error)
    "smallest_dataset_scans": 50,  # Files: "Only N scans" below 50
    "cutoff_grid_low_mm": 20.0,  # cutoff_range grid np.arange(20, 40.01, 0.5)
    "cutoff_grid_high_mm": 40.0,
    "cutoff_grid_step_mm": 0.5,
    "dice_poor_outline_line": 0.90,  # share_below_0.90, poor-outline split
    "dice_secondary_line": 0.85,  # share_below_0.85 (reported only)
    "poor_outline_error_ratio": 2.0,  # e_low > 2 x e_hi
    "poor_outline_error_floor_mm": 2.0,  # and e_low > 2 mm
    "poor_outline_min_cases": 3,  # 3 <= low.sum() < n - 3
    "embedding_probe_min_class_n": 10,  # predictability: classes with >= 10 scans
    "embedding_probe_min_rows": 25,  # predictability: at least 25 rows
    "leakage_mlp_max_iter": 3000,  # make_model MLPRegressor(max_iter=3000)
    "plausible_diameter_low_mm": 8.0,  # ranges (cell 15)
    "plausible_diameter_high_mm": 120.0,
    "plausible_hu_low": -150.0,
    "plausible_hu_high": 1000.0,
    "plausible_kvp_low": 70.0,
    "plausible_kvp_high": 150.0,
    "plausible_slice_low_mm": 0.1,
    "plausible_slice_high_mm": 10.0,
    "repeat_scan_icc": 1.0,  # NEW (not in the notebook): ICC for the Kish design effect
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
            "sample SD; slicepoint-core uses population SD (ddof=0) throughout, see core PARITY.md. (4) monitor.py emits the 'Aneurysms the model caught' "
            "row with worse='high' when there are fewer than 3 aneurysms (value n/a); the "
            "intended direction is low and that is what is stored here. (5) The notebook-specific "
            "rules (triggers with snake_case keys and `parameters`) were added for "
            "slicepoint-core milestone 1; they are transcribed from test_your_hospital.ipynb "
            "and are what the five checks read."
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
    triggers={**_TRIGGERS, **_NOTEBOOK_TRIGGERS},
    parameters=_NOTEBOOK_PARAMETERS,
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
        **{f"triggers.{name}": _NB_LINES for name in _NOTEBOOK_TRIGGERS if name != "AAA size class mix"},
        "triggers.AAA size class mix": "reviewer decision 2026-11-09, new vs POC (same lines as the other mixes)",
        **{f"parameters.{name}": _NB_LINES for name in _NOTEBOOK_PARAMETERS if name != "repeat_scan_icc"},
        "parameters.repeat_scan_icc": (
            "slicepoint-core (new, not in the POC): ICC for the Kish design effect of repeat "
            "scans per person. 1.0 treats repeat scans of one person as fully redundant, so "
            "n_effective = (sum m)^2 / sum m^2, the conservative bound."
        ),
    },
)
"""POC thresholds with per-value provenance. See ``provenance.notes`` for conflicts."""
