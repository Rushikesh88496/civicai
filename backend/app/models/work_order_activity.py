import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin


class WorkOrderActivity(Base, UUIDMixin):
    """Append-only field worker activity log (Part 18).

    Records every workflow step the field worker performs: accept, navigate
    (check-in with GPS), arrive, start, before/after photos, notes, and
    complete. Each row optionally carries latitude/longitude for GPS capture
    and a geo_denied flag when the device location was unavailable.
    """

    __tablename__ = "work_order_activities"

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_workers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_denied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Browser/device GPS horizontal accuracy in metres at capture time (Part 18
    # check-in with GPS). Optional — geo-denied / older clients record None.
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_order_photos.id", ondelete="SET NULL"),
        nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Client-generated reference used by the offline queue to make each action
    # idempotent: re-synching a queued action replays the SAME client_ref so the
    # server can recognize and skip it instead of duplicating the activity row.
    client_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    work_order = relationship("WorkOrder", back_populates="activities")
    worker = relationship("FieldWorker")

    def __repr__(self) -> str:
        return f"<WorkOrderActivity {self.activity_type} wo={self.work_order_id}>"
