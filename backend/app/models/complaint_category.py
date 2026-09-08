from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class ComplaintCategoryConfig(Base, UUIDMixin, TimestampMixin):
    """Admin-managed registry of complaint categories (Part 27).

    Seeded from the ``ComplaintCategory`` enum values so the panel can label,
    reorder and deactivate categories without touching code. Active categories
    drive the category pickers across the app; a deactivated category is hidden
    from those pickers (existing complaints keep their category).
    """

    __tablename__ = "complaint_categories"

    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<ComplaintCategory {self.code} active={self.is_active}>"
