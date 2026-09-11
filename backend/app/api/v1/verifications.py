"""AI Resolution Verification API (Part 19).

Runs the Resolution-Verification agent on a completed work order, lets
authorized viewers read the persisted outcome (with resolved BEFORE/AFTER photo
URLs for the side-by-side UI), and lets staff take the human-approval actions.

- POST /work-orders/{order_id}/verify                — run AI resolution verification (staff)
- GET  /work-orders/{order_id}/verification          — latest verification (staff / worker / owner)
- POST /work-orders/{order_id}/verification/review   — human decision (staff)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.verification import (
    VerificationReviewIn,
    VerificationReviewOut,
    VerificationRunResponse,
    WorkOrderEvidenceOut,
    WorkOrderVerificationOut,
)
from app.services import verify_repair_service as svc

router = APIRouter(
    prefix="/work-orders",
    tags=["work-orders", "verification"],
    dependencies=[Depends(get_current_user)],
)

_STAFF_DEPS = [
    Depends(require_roles(RoleName.OFFICER, RoleName.ADMIN, RoleName.WARD_REPRESENTATIVE))
]


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.VerifyNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, svc.VerifyAccessError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, svc.VerifyEvidenceError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if isinstance(exc, svc.VerifyStateError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))


@router.post(
    "/{order_id}/verify",
    response_model=VerificationRunResponse,
    dependencies=_STAFF_DEPS,
)
async def run_verification(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VerificationRunResponse:
    try:
        return await svc.run_verification(db, user, order_id)
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.get("/{order_id}/verification", response_model=WorkOrderVerificationOut | None)
async def get_order_verification(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderVerificationOut | None:
    try:
        return await svc.get_verification(db, user, order_id)
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.get(
    "/{order_id}/evidence",
    response_model=WorkOrderEvidenceOut,
    dependencies=_STAFF_DEPS,
)
async def get_order_evidence(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderEvidenceOut:
    """Full resolution-review bundle: complaint + completion details + BEFORE/AFTER evidence."""
    try:
        return await svc.get_work_order_evidence(db, user, order_id)
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.post(
    "/{order_id}/verification/review",
    response_model=VerificationReviewOut,
    dependencies=_STAFF_DEPS,
)
async def review_verification(
    order_id: uuid.UUID,
    payload: VerificationReviewIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VerificationReviewOut:
    try:
        return await svc.review_verification(
            db,
            user,
            order_id,
            decision=payload.decision,
            note=payload.note,
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc
