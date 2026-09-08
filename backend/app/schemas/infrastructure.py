"""Predictive Infrastructure Maintenance schemas (Part 24).

The officer-facing "AI Prediction" surface exposes per-asset predicted risk:

* ``InfrastructurePredictions`` - per-asset ``failure_probability``, risk level
  (LOW/MEDIUM/HIGH/CRITICAL), recommended-inspection text, supporting factors
  and the observed history the prediction was based on. Every payload ships an
  ``ai_prediction`` flag + disclaimer; phrasing stays "predicted risk" /
  "recommended inspection" - never a claim that an asset will fail.
* ``InfrastructureTrainingOut`` - result of a retrain (version, metrics, config).
* ``InfrastructureStatus`` - the active infra model (or "not trained yet").
* ``InfrastructureAssetOut`` / ``InfrastructureAssetIn`` - asset registry IO.
* ``InfrastructureReviewIn`` - officer decision on a stored prediction.
* ``PreventiveWorkOrderIn`` / ``PreventiveWorkOrderOut`` - optional proactive
  maintenance order raised against an *approved* prediction.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class InfrastructureModelInfo(BaseModel):
    version: int
    kind: str = "predictive-infrastructure-v1"
    status: str = "ready"
    is_active: bool = True
    trained_at: datetime
    artifact_filename: str
    metrics: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)


class InfrastructureAssetOut(BaseModel):
    id: str
    name: str
    category: str
    ward_id: str | None = None
    ward_code: str | None = None
    ward_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None
    installed_at: date | None = None
    condition_note: str | None = None
    is_active: bool = True
    created_at: datetime


class InfrastructureAssetIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    category: str
    ward_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None
    installed_at: date | None = None
    condition_note: str | None = None


class AssetPrediction(BaseModel):
    id: str
    asset: InfrastructureAssetOut
    model_version: int
    # Predicted risk, never a statement the asset WILL fail.
    failure_probability: float = Field(ge=0.0, le=1.0)
    risk_level: str
    recommended_inspection: str
    supporting_factors: list[str] = Field(default_factory=list)
    history: dict = Field(default_factory=dict)
    ai_prediction: bool = True
    review_status: str = "PENDING"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    predicted_at: datetime


class InfrastructurePredictions(BaseModel):
    ai_prediction: bool = Field(True, description="Always true: this is a forecast, not data")
    disclaimer: str
    inference_at: datetime
    model: InfrastructureModelInfo
    assets: list[AssetPrediction] = Field(default_factory=list)
    assets_assessed: int = 0
    assets_skipped: int = 0
    horizon_days: int = 30


class InfrastructureTrainingOut(BaseModel):
    trained: bool = True
    version: int
    model: InfrastructureModelInfo
    metrics: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    rows: int = 0
    duration_seconds: float = 0.0


class InfrastructureStatus(BaseModel):
    trained: bool = False
    model: InfrastructureModelInfo | None = None
    message: str = ""


class InfrastructureReviewIn(BaseModel):
    decision: str  # APPROVED | REJECTED
    note: str | None = None


class InfrastructureReviewOut(BaseModel):
    id: str
    review_status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None


class PreventiveWorkOrderIn(BaseModel):
    department: str
    recommended_action: str | None = None
    due_at: datetime | None = None
    note: str | None = None


class PreventiveWorkOrderOut(BaseModel):
    id: str
    prediction_id: str
    asset: InfrastructureAssetOut
    department: str
    recommended_action: str
    status: str
    due_at: datetime | None = None
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    note: str | None = None
    created_at: datetime
