"""Preventive infrastructure work orders (Part 24).

An authorized officer may create a preventive work order for an asset whose
stored prediction they *approved*. Unlike the complaint-driven ``WorkOrder``
(which requires ``complaint_id``), a preventive order is proactive maintenance
on a predicted-at-risk asset, so it is intentionally its own table.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import PreventiveWorkOrderStatus


class PreventiveWorkOrder(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "preventive_work_orders"

    prediction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("infrastructure_predictions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("infrastructure_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # One of the seven routing DepartmentCode values (owner of the asset type).
    department: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Concrete proactive action, derived from the recommended inspection.
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PreventiveWorkOrderStatus] = mapped_column(
        Enum(PreventiveWorkOrderStatus, name="preventive_work_order_status"),
        default=PreventiveWorkOrderStatus.PENDING_APPROVAL,
        nullable=False,
        index=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Creator + reviewer (authorized staff).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    prediction = relationship("InfrastructurePrediction", back_populates="preventive_order")
    asset = relationship("InfrastructureAsset", back_populates="preventive_orders")
    created_by_user = relationship("User", foreign_keys=[created_by])
    approved_by_user = relationship("User", foreign_keys=[approved_by])

    def __repr__(self) -> str:
        return f"<PreventiveWorkOrder {self.id} {self.department} {self.status.value}>"
