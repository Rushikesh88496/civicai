import uuid

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import RepresentativeStatus


class WardRepresentative(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "ward_representatives"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wards.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[RepresentativeStatus] = mapped_column(
        Enum(RepresentativeStatus, name="representative_status"),
        default=RepresentativeStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    user = relationship("User", back_populates="ward_representative")
    ward = relationship("Ward", back_populates="representatives")

    def __repr__(self) -> str:
        return f"<WardRepresentative user={self.user_id} status={self.status.value}>"
