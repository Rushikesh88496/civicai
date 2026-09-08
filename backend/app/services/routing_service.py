"""Service facade for the Department Routing Agent (Part 13).

Wraps ``RoutingAgent`` with complaint access enforcement (only an authenticated
user who may view the source complaint can trigger or read its routing decision),
persists the structured ``RoutingOutput`` to ``agent_runs`` (``agent="routing"``),
exposes the append-only routing-decision history, and handles **officer
overrides** — recording ``old_department`` / ``new_department`` / ``reason`` /
``override_by`` / timestamp into ``department_overrides``.

All access decisions receive the authenticated ``User`` from the dependency —
never a client-supplied ID.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.routing_agent import AGENT_NAME, RoutingAgent
from app.core.config import get_settings
from app.models import (
    AgentRun,
    ComplaintDepartmentHistory,
    DepartmentOverride,
    User,
)
from app.schemas.routing import (
    DepartmentOverrideEntry,
    DepartmentOverrideHistoryOut,
    DepartmentOverrideResponse,
    RoutingHistoryEntry,
    RoutingHistoryOut,
    RoutingOutput,
    RoutingRunOut,
    RoutingRunResponse,
)
from app.services import agent_run_service
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
    _load_complaint,
    get_effective_department,
    user_can_view,
)


class RoutingNotFoundError(ComplaintNotFoundError):
    """Raised when a complaint does not exist (mirrors tracking semantics)."""


class RoutingAccessError(ComplaintAccessError):
    """Raised when the authenticated user cannot access a complaint."""


async def _assert_can_view(db: AsyncSession, user: User, complaint_id: uuid.UUID) -> None:
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise RoutingNotFoundError
    if not user_can_view(user, complaint):
        raise RoutingAccessError


def _agent() -> RoutingAgent:
    return RoutingAgent(settings=get_settings())


async def run_routing(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
) -> RoutingRunResponse:
    """Run the routing agent for a complaint and return the run state."""
    await _assert_can_view(db, user, complaint_id)
    run: AgentRun = await _agent().run(db, complaint_id=complaint_id)
    await db.refresh(run)
    result = (
        RoutingOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return RoutingRunResponse(
        run_id=run.id,
        status=run.status,
        result=result,
        error=run.error,
        retry_allowed=True,
    )


async def get_routing_result(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> RoutingRunOut | None:
    """Return the most recent routing agent run for a complaint, if any."""
    await _assert_can_view(db, user, complaint_id)
    run = await agent_run_service.get_latest_run_for_agent(db, complaint_id, AGENT_NAME)
    if run is None:
        return None
    result = (
        RoutingOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return RoutingRunOut(
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


async def get_routing_history(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> RoutingHistoryOut:
    """Return the append-only routing-decision history (newest first)."""
    await _assert_can_view(db, user, complaint_id)
    rows = (
        (
            await db.execute(
                select(ComplaintDepartmentHistory)
                .where(ComplaintDepartmentHistory.complaint_id == complaint_id)
                .order_by(ComplaintDepartmentHistory.calculated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    entries = [
        RoutingHistoryEntry(
            id=e.id,
            complaint_id=e.complaint_id,
            primary_department=e.primary_department,
            secondary_departments=e.secondary_departments or [],
            confidence=e.confidence,
            ambiguous=e.ambiguous,
            calculated_at=e.calculated_at,
        )
        for e in rows
    ]
    return RoutingHistoryOut(complaint_id=complaint_id, entries=entries)


async def get_override_history(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> DepartmentOverrideHistoryOut:
    """Return all recorded officer overrides for a complaint (newest first)."""
    await _assert_can_view(db, user, complaint_id)
    rows = (
        (
            await db.execute(
                select(DepartmentOverride)
                .where(DepartmentOverride.complaint_id == complaint_id)
                .order_by(DepartmentOverride.overridden_at.desc())
                .options(selectinload(DepartmentOverride.override_by_user))
            )
        )
        .scalars()
        .all()
    )
    overrides = [_override_entry(o) for o in rows]
    return DepartmentOverrideHistoryOut(complaint_id=complaint_id, overrides=overrides)


def _override_entry(o: DepartmentOverride) -> DepartmentOverrideEntry:
    return DepartmentOverrideEntry(
        id=o.id,
        complaint_id=o.complaint_id,
        old_department=o.old_department,
        new_department=o.new_department,
        reason=o.reason,
        override_by=o.override_by,
        override_by_name=o.override_by_user.full_name if o.override_by_user else None,
        overridden_at=o.overridden_at,
    )


async def override_department(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
    new_department: str,
    reason: str,
) -> DepartmentOverrideResponse:
    """Record an officer override of a complaint's department and return the audit row.

    The officer must be allowed to *view* the complaint (staff roles authorize the
    endpoint; the view guard prevents overriding someone else's complaint by ID and
    keeps citizens out). ``old_department`` is read from the current effective
    department so the audit trail is complete.
    """
    await _assert_can_view(db, user, complaint_id)
    if not get_settings().ROUTING_OVERRIDE_ENABLED:
        raise RoutingNotFoundError("Routing overrides are currently disabled.")

    old_department = await get_effective_department(db, complaint_id)
    entry = DepartmentOverride(
        complaint_id=complaint_id,
        old_department=old_department,
        new_department=new_department.upper(),
        reason=reason,
        override_by=user.id,
    )
    db.add(entry)
    await db.commit()
    stored = await db.scalar(
        select(DepartmentOverride)
        .where(DepartmentOverride.id == entry.id)
        .options(selectinload(DepartmentOverride.override_by_user))
    )
    return DepartmentOverrideResponse(
        override=_override_entry(stored),
        current_department=new_department.upper(),
    )
