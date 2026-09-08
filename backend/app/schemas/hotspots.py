"""Predictive Hotspots schemas (Part 23).

The officer-facing "AI Prediction" surface exposes:

* ``HotspotPredictions`` — per-grid-cell risk score (probability of >=1 new
  complaint in the next horizon), expected volume, tier + provenance info. Every
  payload is explicitly labelled ``ai_prediction`` and ships a disclaimer so the
  UI can never present a forecast as a confirmed incident.
* ``HotspotTrainingOut`` — result of a retrain (version, metrics, config).
* ``HotspotStatus`` — the active model (or "not trained yet").
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HotspotModelInfo(BaseModel):
    version: int
    kind: str = "predictive-hotspots-v1"
    status: str = "ready"
    is_active: bool = True
    trained_at: datetime
    artifact_filename: str
    metrics: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)


class RiskCell(BaseModel):
    cell_id: str
    latitude: float
    longitude: float
    # P(>=1 new complaint in the next horizon) from the XGBoost classifier.
    risk_score: float = 0.0
    # Expected complaint volume (count) in the same window from the regressor.
    expected_volume: float = 0.0
    # high (>=0.5) / medium (>=0.25) / low.
    tier: str = "low"
    ward_code: str | None = None
    ward_name: str | None = None
    # Observed complaints in the trailing 7 days (context, not prediction).
    trailing7: int = 0


class HotspotPredictions(BaseModel):
    ai_prediction: bool = Field(True, description="Always true: this is a forecast, not data")
    disclaimer: str
    horizon_days: int = 7
    inference_at: datetime
    model: HotspotModelInfo
    cells: list[RiskCell] = Field(default_factory=list)
    population_cells: int = 0
    complaint_events_used: int = 0
    complaints_outside_grid: int = 0


class HotspotTrainingOut(BaseModel):
    trained: bool = True
    version: int
    model: HotspotModelInfo
    metrics: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    rows: int = 0
    duration_seconds: float = 0.0


class HotspotStatus(BaseModel):
    trained: bool = False
    model: HotspotModelInfo | None = None
    message: str = ""
