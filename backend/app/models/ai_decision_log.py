"""AI Decision Log model — tracks every LLM/agent decision (Part 28).

Records model name, prompt version, confidence, tool calls, and result
for every AI-driven decision on a complaint (triage, priority, routing,
dispatch, vision analysis).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class AIDecisionLog(Base, UUIDMixin, TimestampMixin):
    """Append-only log of every AI/agent decision."""

    __tablename__ = "ai_decision_logs"
    __table_args__ = (
        Index("ix_ai_decision_logs_complaint_id", "complaint_id"),
        Index("ix_ai_decision_logs_agent_name", "agent_name"),
    )

    complaint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("complaints.id", ondelete="SET NULL"), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_override: Mapped[bool] = mapped_column(default=False)

    complaint = relationship("Complaint", lazy="select")
