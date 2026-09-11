import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import (
    ComplaintCategory,
    ComplaintPriority,
    ComplaintStatus,
    CorrelationStatus,
)


class Complaint(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "complaints"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ward_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    category: Mapped[ComplaintCategory] = mapped_column(
        Enum(ComplaintCategory, name="complaint_category"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[ComplaintPriority] = mapped_column(
        Enum(ComplaintPriority, name="complaint_priority"),
        default=ComplaintPriority.MEDIUM,
        nullable=False,
        index=True,
    )
    status: Mapped[ComplaintStatus] = mapped_column(
        Enum(ComplaintStatus, name="complaint_status"),
        default=ComplaintStatus.OPEN,
        nullable=False,
        index=True,
    )
    # Duplicate / incident correlation outcome (Part 9). Nullable so pre-existing
    # rows are treated as NEW_INCIDENT until the correlation agent runs.
    correlation_status: Mapped[CorrelationStatus | None] = mapped_column(
        Enum(CorrelationStatus, name="correlation_status"),
        default=CorrelationStatus.NEW_INCIDENT,
        nullable=True,
        index=True,
    )
    # ISO 639-1 language code detected at complaint submission (Part 26).
    # Null on legacy rows (treated as English by the pipeline).
    language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        index=True,
    )

    user = relationship("User", back_populates="complaints")
    ward = relationship("Ward", back_populates="complaints")
    media = relationship(
        "ComplaintMedia", back_populates="complaint", uselist=True, cascade="all, delete-orphan"
    )
    complaint_location = relationship(
        "ComplaintLocation",
        back_populates="complaint",
        uselist=False,
        cascade="all, delete-orphan",
    )
    status_history = relationship(
        "ComplaintStatusHistory",
        back_populates="complaint",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="ComplaintStatusHistory.recorded_at",
    )
    priority_history = relationship(
        "ComplaintPriorityHistory",
        back_populates="complaint",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="ComplaintPriorityHistory.calculated_at",
    )
    department_history = relationship(
        "ComplaintDepartmentHistory",
        back_populates="complaint",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="ComplaintDepartmentHistory.calculated_at",
    )
    department_overrides = relationship(
        "DepartmentOverride",
        back_populates="complaint",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="DepartmentOverride.overridden_at",
    )
    agent_runs = relationship(
        "AgentRun",
        back_populates="complaint",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="AgentRun.started_at",
    )
    embedding = relationship(
        "ComplaintEmbedding",
        back_populates="complaint",
        uselist=False,
        cascade="all, delete-orphan",
    )
    work_orders = relationship(
        "WorkOrder",
        back_populates="complaint",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="WorkOrder.created_at",
    )
    conversation = relationship(
        "Conversation",
        back_populates="complaint",
        uselist=False,
        cascade="all, delete-orphan",
    )
    messages = relationship(
        "Message",
        back_populates="complaint",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    source_correlations = relationship(
        "ComplaintCorrelation",
        back_populates="source_complaint",
        foreign_keys="ComplaintCorrelation.source_complaint_id",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="ComplaintCorrelation.created_at",
    )
    target_correlations = relationship(
        "ComplaintCorrelation",
        back_populates="target_complaint",
        foreign_keys="ComplaintCorrelation.target_complaint_id",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="ComplaintCorrelation.created_at",
    )

    def __repr__(self) -> str:
        return f"<Complaint {self.id} ({self.status.value})>"
