import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class AuditLog(Base, UUIDMixin, TimestampMixin):
    """Append-only administrative audit trail (Part 27).

    Every mutating Super-Admin Panel action records an ``AuditLog`` row so an
    administrator can review who changed what, when. ``before`` / ``after`` hold
    the affected row's old and new serialized values (sensitive values such as
    API keys are REDACTED before capture — never stored in plaintext) and the
    acting user is referenced by ``actor_id`` (``SET NULL`` so a deleted user's
    audit history is preserved without a dangling FK).
    """

    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Canonical action verb, e.g. "user.create", "role.update", "config.set".
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Entity kind being changed: "user", "ward", "role", "system_config", ...
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Stable identifier of the affected record (id / key).
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    actor = relationship("User")

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.entity_type} {self.entity_id or ''}>"
