import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin
from app.models.enums import AssignmentStatus


class WorkerAssignment(Base, UUIDMixin):
    """A worker ↔ work-order assignment (Part 14).

    Only one assignment is *active* (``status=ASSIGNED``) per work order at a
    time; reassignment marks the previous holder ``UNASSIGNED``/``REASSIGNED`` and
    records why. Used to (a) enforce that selection is never random and always
    explainable, and (b) compute each worker's current workload.
    """

    __tablename__ = "worker_assignments"

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
    status: Mapped[AssignmentStatus] = mapped_column(
        "status", String(24), default=AssignmentStatus.ASSIGNED, nullable=False
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    # How this assignment was created (Part 32): "AI_RECOMMENDATION" when the
    # officer accepted the dispatch agent's pick, "OFFICER_OVERRIDE" when they
    # chose a different worker, "MANUAL" when no AI recommendation existed.
    # Together with ``ai_decision_logs`` this makes the official assignment
    # never be confused with — or masquerade as — the AI recommendation.
    origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Selection rationale (skill/distance/workload/equipment scoring) — never random.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # When the assigned worker accepted the job (Part 18 field workflow).
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    work_order = relationship("WorkOrder", back_populates="assignments")
    worker = relationship("FieldWorker", back_populates="assignments", lazy="selectin")
    assigned_by_user = relationship("User", foreign_keys=[assigned_by])

    def __repr__(self) -> str:
        return f"<WorkerAssignment {self.worker_id} {self.status.value}>"
