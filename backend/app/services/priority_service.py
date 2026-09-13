"""Service facade for the Dynamic Priority & Risk Engine (Part 12).

Wraps ``PriorityAgent`` with complaint access enforcement (only an authenticated
user who may view the source complaint can trigger or read its priority score),
persists the structured ``PriorityOutput`` to ``agent_runs``
(``agent="priority"``) and exposes the append-only score history.

All access decisions receive the authenticated ``User`` from the dependency —
never a client-supplied ID.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.priority_agent import AGENT_NAME, PriorityAgent
from app.core.config import get_settings
from app.core.notification_types import EVENT_PRIORITY_ASSIGNED, EVENT_PRIORITY_CHANGE
from app.models import (
    AgentRun,
    Complaint,
    ComplaintPriorityHistory,
    FieldWorker,
    User,
    WorkerAssignment,
    WorkOrder,
)
from app.models.enums import AssignmentStatus
from app.schemas.priority import (
    PriorityHistoryEntry,
    PriorityHistoryOut,
    PriorityOutput,
    PriorityRunOut,
    PriorityRunResponse,
)
from app.services import agent_run_service, notification_service
from app.services.ai_governance_service import PROMPT_VERSION_PRIORITY, log_ai_decision
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
    _load_complaint,
    user_can_view,
)


class PriorityNotFoundError(ComplaintNotFoundError):
    """Raised when a complaint does not exist (mirrors tracking semantics)."""


class PriorityAccessError(ComplaintAccessError):
    """Raised when the authenticated user cannot access a complaint."""


async def _assert_can_view(db: AsyncSession, user: User, complaint_id: uuid.UUID) -> None:
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise PriorityNotFoundError
    if not user_can_view(user, complaint):
        raise PriorityAccessError


def _agent() -> PriorityAgent:
    return PriorityAgent(settings=get_settings())


async def run_priority(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
) -> PriorityRunResponse:
    """Run the priority engine for a complaint and return the run state."""
    await _assert_can_view(db, user, complaint_id)
    run: AgentRun = await _agent().run(db, complaint_id=complaint_id)
    await db.refresh(run)
    result = (
        PriorityOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    if result is not None:
        await _log_priority_decision(db, complaint_id, result)
        await _notify_priority(db, complaint_id, result)
    return PriorityRunResponse(
        run_id=run.id,
        status=run.status,
        result=result,
        error=run.error,
        retry_allowed=True,
    )


async def _log_priority_decision(
    db: AsyncSession,
    complaint_id: uuid.UUID,
    result: PriorityOutput,
) -> None:
    """Part 28 — persist the priority engine decision to the AI governance log."""
    await log_ai_decision(
        db,
        complaint_id=complaint_id,
        agent_name=AGENT_NAME,
        model_name="deterministic-priority-v1",
        prompt_version=PROMPT_VERSION_PRIORITY,
        output_summary=result.summary,
        confidence=round(result.score / 100.0, 4),
        result=result.model_dump(mode="json"),
    )


async def _assigned_workers_for_complaint(db: AsyncSession, complaint_id: uuid.UUID) -> list[User]:
    """Users of workers holding an active assignment on the complaint's orders."""
    rows = (
        (
            await db.execute(
                select(FieldWorker)
                .join(WorkerAssignment, WorkerAssignment.worker_id == FieldWorker.id)
                .join(WorkOrder, WorkOrder.id == WorkerAssignment.work_order_id)
                .where(
                    WorkOrder.complaint_id == complaint_id,
                    WorkerAssignment.status.in_(
                        (AssignmentStatus.ASSIGNED.value, AssignmentStatus.REASSIGNED.value)
                    ),
                )
                .options(selectinload(FieldWorker.user))
            )
        )
        .scalars()
        .all()
    )
    return [fw.user for fw in rows if fw.user is not None and fw.user.is_active]


async def _notify_priority(
    db: AsyncSession, complaint_id: uuid.UUID, result: PriorityOutput
) -> None:
    """Notify the owner of the priority bucket and workers of a bucket change (Part 21)."""
    complaint = await db.get(Complaint, complaint_id)
    link = f"/dashboard/complaints/{complaint_id}"
    bucket = result.priority.value

    if complaint is not None:
        owner = await db.get(User, complaint.user_id)
        if owner is not None and owner.is_active:
            await notification_service.notify(
                db,
                targets=[owner],
                event=EVENT_PRIORITY_ASSIGNED,
                complaint_id=complaint_id,
                body=(
                    f"Priority for '{complaint.title}' is now {bucket} (score {result.score}/100)."
                ),
                link=link,
            )

    bucket_changed = (
        result.previous_priority is not None and result.previous_priority != result.priority
    )
    if bucket_changed:
        workers = await _assigned_workers_for_complaint(db, complaint_id)
        if workers:
            await notification_service.notify(
                db,
                targets=workers,
                event=EVENT_PRIORITY_CHANGE,
                complaint_id=complaint_id,
                body=(
                    f"Priority of your work order changed "
                    f"(was {result.previous_priority.value}, now {bucket})."
                ),
                link=link,
            )
    await db.commit()


async def get_priority_result(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> PriorityRunOut | None:
    """Return the most recent priority engine run for a complaint, if any."""
    await _assert_can_view(db, user, complaint_id)
    run = await agent_run_service.get_latest_run_for_agent(db, complaint_id, AGENT_NAME)
    if run is None:
        return None
    result = (
        PriorityOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return PriorityRunOut(
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


async def get_priority_history(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> PriorityHistoryOut:
    """Return the append-only score history for a complaint (newest first)."""
    await _assert_can_view(db, user, complaint_id)
    rows = (
        (
            await db.execute(
                select(ComplaintPriorityHistory)
                .where(ComplaintPriorityHistory.complaint_id == complaint_id)
                .order_by(ComplaintPriorityHistory.calculated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    entries = [
        PriorityHistoryEntry(
            id=e.id,
            complaint_id=e.complaint_id,
            score=e.score,
            priority=e.priority,
            previous_score=e.previous_score,
            changed=e.changed,
            calculated_at=e.calculated_at,
            summary=e.summary,
        )
        for e in rows
    ]
    return PriorityHistoryOut(complaint_id=complaint_id, entries=entries)
