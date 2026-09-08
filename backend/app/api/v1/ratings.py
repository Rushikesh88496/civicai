"""Citizen satisfaction rating API (Part 22).

POST /complaints/{complaint_id}/rating — a complaint owner leaves a 1..5 star
score once the incident is resolved (one rating per complaint).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.rating import RatingIn, RatingOut
from app.services import rating_service

router = APIRouter(prefix="/complaints", tags=["ratings"])


def _rating_error(exc: rating_service.RatingError) -> HTTPException:
    if isinstance(exc, rating_service.ComplaintNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, rating_service.RatingAccessError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, rating_service.AlreadyRatedError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, rating_service.ComplaintNotResolvedError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/{complaint_id}/rating",
    response_model=RatingOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(RoleName.CITIZEN.value))],
)
async def submit_rating(
    complaint_id: uuid.UUID,
    payload: RatingIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RatingOut:
    try:
        rating = await rating_service.create_rating(
            db, user, complaint_id, payload.rating, payload.comment
        )
    except rating_service.RatingError as exc:
        raise _rating_error(exc) from exc
    return RatingOut(
        id=rating.id,
        complaint_id=rating.complaint_id,
        rating=rating.rating,
        comment=rating.comment,
        created_at=rating.created_at,
    )
