"""Evidence Check model — validates AI claims against actual data (Part 28).

When an AI makes a factual claim (distance to facility, category match,
department assignment), the system cross-checks against GIS/tool/database
evidence and records matches/mismatches.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class EvidenceCheck(Base, UUIDMixin, TimestampMixin):
    """Cross-check of an AI claim against ground-truth data."""

    __tablename__ = "evidence_checks"
    __table_args__ = (
        Index("ix_evidence_checks_complaint_id", "complaint_id"),
        Index("ix_evidence_checks_decision_id", "decision_id"),
    )

    complaint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("complaints.id", ondelete="SET NULL"), nullable=True
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_decision_logs.id", ondelete="SET NULL"), nullable=True
    )
    claim_type: Mapped[str] = mapped_column(String(64), nullable=False)
    claimed_value: Mapped[str] = mapped_column(Text, nullable=False)
    actual_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    is_match: Mapped[bool] = mapped_column(Boolean, nullable=False)
    discrepancy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    complaint = relationship("Complaint", lazy="select")
    decision = relationship("AIDecisionLog", lazy="select")
