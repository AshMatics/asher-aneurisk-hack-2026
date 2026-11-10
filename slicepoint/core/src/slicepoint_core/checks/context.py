"""What a check function receives: the site, the reference, the thresholds, and shared
analyses computed once on first use (person grouping, deduplicated table, performance)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property

import numpy as np
import numpy.typing as npt
import pandas as pd
from slicepoint_schemas.checks import CheckStatus
from slicepoint_schemas.legacy import BinMetricsV0, DiceMetricsV0
from slicepoint_schemas.thresholds import ThresholdProfile

from .. import stats as S
from ..ingestion import TabularDataset
from ..params import Params
from ..reference import ReferenceProfile

EvidenceValue = bool | int | float | str | None


class Severity(str, Enum):
    """Notebook severities. ``info`` is not a status: it becomes a note."""

    RED = "red"
    YELLOW = "yellow"
    OK = "ok"
    INFO = "info"

    @property
    def status(self) -> CheckStatus | None:
        return {
            Severity.RED: CheckStatus.PROBLEM,
            Severity.YELLOW: CheckStatus.WATCH,
            Severity.OK: CheckStatus.OK,
        }.get(self)

    @classmethod
    def of(cls, status: CheckStatus | None) -> Severity:
        """Map a trigger classification back to a severity (``None`` -> ``ok``)."""
        if status is CheckStatus.PROBLEM:
            return cls.RED
        if status is CheckStatus.WATCH:
            return cls.YELLOW
        return cls.OK


def worst(*statuses: CheckStatus | None) -> CheckStatus | None:
    present = [s for s in statuses if s is not None]
    return max(present, key=lambda s: s.rank) if present else None


def all_of(*statuses: CheckStatus | None) -> CheckStatus | None:
    """The status reached only when every condition reaches it (AND of rules):
    the least severe of the inputs; ``None`` if any input is ``None``."""
    if any(s is None for s in statuses):
        return None
    return min((s for s in statuses if s is not None), key=lambda s: s.rank)


@dataclass(frozen=True)
class Finding:
    """One observation made by a check.

    ``factor`` names what was examined (``tvd_contrast_phase``). The check spec maps
    factors to the registry's sub-factors. ``area`` is the notebook's finding area, kept
    for the legacy export and the parity suite.
    """

    factor: str
    severity: Severity
    text: str
    area: str
    evidence: Mapping[str, EvidenceValue] = field(default_factory=dict)


def clean_value(v: object) -> EvidenceValue:
    """Coerce numpy scalars and NaN to evidence-safe values."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    return str(v)


class CheckContext:
    """Inputs plus shared, lazily computed analyses. One per assessment."""

    def __init__(self, dataset: TabularDataset, reference: ReferenceProfile, profile: ThresholdProfile) -> None:
        reference.require_space(dataset.space)
        self.dataset = dataset
        self.reference = reference
        self.profile = profile
        self.params = Params(profile)

    @property
    def frame(self) -> pd.DataFrame:
        return self.dataset.frame

    @property
    def n(self) -> int:
        return len(self.dataset)

    @property
    def has_embeddings(self) -> bool:
        return self.dataset.embeddings is not None

    @property
    def reference_has_embeddings(self) -> bool:
        return self.reference.embeddings is not None and self.reference.coverage is not None

    @cached_property
    def people(self) -> S.PersonGrouping:
        return S.group_people(
            self.dataset.embeddings,
            self.frame["patient_id"].to_numpy(dtype=object),
            self.dataset.case_ids,
            threshold=self.params.num("near_duplicate_similarity"),
        )

    @cached_property
    def deduplicated(self) -> pd.DataFrame:
        """One scan per real person (first in row order), as the notebook's ``Dd``."""
        dedup: pd.DataFrame = self.frame[self.people.first_of_each()].reset_index(drop=True)
        return dedup

    def people_stats(self, mask: npt.NDArray[np.bool_] | None = None) -> tuple[int, int, float | None]:
        """(n, subjects, Kish n_effective) over the cases in ``mask`` (all if ``None``)."""
        labels = self.people.labels if mask is None else self.people.labels[mask]
        n = len(labels)
        if n == 0:
            return 0, 0, None
        n_eff = S.kish_effective_n(labels, icc=self.params.num("repeat_scan_icc"))
        return n, len(set(labels.tolist())), min(float(n), n_eff)

    # ------------------------------------------------------------------ performance

    @cached_property
    def bin_missing_as_wrong(self) -> BinMetricsV0 | None:
        if not (self.dataset.has_labels and self.dataset.has_predictions):
            return None
        return S.binary_metrics(self.frame["aaa"].to_numpy(bool), self.frame["pred_aaa_f"].to_numpy(float))

    @cached_property
    def bin_when_answered(self) -> BinMetricsV0 | None:
        if not (self.dataset.has_labels and self.dataset.has_predictions):
            return None
        return S.binary_metrics(
            self.frame["aaa"].to_numpy(bool), self.frame["pred_aaa_f"].to_numpy(float), missing="drop"
        )

    @cached_property
    def diameter(self) -> S.DiameterAgreement | None:
        if not (self.dataset.has_labels and self.dataset.has_predictions):
            return None
        return S.diameter_agreement(
            self.frame["pred_max_diameter_mm"], self.frame["max_aortic_diameter_mm"], tolerances_mm=self.params.tolerances()
        )

    @cached_property
    def dice(self) -> DiceMetricsV0 | None:
        if "pred_aorta_dice" not in self.frame:
            return None
        return S.dice_summary(
            self.frame["pred_aorta_dice"],
            line=self.params.num("dice_poor_outline_line"),
            secondary_line=self.params.num("dice_secondary_line"),
        )
