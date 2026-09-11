"""Predictive Hotspots schemas (Part 23 + Part 31 gating).

The officer-facing "AI Prediction" surface exposes:

* ``HotspotPredictions`` — per-grid-cell risk score (probability of >=1 new
  complaint in the next horizon), expected volume, tier + provenance info. Every
  payload is explicitly labelled ``ai_prediction`` and ships a disclaimer so the
  UI can never present a forecast as a confirmed incident.
* ``HotspotTrainingOut`` — result of a retrain (version, metrics, config).
* ``HotspotStatus`` — the active model (or "not trained yet").

Part 31: predictions/training are *gated* on real minimum data (see
``app.ml.readiness``). When the platform holds too little complaint history the
surfaces report ``prediction_status=INSUFFICIENT_DATA`` with zero cells and a
human readable ``message`` — they never emit synthetic forecasts.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.ml.readiness import PredictionStatus


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
    # READY | INSUFFICIENT_DATA | TRAINING | FAILED (Part 31 gating).
    prediction_status: PredictionStatus = PredictionStatus.INSUFFICIENT_DATA
    horizon_days: int = 7
    inference_at: datetime | None = None
    model: HotspotModelInfo | None = None
    cells: list[RiskCell] = Field(default_factory=list)
    population_cells: int = 0
    complaint_events_used: int = 0
    complaints_outside_grid: int = 0
    # Data-readiness context (0 when gated off because data is missing).
    message: str = ""
    records_available: int = 0
    observations_available: int = 0
    minimum_records: int = 25
    minimum_observations: int = 15


class HotspotTrainingOut(BaseModel):
    trained: bool = False
    # READY when training produced a model; INSUFFICIENT_DATA when the gate
    # refused to train; FAILED when a run failed.
    status: PredictionStatus = PredictionStatus.INSUFFICIENT_DATA
    version: int | None = None
    model: HotspotModelInfo | None = None
    metrics: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    rows: int = 0
    duration_seconds: float = 0.0
    message: str = ""
    records_available: int = 0
    observations_available: int = 0
    minimum_records: int = 25
    minimum_observations: int = 15


class HotspotStatus(BaseModel):
    trained: bool = False
    prediction_status: PredictionStatus = PredictionStatus.INSUFFICIENT_DATA
    model: HotspotModelInfo | None = None
    message: str = ""
    records_available: int = 0
    observations_available: int = 0
    minimum_records: int = 25
    minimum_observations: int = 15
