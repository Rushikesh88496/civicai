import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin
from app.models.enums import CorrelationMatchStatus


class ComplaintCorrelation(Base, UUIDMixin):
    """A candidate duplicate link between two complaints (Part 9).

    The correlation agent writes one row per candidate it finds (the new complaint
    vs. an existing one) with the measured semantic similarity, geospatial distance,
    time difference, category match and a combined score. Officers later flip
    ``status`` between PENDING → CONFIRMED / REJECTED.
    """

    __tablename__ = "complaint_correlations"

    # The complaint being correlated (the "source" = the newer one).
    source_complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The existing complaint the source may be a duplicate of.
    target_complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 0..1 semantic cosine similarity.
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    # Geodesic distance (metres); null when either location is unknown.
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Absolute time difference (hours).
    time_diff_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Weighted combined score (0..1).
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CorrelationMatchStatus] = mapped_column(
        Enum(CorrelationMatchStatus, name="correlation_match_status"),
        default=CorrelationMatchStatus.PENDING,
        nullable=False,
        index=True,
    )
    # Who made the officer decision (null while PENDING).
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_complaint = relationship(
        "Complaint", foreign_keys=[source_complaint_id], back_populates="source_correlations"
    )
    target_complaint = relationship(
        "Complaint", foreign_keys=[target_complaint_id], back_populates="target_correlations"
    )

    def __repr__(self) -> str:
        return (
            f"<ComplaintCorrelation {self.id} {self.source_complaint_id}~"
            f"{self.target_complaint_id} {self.status.value} score={self.score:.2f}>"
        )
