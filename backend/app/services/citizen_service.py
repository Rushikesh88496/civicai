"""Citizen dashboard business logic.

All queries are scoped to the requesting user — a citizen can only ever see
their own complaints and their own ward. This is enforced by the service
(receiving the authenticated ``User`` from the dependency, never an ID supplied
by the client).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Complaint, User, Ward, WardRepresentative
from app.models.enums import ComplaintStatus
from app.schemas.citizen import (
    ComplaintOut,
    ComplaintSummary,
    DashboardResponse,
    WardInfoOut,
    WardRepresentativeOut,
)


async def get_dashboard(db: AsyncSession, user: User) -> DashboardResponse:
    """Build the citizen dashboard payload for the given authenticated user."""
    summary = await _summary(db, user.id)
    recent = await _recent_complaints(db, user.id)
    ward_info = await _ward_info(db, user.ward_id)
    return DashboardResponse(
        complaints=summary,
        recent_complaints=recent,
        ward=ward_info,
    )


async def _summary(db: AsyncSession, user_id: uuid.UUID) -> ComplaintSummary:
    rows = (
        await db.execute(
            select(Complaint.status, func.count(Complaint.id))
            .where(Complaint.user_id == user_id)
            .group_by(Complaint.status)
        )
    ).all()
    counts = {status: 0 for status in ComplaintStatus}
    for status_value, total in rows:
        counts[ComplaintStatus(status_value)] = total
    return ComplaintSummary(
        total=sum(counts.values()),
        open=counts[ComplaintStatus.OPEN],
        in_progress=counts[ComplaintStatus.IN_PROGRESS],
        resolved=counts[ComplaintStatus.RESOLVED],
        escalated=counts[ComplaintStatus.ESCALATED],
    )


async def _recent_complaints(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 8
) -> list[ComplaintOut]:
    rows = await db.scalars(
        select(Complaint)
        .where(Complaint.user_id == user_id)
        .order_by(Complaint.created_at.desc())
        .limit(limit)
    )
    return [ComplaintOut.model_validate(row) for row in rows]


async def _ward_info(db: AsyncSession, ward_id: uuid.UUID | None) -> WardInfoOut:
    if ward_id is None:
        return WardInfoOut(code=None, name=None, description=None, representative=None)
    ward = await db.get(Ward, ward_id)
    if ward is None:
        return WardInfoOut(code=None, name=None, description=None, representative=None)

    representative: WardRepresentative | None = await db.scalar(
        select(WardRepresentative)
        .where(WardRepresentative.ward_id == ward_id)
        .order_by(WardRepresentative.created_at.asc())
        .limit(1)
    )

    rep_out: WardRepresentativeOut | None = None
    if representative is not None:
        rep_user = await db.get(User, representative.user_id)
        if rep_user is not None:
            rep_out = WardRepresentativeOut(
                name=rep_user.full_name,
                email=rep_user.email,
                title=representative.title,
            )

    return WardInfoOut(
        code=ward.code,
        name=ward.name,
        description=ward.description,
        representative=rep_out,
    )
