"""Human Override model — tracks officer overrides of AI decisions (Part 28).

When an officer overrides an AI decision (priority, department, routing,
resolution verdict), the system stores the original decision, new decision,
reason, and who made the override.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class HumanOverride(Base, UUIDMixin, TimestampMixin):
    """Record of an officer overriding an AI-generated decision."""

    __tablename__ = "human_overrides"
    __table_args__ = (
        Index("ix_human_overrides_complaint_id", "complaint_id"),
        Index("ix_human_overrides_decision_id", "decision_id"),
    )

    complaint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("complaints.id", ondelete="SET NULL"), nullable=True
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_decision_logs.id", ondelete="SET NULL"), nullable=True
    )
    override_type: Mapped[str] = mapped_column(String(64), nullable=False)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    complaint = relationship("Complaint", lazy="select")
    decision = relationship("AIDecisionLog", lazy="select")
    user = relationship("User", lazy="select")
