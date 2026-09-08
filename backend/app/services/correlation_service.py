"""Service facade for the Duplicate / Incident Correlation Agent (Part 9).

Wraps ``CorrelationAgent`` with complaint access enforcement (only an
authenticated user who may view the source complaint can trigger or read its
correlation results), persists candidate links, and exposes officer decisions
(Confirm/Reject). ``confirm_correlation`` marks the pair ``CONFIRMED`` and flips
the source complaint's ``correlation_status`` to ``CONFIRMED_DUPLICATE``;
``reject_correlation`` marks it ``REJECTED`` (a false positive) without changing
the source complaint's correlation status.

All access decisions receive the authenticated ``User`` from the dependency —
never a client-supplied ID.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.correlation_agent import AGENT_NAME, CorrelationAgent
from app.core.config import get_settings
from app.models import AgentRun, Complaint, ComplaintCorrelation, User
from app.models.enums import CorrelationMatchStatus, CorrelationStatus, RoleName
from app.schemas.correlation import (
    CorrelationMatch,
    CorrelationOutput,
    CorrelationRunOut,
    CorrelationRunResponse,
)
from app.services import agent_run_service, embedding_service
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
    _load_complaint,
    user_can_view,
)


class CorrelationNotFoundError(ComplaintNotFoundError):
    """Raised when a complaint does not exist (mirrors tracking semantics)."""


class CorrelationAccessError(ComplaintAccessError):
    """Raised when the authenticated user cannot access a complaint."""


class CandidateNotFoundError(Exception):
    """Raised when a candidate correlation link does not exist."""


class CandidateDecidedError(ValueError):
    """Raised when an officer tries to decide on an already-decided candidate."""


async def _assert_can_view(db: AsyncSession, user: User, complaint_id: uuid.UUID) -> None:
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise CorrelationNotFoundError
    if not user_can_view(user, complaint):
        raise CorrelationAccessError


def _agent() -> CorrelationAgent:
    settings = get_settings()
    return CorrelationAgent(
        settings=settings,
        embedding_service=embedding_service.EmbeddingService(settings=settings),
    )


def _is_staff(user: User) -> bool:
    return user.role.name in {
        RoleName.OFFICER.value,
        RoleName.ADMIN.value,
        RoleName.WARD_REPRESENTATIVE.value,
    }


async def run_correlation(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
) -> CorrelationRunResponse:
    """Run the correlation graph for a complaint and return the run state."""
    await _assert_can_view(db, user, complaint_id)
    run: AgentRun = await _agent().run(db, complaint_id=complaint_id)
    await db.refresh(run)
    result = (
        CorrelationOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return CorrelationRunResponse(
        run_id=run.id,
        status=run.status,
        result=result,
        error=run.error,
        retry_allowed=True,
    )


async def get_correlation_result(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> CorrelationRunOut | None:
    """Return the most recent correlation run for a complaint, if any."""
    await _assert_can_view(db, user, complaint_id)
    run = await agent_run_service.get_latest_run(db, complaint_id)
    if run is None or run.agent != AGENT_NAME:
        return None
    result = (
        CorrelationOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return CorrelationRunOut(
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


async def list_candidates(
    db: AsyncSession, user: User, source_complaint_id: uuid.UUID
) -> list[CorrelationMatch]:
    """Return the candidate duplicate links for a complaint (any status)."""
    await _assert_can_view(db, user, source_complaint_id)
    rows = (
        (
            await db.execute(
                select(ComplaintCorrelation)
                .where(ComplaintCorrelation.source_complaint_id == source_complaint_id)
                .order_by(ComplaintCorrelation.score.desc())
            )
        )
        .scalars()
        .all()
    )
    # Resolve titles/categories for the targets in one query.
    targets = {
        c.id: c
        for c in (
            await db.execute(
                select(Complaint).where(Complaint.id.in_({r.target_complaint_id for r in rows}))
            )
        )
        .scalars()
        .all()
    }
    out: list[CorrelationMatch] = []
    for r in rows:
        target = targets.get(r.target_complaint_id)
        out.append(
            CorrelationMatch(
                correlation_id=r.id,
                complaint_id=r.target_complaint_id,
                title=target.title if target else "",
                category=target.category.value if target and target.category else None,
                similarity=r.similarity,
                distance_m=r.distance_m,
                time_diff_hours=r.time_diff_hours,
                category_match=r.category_match,
                score=r.score,
                reason=r.reason,
                status=r.status,
            )
        )
    return out


async def _load_candidate(
    db: AsyncSession, correlation_id: uuid.UUID
) -> ComplaintCorrelation | None:
    return await db.get(ComplaintCorrelation, correlation_id)


async def decide_candidate(
    db: AsyncSession,
    user: User,
    correlation_id: uuid.UUID,
    *,
    confirm: bool,
) -> CorrelationMatch:
    """Officer decision on a candidate link (Confirm or Reject)."""
    if not _is_staff(user):
        raise CorrelationAccessError
    cand = await _load_candidate(db, correlation_id)
    if cand is None:
        raise CandidateNotFoundError
    if cand.status != CorrelationMatchStatus.PENDING:
        raise CandidateDecidedError

    cand.status = CorrelationMatchStatus.CONFIRMED if confirm else CorrelationMatchStatus.REJECTED
    cand.decided_by = user.id
    cand.decided_at = cand.decided_at or _utcnow()

    source = await db.get(Complaint, cand.source_complaint_id)
    if source is not None:
        source.correlation_status = (
            CorrelationStatus.CONFIRMED_DUPLICATE
            if confirm
            else CorrelationStatus.POSSIBLE_DUPLICATE
        )
    await db.commit()
    await db.refresh(cand)

    target = await db.get(Complaint, cand.target_complaint_id)
    return CorrelationMatch(
        correlation_id=cand.id,
        complaint_id=cand.target_complaint_id,
        title=target.title if target else "",
        category=target.category.value if target and target.category else None,
        similarity=cand.similarity,
        distance_m=cand.distance_m,
        time_diff_hours=cand.time_diff_hours,
        category_match=cand.category_match,
        score=cand.score,
        reason=cand.reason,
        status=cand.status,
    )


def _utcnow():
    from datetime import UTC, datetime

    return datetime.now(UTC)
