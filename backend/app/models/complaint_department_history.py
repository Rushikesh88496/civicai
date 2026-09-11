import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin


class ComplaintDepartmentHistory(Base, UUIDMixin):
    """Append-only record of a complaint's department routing decision (Part 13).

    The Routing Agent recomputes a department assignment as the upstream
    triage / vision / priority / context signals change. Each computation appends
    one row here so the UI can show the recommended department, its reason, the
    deterministic confidence, and any multi-department secondary assignments.

    ``inputs`` stores the exact category + upstream signals that produced the
    decision so history is fully reconstructable.
    """

    __tablename__ = "complaint_department_history"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The recommended primary department (one of the seven DepartmentCode values).
    primary_department: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Optional multi-department secondaries (list of DepartmentCode strings).
    secondary_departments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Human-readable why-these-departments explanation.
    routing_reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Deterministic 0..1 confidence in the decision.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # True when the category was unrecognized / routing was ambiguous.
    ambiguous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The exact category + upstream signals that produced the decision.
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Set at insert / recomputation time; history is append-only.
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint", back_populates="department_history")

    def __repr__(self) -> str:
        return (
            f"<ComplaintDepartmentHistory {self.complaint_id} "
            f"primary={self.primary_department} conf={self.confidence:.2f}>"
        )
