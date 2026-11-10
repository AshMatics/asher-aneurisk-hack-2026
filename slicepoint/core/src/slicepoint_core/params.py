"""Typed access to a :class:`ThresholdProfile` with clear errors for missing entries.

Checks never hard-code a threshold. They read it here, and a profile that lacks one fails
loudly with the key it needs.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from slicepoint_schemas.checks import CheckStatus
from slicepoint_schemas.thresholds import ThresholdProfile, TriggerThreshold


class MissingThresholdError(KeyError):
    """The threshold profile lacks a value a check needs."""


class Params:
    def __init__(self, profile: ThresholdProfile) -> None:
        self.profile = profile

    def num(self, key: str) -> float:
        try:
            return float(self.profile.parameters[key])
        except KeyError:
            raise MissingThresholdError(f"profile {self.profile.profile_id} has no parameter {key!r}") from None

    def int(self, key: str) -> int:
        return int(round(self.num(key)))

    def trigger(self, key: str) -> TriggerThreshold:
        try:
            return self.profile.triggers[key]
        except KeyError:
            raise MissingThresholdError(f"profile {self.profile.profile_id} has no trigger {key!r}") from None

    def classify(self, key: str, value: float | None) -> CheckStatus | None:
        return self.trigger(key).classify(value)

    @property
    def decision_line_mm(self) -> float:
        if self.profile.aaa is None:
            raise MissingThresholdError(f"profile {self.profile.profile_id} has no aaa rules")
        return self.profile.aaa.decision_line_mm

    @property
    def large_aneurysm_line_mm(self) -> float:
        if self.profile.aaa is None:
            raise MissingThresholdError(f"profile {self.profile.profile_id} has no aaa rules")
        return self.profile.aaa.large_aneurysm_line_mm

    def tolerances(self) -> tuple[float, float]:
        """(Bland-Altman tolerance, size tolerance) in mm."""
        if self.profile.aaa is None:
            raise MissingThresholdError(f"profile {self.profile.profile_id} has no aaa rules")
        return self.profile.aaa.bland_altman_tolerance_mm, self.profile.aaa.size_tolerance_mm

    def cutoff_grid(self) -> npt.NDArray[np.floating]:
        from .stats import cutoff_grid

        return cutoff_grid(self.num("cutoff_grid_low_mm"), self.num("cutoff_grid_high_mm"), self.num("cutoff_grid_step_mm"))
