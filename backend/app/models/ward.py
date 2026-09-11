from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class Ward(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "wards"

    name: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # A disabled ward keeps its history but is no longer selectable for new
    # complaints / users.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    representatives = relationship("WardRepresentative", back_populates="ward", uselist=True)
    residents = relationship("User", back_populates="ward", uselist=True)
    complaints = relationship("Complaint", back_populates="ward", uselist=True)
    infrastructure_assets = relationship(
        "InfrastructureAsset", back_populates="ward", uselist=True
    )
    boundary = relationship(
        "WardBoundary", back_populates="ward", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Ward {self.code}>"
