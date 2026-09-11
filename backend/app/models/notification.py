import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin


class Notification(Base, UUIDMixin):
    """An in-app notification (Part 17 + Part 21).

    Created whenever a notable event happens so its recipients can be nudged:
    new conversation messages, complaint lifecycle steps, work-order actions,
    SLA warnings and escalation alerts. ``notification_type`` is the canonical
    event key (see :mod:`app.core.notification_types`); ``actor_id`` is the user
    who triggered the event. ``channel`` records the delivery channel
    (``"inbox"`` — stored + realtime, or ``"email"`` — also emailed when an
    email provider is configured). ``link`` is the deep link the UI navigates to
    when a notification is opened.
    """

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notification_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    complaint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    body: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(180), nullable=True)
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel: Mapped[str] = mapped_column(
        String(16), default="inbox", nullable=False, server_default="inbox"
    )
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false", index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "is_read"),)

    user = relationship("User", foreign_keys=[user_id], back_populates="notifications")
    actor = relationship("User", foreign_keys=[actor_id])
    message = relationship("Message", foreign_keys=[message_id])
    complaint = relationship("Complaint", foreign_keys=[complaint_id])
    work_order = relationship("WorkOrder", foreign_keys=[work_order_id])

    def __repr__(self) -> str:
        return (
            f"<Notification {self.id} user={self.user_id} type={self.notification_type} "
            f"read={self.is_read}>"
        )
