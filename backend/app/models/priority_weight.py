import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class PriorityWeight(Base, UUIDMixin, TimestampMixin):
    """Runtime-editable Priority Engine factor weights (Part 27).

    Mirrors the ``Weights`` dataclass in ``app/services/priority_engine.py``
    (severity / weather / location / crowd / history / time). An ACTIVE weight
    row overrides the engine's built-in default for that factor; the panel lets
    a super admin tune these without redeploying.
    """

    __tablename__ = "priority_weights"

    # One of the Priority Engine factor keys: severity, weather, location, crowd,
    # history, time.
    key: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<PriorityWeight {self.key}={self.weight} active={self.is_active}>"
