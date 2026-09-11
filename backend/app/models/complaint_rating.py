import uuid

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class ComplaintRating(Base, UUIDMixin, TimestampMixin):
    """Citizen satisfaction rating left on a resolved complaint (Part 22).

    Exactly one rating per complaint (``complaint_id`` is unique): the complaint
    owner submits a 1-5 star score and optional comment after the incident is
    resolved. The analytics dashboard aggregates these into the citizen
    satisfaction KPI.
    """

    __tablename__ = "complaint_ratings"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    complaint = relationship("Complaint")

    def __repr__(self) -> str:
        return f"<ComplaintRating {self.id} {self.rating}/5>"
