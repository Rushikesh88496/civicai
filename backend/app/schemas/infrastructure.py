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

from app.ml.readiness import PredictionStatus


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
    # Real provenance, when the asset was synced from the verified facility
    # registry (None for manually registered assets).
    source: str | None = None
    source_dataset: str | None = None
    source_url: str | None = None
    source_id: str | None = None
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
    # READY | INSUFFICIENT_DATA | TRAINING | FAILED (Part 31 gating).
    prediction_status: PredictionStatus = PredictionStatus.INSUFFICIENT_DATA
    inference_at: datetime | None = None
    model: InfrastructureModelInfo | None = None
    assets: list[AssetPrediction] = Field(default_factory=list)
    assets_assessed: int = 0
    assets_skipped: int = 0
    horizon_days: int = 30
    message: str = ""
    registered_assets: int = 0
    minimum_assets: int = 5
    # Part 37 history gate: how many REAL, legitimately-linked complaint/repair
    # records exist vs the configured minimum (separate from the asset fleet).
    history_records: int = 0
    minimum_history: int = 0


class InfrastructureTrainingOut(BaseModel):
    trained: bool = False
    status: PredictionStatus = PredictionStatus.INSUFFICIENT_DATA
    version: int | None = None
    model: InfrastructureModelInfo | None = None
    metrics: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    rows: int = 0
    duration_seconds: float = 0.0
    message: str = ""
    registered_assets: int = 0
    minimum_assets: int = 5
    history_records: int = 0
    minimum_history: int = 0


class InfrastructureStatus(BaseModel):
    trained: bool = False
    prediction_status: PredictionStatus = PredictionStatus.INSUFFICIENT_DATA
    model: InfrastructureModelInfo | None = None
    message: str = ""
    registered_assets: int = 0
    minimum_assets: int = 5
    history_records: int = 0
    minimum_history: int = 0


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


class AssetRegistryCategoryCounts(BaseModel):
    """Per-category result of a real asset-registry sync (Part 37)."""

    category: str
    # Registered-asset category this maps to (the asset kind actually created).
    asset_category: str | None = None
    # Real verified facility-registry records available in that category.
    available: int = 0
    registered: int = 0
    updated: int = 0
    skipped_duplicate: int = 0


class AssetRegistrySyncOut(BaseModel):
    """Idempotent, provenance-keyed sync of real assets (Part 37)."""

    source: str = "openstreetmap"
    source_dataset: str | None = None
    inserted: int = 0
    updated: int = 0
    skipped_duplicate: int = 0
    unlocated: int = 0
    registered_total: int = 0
    by_category: list[AssetRegistryCategoryCounts] = Field(default_factory=list)
    message: str = ""
