"""Complaint tracking, detail, timeline and status-transition business logic (Part 5).

Enforces ownership / RBAC so a citizen can only ever see *their own* complaints
while staff (officer / admin / ward representative / field worker) gain access
based on their role, ward, and department. All access decisions receive the
authenticated ``User`` from the dependency — never a client-supplied ID.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Complaint,
    ComplaintDepartmentHistory,
    DepartmentOverride,
    User,
    WorkOrder,
    WorkOrderStatusHistory,
)
from app.models.enums import ComplaintStatus, RoleName
from app.schemas.complaint import (
    ComplaintDetailOut,
    ComplaintLocationOut,
    ComplaintStatusHistoryOut,
    ComplaintTimelineOut,
    WardOut,
    WorkOrderTimelineEvent,
)
from app.services.complaint_service import media_out, record_status_transition

logger = logging.getLogger(__name__)


class ComplaintNotFoundError(Exception):
    """Raised when a complaint does not exist."""


class ComplaintAccessError(Exception):
    """Raised when the authenticated user cannot access a complaint."""


class InvalidStatusTransitionError(ValueError):
    """Raised when a requested status transition is not permitted."""


async def _load_complaint(db: AsyncSession, complaint_id: uuid.UUID) -> Complaint | None:
    return await db.scalar(
        select(Complaint)
        .where(Complaint.id == complaint_id)
        .options(
            selectinload(Complaint.media),
            selectinload(Complaint.complaint_location),
            selectinload(Complaint.status_history),
            selectinload(Complaint.ward),
        )
    )


def user_can_view(user: User, complaint: Complaint) -> bool:
    """Return True if ``user`` may view ``complaint`` based on ownership and RBAC."""
    if user.role.name == RoleName.CITIZEN.value:
        return complaint.user_id == user.id
    if user.role.name == RoleName.WARD_REPRESENTATIVE.value:
        return complaint.ward_id is not None and complaint.ward_id == user.ward_id
    # OFFICER, ADMIN, FIELD_WORKER have broad operational visibility.
    return True


async def get_effective_department(db: AsyncSession, complaint_id: uuid.UUID) -> str | None:
    """Return the department currently in effect for a complaint (Part 13).

    The latest officer override (if any) wins over the most recent routing
    decision. Returns ``None`` when neither a routing decision nor an override has
    been recorded yet.
    """
    override = await db.scalar(
        select(DepartmentOverride)
        .where(DepartmentOverride.complaint_id == complaint_id)
        .order_by(DepartmentOverride.overridden_at.desc())
        .limit(1)
    )
    if override is not None:
        return override.new_department
    routing = await db.scalar(
        select(ComplaintDepartmentHistory)
        .where(ComplaintDepartmentHistory.complaint_id == complaint_id)
        .order_by(ComplaintDepartmentHistory.calculated_at.desc())
        .limit(1)
    )
    return routing.primary_department if routing is not None else None


async def get_complaint_detail(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> ComplaintDetailOut:
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise ComplaintNotFoundError
    if not user_can_view(user, complaint):
        raise ComplaintAccessError

    ward_out: WardOut | None = None
    if complaint.ward is not None:
        ward_out = WardOut(id=complaint.ward_id, name=complaint.ward.name, code=complaint.ward.code)

    complaint_location: ComplaintLocationOut | None = None
    if complaint.complaint_location is not None:
        loc = complaint.complaint_location
        complaint_location = ComplaintLocationOut(
            latitude=loc.latitude,
            longitude=loc.longitude,
            address=loc.address,
            source=loc.source,
            geopoint_denied=loc.geopoint_denied,
            accuracy_m=loc.accuracy_m,
        )

    detail = ComplaintDetailOut(
        id=complaint.id,
        title=complaint.title,
        description=complaint.description,
        category=complaint.category,
        priority=complaint.priority,
        status=complaint.status,
        location=complaint.location,
        created_at=complaint.created_at,
        updated_at=complaint.updated_at,
        user_id=complaint.user_id,
        ward=ward_out,
        department=await get_effective_department(db, complaint.id),
        complaint_location=complaint_location,
        media=[media_out(m) for m in complaint.media],
    )

    # INTELLIGENCE PIPELINE: for staff viewing the detail page, automatically
    # enrich context (weather / GIS / history / infrastructure) and compute the
    # deterministic priority score when they are missing or stale, so the
    # officer sees real intelligence without clicking through the pipeline.
    # The detail object above is fully built first; the agents use their own
    # sessions/commits, so the read never races with the pipeline's writes.
    if user.role.name in (
        RoleName.OFFICER.value,
        RoleName.ADMIN.value,
        RoleName.WARD_REPRESENTATIVE.value,
    ):
        await ensure_auto_intelligence(db, user, complaint.id)

    return detail


async def ensure_auto_intelligence(db: AsyncSession, user: User, complaint_id: uuid.UUID) -> None:
    """Auto-run the context → priority intelligence pipeline on detail views.

    Gated to staff roles (officer / admin / ward rep) by
    :func:`app.services.complaint_intelligence_service.ensure_intelligence_pipeline`;
    idempotent (missing/FAILED/stale runs only), never raises — intelligence is
    always an enhancement, never a reason the detail view fails.
    """
    try:
        # Imported lazily to avoid an import cycle: the context/priority services
        # themselves import this module (access helpers).
        from app.services.complaint_intelligence_service import (
            ensure_intelligence_pipeline,
        )

        await ensure_intelligence_pipeline(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - auto-intelligence must never break reads
        logger.warning("Auto-intelligence skipped for %s: %s", complaint_id, exc)


async def get_complaint_timeline(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> ComplaintTimelineOut:
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise ComplaintNotFoundError
    if not user_can_view(user, complaint):
        raise ComplaintAccessError

    events = [
        ComplaintStatusHistoryOut(
            id=e.id,
            status=e.status,
            actor_id=e.actor_id,
            note=e.note,
            recorded_at=e.recorded_at,
        )
        for e in complaint.status_history
    ]
    events.sort(key=lambda e: e.recorded_at)

    # Part 32: merge the work-order milestone trail (officer review → assignment
    # → acceptance → in-progress → evidence → verification) so the complaint
    # timeline renders the complete human-in-the-loop lifecycle.
    orders = (
        (
            await db.execute(
                select(WorkOrder)
                .where(WorkOrder.complaint_id == complaint_id)
                .options(
                    selectinload(WorkOrder.status_history).selectinload(
                        WorkOrderStatusHistory.actor
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    work_order_events = [
        WorkOrderTimelineEvent(
            work_order_id=order.id,
            action=h.action,
            status=h.to_status,
            actor_name=h.actor.full_name if h.actor is not None else None,
            note=h.note,
            recorded_at=h.recorded_at,
        )
        for order in orders
        for h in sorted(order.status_history, key=lambda h: h.recorded_at)
    ]
    return ComplaintTimelineOut(
        complaint_id=complaint.id,
        current_status=complaint.status,
        events=events,
        work_order_events=work_order_events,
    )


async def transition_complaint(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
    new_status: ComplaintStatus,
    note: str | None = None,
) -> ComplaintDetailOut:
    """Apply a status change to a complaint and record it in the timeline."""
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise ComplaintNotFoundError
    if not user_can_view(user, complaint):
        raise ComplaintAccessError

    if new_status == complaint.status:
        raise InvalidStatusTransitionError("Complaint is already in that status.")

    complaint.status = new_status
    db.add(
        record_status_transition(
            complaint,
            new_status,
            actor_id=user.id,
            note=note,
        )
    )
    await db.commit()
    return await get_complaint_detail(db, user, complaint_id)
