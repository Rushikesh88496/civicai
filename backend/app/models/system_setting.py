import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class SystemSetting(Base, UUIDMixin, TimestampMixin):
    """Runtime-managed system configuration (Part 27).

    Holds *overrides* on top of the environment-based ``Settings`` defaults:
    production configuration stays in the environment, and the Super-Admin Panel
    manages an optional override layer here. Secret settings (API keys) NEVER
    store the plaintext — ``value`` holds a Fernet-encrypted token (see
    ``app/core/vault.py``) and API responses only ever surface a ``configured``
    boolean plus a masked tail (e.g. ``••••1234``).
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    # Grouping shown in the admin UI: "AI", "Vision", "Integrations", "Email".
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # How the value is parsed/applied: "secret" | "text" | "int" | "float" | "bool".
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # For secrets this holds the Fernet token of the override; for non-secrets
    # the raw override. NULL means "no override — use the environment default".
    value: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    is_secret: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    is_editable: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    updated_by_user = relationship("User")

    def __repr__(self) -> str:
        secret = " (secret)" if self.is_secret else ""
        return f"<SystemSetting {self.key}{secret} set={self.value is not None}>"
