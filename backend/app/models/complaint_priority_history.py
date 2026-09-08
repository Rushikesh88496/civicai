import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin
from app.models.enums import DynamicPriority


class ComplaintPriorityHistory(Base, UUIDMixin):
    """Append-only record of a complaint's deterministic priority score (Part 12).

    The Priority Engine recomputes a 0..100 score whenever significant context
    changes. Each computation appends one row here so the UI can show a score
    history (score, bucket, and how it changed versus the previous computation).

    ``inputs`` stores the exact input values that produced the score and
    ``factors`` the explainable factor breakdown (factor / input value / weight /
    contribution) — both as JSON so history is fully reconstructable.
    """

    __tablename__ = "complaint_priority_history"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The computed 0..100 score.
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    # The deterministic bucket for this score.
    priority: Mapped[DynamicPriority] = mapped_column(
        Enum(DynamicPriority, name="dynamic_priority"),
        nullable=False,
        index=True,
    )
    # Score of the previous computation (None on the first run).
    previous_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # True when this score moved by >= the configured change threshold.
    changed: Mapped[bool] = mapped_column(nullable=False, default=False)
    # The exact input values that produced this score (the 7 priority inputs).
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Explainable factor breakdown (factor / input value / weight / contribution).
    factors: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # One-line summary for the timeline / UI.
    summary: Mapped[str | None] = mapped_column(nullable=True)
    # Set at insert / recomputation time; history is append-only.
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint", back_populates="priority_history")

    def __repr__(self) -> str:
        return (
            f"<ComplaintPriorityHistory {self.complaint_id} score={self.score} "
            f"{self.priority.value}>"
        )
