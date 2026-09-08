import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import MediaType


class ComplaintMedia(Base, UUIDMixin, TimestampMixin):
    """A single media asset (image or short video) attached to a complaint.

    Binary payloads are never stored in PostgreSQL — the file lives in object
    storage (local disk or a MinIO/S3-compatible bucket) and only its key,
    size and content metadata are kept here.
    """

    __tablename__ = "complaint_media"

    complaint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_type: Mapped[MediaType] = mapped_column(
        Enum(MediaType, name="media_type"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    complaint = relationship("Complaint", back_populates="media")

    def __repr__(self) -> str:
        return f"<ComplaintMedia {self.id} ({self.media_type.value})>"
