import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin
from app.models.enums import ComplaintStatus


class ComplaintStatusHistory(Base, UUIDMixin):
    """Immutable record of a complaint status transition (Part 5).

    One row is appended on every status change so the full lifecycle can be
    reconstructed and shown in the complaint timeline UI. Rows are append-only:
    ``recorded_at`` captures when the transition happened and ``actor_id`` /
    ``note`` document who/what caused it.
    """

    __tablename__ = "complaint_status_history"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The status this entry moved the complaint INTO (the resulting status).
    status: Mapped[ComplaintStatus] = mapped_column(
        Enum(ComplaintStatus, name="complaint_status"),
        nullable=False,
        index=True,
    )
    # Which user triggered the change (e.g. a citizen verifying, a worker marking
    # a complaint RESOLVED, or a system/AI automated transition).
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set at insert time; deliberately has no onupdate (history is immutable).
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint", back_populates="status_history")

    def __repr__(self) -> str:
        return f"<ComplaintStatusHistory {self.id} -> {self.status.value}>"
