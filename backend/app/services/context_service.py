"""Service facade for the Context Enrichment Agent (Part 11).

Wraps ``ContextAgent`` with complaint access enforcement (only an authenticated
user who may view the source complaint can trigger or read its context
enrichment), persists the structured ``ContextOutput`` to ``agent_runs``, and
returns the latest run for a complaint.

All access decisions receive the authenticated ``User`` from the dependency —
never a client-supplied ID.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context_agent import AGENT_NAME, ContextAgent
from app.core.config import get_settings
from app.models import AgentRun, User
from app.schemas.context import ContextOutput, ContextRunOut, ContextRunResponse
from app.services import agent_run_service
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
    _load_complaint,
    user_can_view,
)


class ContextNotFoundError(ComplaintNotFoundError):
    """Raised when a complaint does not exist (mirrors tracking semantics)."""


class ContextAccessError(ComplaintAccessError):
    """Raised when the authenticated user cannot access a complaint."""


async def _assert_can_view(db: AsyncSession, user: User, complaint_id: uuid.UUID) -> None:
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise ContextNotFoundError
    if not user_can_view(user, complaint):
        raise ContextAccessError


def _agent() -> ContextAgent:
    return ContextAgent(settings=get_settings())


async def run_context(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
) -> ContextRunResponse:
    """Run the context enrichment graph for a complaint and return the run state."""
    await _assert_can_view(db, user, complaint_id)
    run: AgentRun = await _agent().run(db, complaint_id=complaint_id)
    await db.refresh(run)
    result = (
        ContextOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return ContextRunResponse(
        run_id=run.id,
        status=run.status,
        result=result,
        error=run.error,
        retry_allowed=True,
    )


async def get_context_result(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> ContextRunOut | None:
    """Return the most recent context enrichment run for a complaint, if any."""
    await _assert_can_view(db, user, complaint_id)
    run = await agent_run_service.get_latest_run(db, complaint_id)
    if run is None or run.agent != AGENT_NAME:
        return None
    result = (
        ContextOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return ContextRunOut(
        id=run.id,
        complaint_id=run.complaint_id,
        agent=run.agent,
        model=run.model,
        status=run.status,
        duration_ms=run.duration_ms,
        structured_result=result,
        error=run.error,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )
