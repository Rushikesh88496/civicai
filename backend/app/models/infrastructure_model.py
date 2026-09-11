"""Infrastructure-maintenance model registry (Part 24).

Mirrors the Predictive Civic Hotspots registry (``predictive_models``) but is a
separate table so infra model retrains can never deactivate or renumber the
hotspot model. Stores the trained artifact metadata, evaluation metrics and the
training config; exactly one row is ``is_active`` at a time.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import UUIDMixin


class InfrastructureModel(Base, UUIDMixin):
    __tablename__ = "infrastructure_models"

    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(
        String(50), nullable=False, default="predictive-infrastructure-v1"
    )
    artifact_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Evaluation metrics (classification + baseline) as JSON.
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Snapshot of the settings / corpus config used to train this model.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    trained_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<InfrastructureModel v{self.version} active={self.is_active}>"
