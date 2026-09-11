"""AI governance service (Part 28).

Persists every AI/agent decision (model, prompt version, confidence, tool
calls, result) so decisions are auditable and can be cross-checked by the
evidence-validation layer.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIDecisionLog

# Stable, tracked prompt versions for each agent (Part 28 AI governance).
PROMPT_VERSION_TRIAGE = "triage.v1"
PROMPT_VERSION_PRIORITY = "priority.v1"
PROMPT_VERSION_DISPATCH = "dispatch.v1"
PROMPT_VERSION_VISION = "vision.v1"
PROMPT_VERSION_ROUTING = "routing.v1"


async def log_ai_decision(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None,
    agent_name: str,
    model_name: str,
    input_summary: str | None = None,
    output_summary: str | None = None,
    confidence: float | None = None,
    tool_calls: list[dict] | dict | None = None,
    result: dict | None = None,
    decision_id: uuid.UUID | None = None,
    prompt_version: str | None = None,
    duration_ms: int | None = None,
) -> AIDecisionLog:
    """Record an AI decision. Does NOT commit — caller commits with its tx."""
    decision = AIDecisionLog(
        complaint_id=complaint_id,
        agent_name=agent_name,
        model_name=model_name,
        prompt_version=prompt_version,
        input_summary=input_summary,
        output_summary=output_summary,
        confidence=confidence,
        tool_calls=tool_calls,
        result=result,
        duration_ms=duration_ms,
    )
    db.add(decision)
    await db.flush()
    return decision


async def list_ai_decisions(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None = None,
    agent_name: str | None = None,
    limit: int = 100,
) -> list[AIDecisionLog]:
    """Return the most recent AI decisions, optionally filtered."""
    stmt = select(AIDecisionLog).order_by(AIDecisionLog.created_at.desc()).limit(limit)
    if complaint_id is not None:
        stmt = stmt.where(AIDecisionLog.complaint_id == complaint_id)
    if agent_name is not None:
        stmt = stmt.where(AIDecisionLog.agent_name == agent_name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_ai_decision(db: AsyncSession, decision_id: uuid.UUID) -> AIDecisionLog | None:
    return await db.get(AIDecisionLog, decision_id)


class TimingContext:
    """Helper to measure an agent/LLM call duration."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    @property
    def duration_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)


def _serialize_claim_value(value: Any) -> str:
    """Best-effort string serialization for evidence claim values."""
    if value is None:
        return ""
    if isinstance(value, dict):
        try:
            import json

            return json.dumps(value, default=str)
        except Exception:
            return str(value)
    return str(value)
