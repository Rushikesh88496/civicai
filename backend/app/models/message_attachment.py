import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin


class MessageAttachment(Base, UUIDMixin):
    """A file attached to a conversation message (Part 17).

    Uploads happen in two steps so ownership and scope can be checked *before* a
    message exists: the file is stored and its metadata row created with
    ``message_id = NULL`` (authorized to a complaint by ``complaint_id`` +
    ``uploader_id``), then linked to the ``Message`` on send via
    ``attachment_ids``. Pending attachments that are never linked can be garbage
    collected without touching a conversation.
    """

    __tablename__ = "message_attachments"

    # NULL until the attachment is attached to a sent message.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message = relationship("Message", back_populates="attachments")
    complaint = relationship("Complaint")
    uploader = relationship("User")

    def __repr__(self) -> str:
        state = self.message_id or "pending"
        return f"<MessageAttachment {self.id} {self.original_filename!r} {state}>"
