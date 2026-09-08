import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class WorkOrderPhoto(Base, UUIDMixin, TimestampMixin):
    """A before/after photo uploaded by a field worker for a work order (Part 18).

    Binaries live in object storage (local disk in the demo); only metadata is
    stored here. ``category`` is BEFORE or AFTER. ``allowed`` becomes False if an
    officer/authority later rejects the photo for evidence.
    """

    __tablename__ = "work_order_photos"

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
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed: Mapped[bool] = mapped_column("allowed", default=True, nullable=False)

    work_order = relationship("WorkOrder", back_populates="photos")
    worker = relationship("FieldWorker")

    def __repr__(self) -> str:
        return f"<WorkOrderPhoto {self.category} {self.original_filename}>"
