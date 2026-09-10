"""ML readiness gating (Part 31).

Predictive surfaces (hotspots, infrastructure maintenance) only operate once the
platform holds enough REAL operational data. This module defines the gating
states and a small helper to report how close the system is to "ready".

The intent is explicit: an empty CivicAgent deployment reports
``INSUFFICIENT_DATA`` (never fake markers / forecasts) until officers have been
feeding real complaint history past the configured minimum thresholds.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class PredictionStatus(enum.StrEnum):
    """Shared gating state for every ML prediction surface."""

    # Not enough real data to train or serve a meaningful model.
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    # Enough data; the surface is operating (model trained + served).
    READY = "READY"
    # A training run is in progress.
    TRAINING = "TRAINING"
    # A training run failed and the previous model (if any) is unaffected.
    FAILED = "FAILED"


@dataclass(frozen=True)
class Readiness:
    """How much real history exists versus the configured minimums."""

    records: int = 0
    area_time_observations: int = 0
    minimum_records: int = 25
    minimum_observations: int = 15

    @property
    def ready(self) -> bool:
        return (
            self.records >= self.minimum_records
            and self.area_time_observations >= self.minimum_observations
        )

    @property
    def status(self) -> PredictionStatus:
        return PredictionStatus.READY if self.ready else PredictionStatus.INSUFFICIENT_DATA

    def message(self, surface: str = "the predictive model") -> str:
        if self.ready:
            return (
                f"Enough real data: {self.records} records across "
                f"{self.area_time_observations} area/time observations."
            )
        return (
            f"{surface} is not ready yet: {self.records}/{self.minimum_records} minimum "
            f"complaint records and {self.area_time_observations}/{self.minimum_observations} "
            "area/time observations are required. Forecasts are disabled until real "
            "complaint history accumulates."
        )
