"""Citizen complaint-ratings business logic (Part 22).

A complaint owner can submit exactly one rating once the incident is resolved.
The analytics service aggregates these rows into the satisfaction KPI.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Complaint, ComplaintRating, ComplaintStatusHistory, User
from app.models.enums import ComplaintStatus

_RESOLVED_VALUES = [
    ComplaintStatus.RESOLVED.value,
    ComplaintStatus.CITIZEN_VERIFIED.value,
    ComplaintStatus.CLOSED.value,
]


class RatingError(Exception):
    pass


class ComplaintNotFoundError(RatingError):
    pass


class RatingAccessError(RatingError):
    pass


class AlreadyRatedError(RatingError):
    pass


class ComplaintNotResolvedError(RatingError):
    pass


async def create_rating(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
    rating: int,
    comment: str | None,
) -> ComplaintRating:
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        raise ComplaintNotFoundError("Complaint not found.")

    if complaint.user_id != user.id:
        raise RatingAccessError("You cannot rate this complaint.")

    resolved_ts = await db.scalar(
        select(ComplaintStatusHistory.recorded_at)
        .where(
            ComplaintStatusHistory.complaint_id == complaint_id,
            ComplaintStatusHistory.status.in_(_RESOLVED_VALUES),
        )
        .limit(1)
    )
    resolved_now = complaint.status.value in _RESOLVED_VALUES
    if not resolved_now and resolved_ts is None:
        raise ComplaintNotResolvedError("Complaint is not resolved yet.")

    existing = await db.scalar(
        select(ComplaintRating.id).where(ComplaintRating.complaint_id == complaint_id).limit(1)
    )
    if existing is not None:
        raise AlreadyRatedError("Complaint already has a rating.")

    row = ComplaintRating(
        complaint_id=complaint_id,
        user_id=user.id,
        rating=rating,
        comment=comment,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
