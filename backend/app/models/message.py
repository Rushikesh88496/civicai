import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin


class Message(Base, UUIDMixin):
    """A single message in a complaint conversation (Part 17).

    Evolves the Part 16 thread into a first-class conversation: each message
    belongs to a ``conversation`` (1 per complaint) and is authored either by the
    citizen who opened the complaint or by an authorized staff member
    (WARD_REPRESENTATIVE / OFFICER / ADMIN) whose ward / role grants them access.
    ``complaint_id`` is kept denormalized for legacy endpoints and fast scoped
    queries. ``role`` snapshots the author's role at send time so the thread
    renders without extra joins; visibility is enforced on read by comparing the
    requesting user against the complaint's owner and ward.
    """

    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The user who authored this message.
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Snapshot of the author's role at send time (CITIZEN / WARD_REPRESENTATIVE /
    # OFFICER / ADMIN) so the thread renders correctly without extra lookups.
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation = relationship("Conversation", back_populates="messages")
    complaint = relationship("Complaint", back_populates="messages")
    author = relationship("User", foreign_keys=[author_id])
    attachments = relationship(
        "MessageAttachment",
        back_populates="message",
        uselist=True,
        cascade="all, delete-orphan",
    )
    reads = relationship(
        "MessageRead",
        back_populates="message",
        uselist=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Message {self.id} conversation={self.conversation_id} "
            f"complaint={self.complaint_id} role={self.role}>"
        )
