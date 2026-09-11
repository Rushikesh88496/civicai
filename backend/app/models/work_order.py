import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import WorkOrderStatus


class WorkOrder(Base, UUIDMixin, TimestampMixin):
    """A field-work order created for a complaint (Part 14).

    The Dispatch Agent produces a *draft* work order (``PENDING_APPROVAL``) with a
    recommended worker and an ETA; an authorized officer then approves / assigns /
    reassigns / escalates / rejects / closes it. ``department`` is one of the seven
    routing ``DepartmentCode`` values; ``priority`` mirrors the complaint's dynamic
    priority bucket (P1..P4). ``eta_minutes`` + ``eta_source`` come from the routing
    abstraction and are never falsely labelled "live" when only estimated.
    """

    __tablename__ = "work_orders"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Short human-readable label of the underlying incident (from the complaint).
    incident: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # One of the seven DepartmentCode routing targets.
    department: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Dynamic priority bucket (P1..P4) copied from the complaint's priority run.
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # Denormalized complaint location so the order is portable + sortable by distance.
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # SLA in hours from dispatch (drive towards the priority bucket deadline).
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Recommended action from the dispatch agent.
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[WorkOrderStatus] = mapped_column(
        "status",
        String(40),
        default=WorkOrderStatus.PENDING_APPROVAL,
        nullable=False,
        index=True,
    )
    # ETA + provenance from the routing abstraction (source = "live" | "estimated").
    eta_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eta_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Currently assigned worker (nullable until approved/assigned).
    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_workers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The worker the Dispatch Agent recommended (frozen at draft time). Kept so
    # an officer's accept-vs-override can always be reconstructed precisely,
    # even after the live ``worker_id`` is later changed by a reassignment.
    recommended_worker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_workers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Creator + approver (authorized staff). Approver set on approve.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optional officer escalation / rejection note (kept for context).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Field worker workflow timestamps (Part 18).
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the worker submitted the resolution evidence (Part 28). Distinct from
    # ``completed_at`` (when the physical work finished) — the order is only
    # treated as resolved once the verification stage confirms the repair.
    evidence_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Why an officer returned the order for rework (``RETURNED_FOR_REWORK``).
    # Kept through the rework cycle so the worker always sees the required fixes.
    rework_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    complaint = relationship("Complaint", back_populates="work_orders")
    worker = relationship("FieldWorker", back_populates="work_orders", foreign_keys=[worker_id])
    recommended_worker = relationship(
        "FieldWorker", foreign_keys=[recommended_worker_id], lazy="selectin"
    )
    created_by_user = relationship("User", foreign_keys=[created_by])
    approved_by_user = relationship("User", foreign_keys=[approved_by])
    assignments = relationship(
        "WorkerAssignment",
        back_populates="work_order",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="WorkerAssignment.assigned_at",
    )
    status_history = relationship(
        "WorkOrderStatusHistory",
        back_populates="work_order",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="WorkOrderStatusHistory.recorded_at",
    )
    activities = relationship(
        "WorkOrderActivity",
        back_populates="work_order",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="WorkOrderActivity.recorded_at",
    )
    photos = relationship(
        "WorkOrderPhoto",
        back_populates="work_order",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="WorkOrderPhoto.created_at",
    )
    verifications = relationship(
        "WorkOrderVerification",
        back_populates="work_order",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="WorkOrderVerification.created_at",
    )

    def __repr__(self) -> str:
        return f"<WorkOrder {self.id} {self.department} {self.status.value}>"
