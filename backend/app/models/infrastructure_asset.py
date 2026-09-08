import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import (
    InfrastructureCategory,
    InfrastructureRiskLevel,
    PredictionReviewStatus,
)


class InfrastructureAsset(Base, UUIDMixin, TimestampMixin):
    """A municipal infrastructure asset tracked for predictive maintenance.

    Roads, bridges, water mains, sewer/drainage lines, street lighting, parks
    and public buildings are registered with their category, ward, coordinates
    and installation (age) so the Part 24 risk pipeline can blend history
    (complaints + repairs) with infrastructure age, weather and location.
    """

    __tablename__ = "infrastructure_assets"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[InfrastructureCategory] = mapped_column(
        Enum(InfrastructureCategory, name="infrastructure_category"),
        nullable=False,
        index=True,
    )
    ward_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    installed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Thin, human-readable operational context (not a prediction).
    condition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    ward = relationship("Ward", back_populates="infrastructure_assets")
    predictions = relationship(
        "InfrastructurePrediction",
        back_populates="asset",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="InfrastructurePrediction.created_at",
    )
    preventive_orders = relationship(
        "PreventiveWorkOrder",
        back_populates="asset",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="PreventiveWorkOrder.created_at",
    )

    def __repr__(self) -> str:
        return f"<InfrastructureAsset {self.name} ({self.category.value})>"


class InfrastructurePrediction(Base, UUIDMixin, TimestampMixin):
    """A stored predicted-maintenance-risk output for one asset (Part 24).

    Persisted so an authorized officer can review the model's recommendation
    (``PredictionReviewStatus``) and optionally create a preventive work order.
    ``supporting_factors`` are short, human-readable explanations; the phrasing
    is always "predicted risk" / "recommended inspection" — never a claim that
    the asset will fail.
    """

    __tablename__ = "infrastructure_predictions"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("infrastructure_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Model version that produced the probability (from the infra registry).
    model_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # P(failure) in the configured horizon from the trained classifier (0..1).
    failure_probability: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[InfrastructureRiskLevel] = mapped_column(
        Enum(InfrastructureRiskLevel, name="infrastructure_risk_level"),
        nullable=False,
        index=True,
    )
    recommended_inspection: Mapped[str] = mapped_column(Text, nullable=False)
    # Human-readable explanatory factors (JSON list of strings).
    supporting_factors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Snapshot of the input history the prediction was based on (JSON).
    history: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Forecast-provenance guard: this is always an AI prediction, never data.
    ai_prediction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_status: Mapped[PredictionReviewStatus] = mapped_column(
        Enum(PredictionReviewStatus, name="prediction_review_status"),
        default=PredictionReviewStatus.PENDING,
        nullable=False,
        index=True,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    asset = relationship("InfrastructureAsset", back_populates="predictions")
    reviewed_by_user = relationship("User", foreign_keys=[reviewed_by])
    preventive_order = relationship(
        "PreventiveWorkOrder",
        back_populates="prediction",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<InfrastructurePrediction {self.risk_level.value} "
            f"{self.failure_probability:.2f} {self.review_status.value}>"
        )
