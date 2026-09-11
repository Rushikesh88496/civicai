import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin
from app.models.enums import WorkOrderStatus


class WorkOrderStatusHistory(Base, UUIDMixin):
    """Append-only audit trail of a work order's lifecycle (Part 14).

    Every officer action (dispatch / approve / assign / reassign / escalate /
    reject / close) records ``action``, the ``from_status`` → ``to_status``
    transition, the acting user and an optional note so the full history of a
    work order is reconstructable.
    """

    __tablename__ = "work_order_status_history"

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[WorkOrderStatus | None] = mapped_column(
        "from_status", String(40), nullable=True
    )
    to_status: Mapped[WorkOrderStatus] = mapped_column("to_status", String(40), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    work_order = relationship("WorkOrder", back_populates="status_history")
    actor = relationship("User")

    def __repr__(self) -> str:
        return f"<WorkOrderStatusHistory {self.action} {self.to_status}>"
