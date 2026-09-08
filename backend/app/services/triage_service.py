"""Service facade for the AI Triage Agent (Part 7).

Wraps ``TriageAgent`` with complaint access enforcement (only an authenticated
user who may view the complaint can trigger or read its analysis), and returns
serializable run data so the route stays thin and free of direct DB plumbing.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.triage_agent import AGENT_NAME, TriageAgent
from app.core.config import get_settings
from app.core.notification_types import EVENT_AI_COMPLETE
from app.models import AgentRun, Complaint, User
from app.schemas.triage import AgentRunOut, TriageInput, TriageOutput, TriageRunResponse
from app.services import agent_run_service, language_service, notification_service
from app.services.ai_service import get_ai_service
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
    _load_complaint,
    user_can_view,
)


class TriageNotFoundError(ComplaintNotFoundError):
    """Raised when a complaint does not exist (mirrors tracking semantics)."""


class TriageAccessError(ComplaintAccessError):
    """Raised when the authenticated user cannot access a complaint."""


async def _assert_can_view(db: AsyncSession, user: User, complaint_id: uuid.UUID) -> None:
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise TriageNotFoundError
    if not user_can_view(user, complaint):
        raise TriageAccessError


async def _notify_analysis_ready(
    db: AsyncSession, complaint_id: uuid.UUID, result: TriageOutput
) -> None:
    """Tell the complaint owner the AI analysis is complete (Part 21)."""
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        return
    owner = await db.get(User, complaint.user_id)
    if owner is None or not owner.is_active:
        return
    await notification_service.notify(
        db,
        targets=[owner],
        event=EVENT_AI_COMPLETE,
        complaint_id=complaint.id,
        body=(
            f"AI analysis for '{complaint.title}' is complete — "
            f"{result.severity.value} severity / {result.urgency.value} urgency."
        ),
        link=f"/dashboard/complaints/{complaint.id}",
    )
    await db.commit()


def _agent() -> TriageAgent:
    return TriageAgent(settings=get_settings(), ai=get_ai_service())


async def run_triage(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
    input_data: TriageInput,
) -> TriageRunResponse:
    """Run the triage graph for a complaint and return the persisted result."""
    await _assert_can_view(db, user, complaint_id)

    # Language pipeline (Part 26): honour an explicit non-English language, but
    # for the default "en" request detect the actual language from the complaint
    # description so a Hindi/Marathi complaint is classified as such even when
    # the caller sends no language hint.
    effective = TriageInput(
        description=input_data.description,
        category=input_data.category,
        location=input_data.location,
        language=(
            language_service.detect_language(input_data.description)
            if input_data.language in (None, "en")
            else input_data.language
        ),
    )
    run: AgentRun = await _agent().run(
        db,
        complaint_id=complaint_id,
        input_data=effective,
    )
    await db.refresh(run)
    result = (
        TriageOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    if result is not None:
        await _notify_analysis_ready(db, complaint_id, result)
    return TriageRunResponse(
        run_id=run.id,
        status=run.status,
        result=result,
        error=run.error,
        retry_allowed=True,
    )


async def get_latest_analysis(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> AgentRunOut | None:
    """Return the most recent triage run for a complaint, if any."""
    await _assert_can_view(db, user, complaint_id)
    run = await agent_run_service.get_latest_run(db, complaint_id)
    if run is None or run.agent != AGENT_NAME:
        return None
    return agent_run_service.run_out(run)
