"""Ward Representative Portal API (Part 16).

Endpoints (WARD_REPRESENTATIVE / OFFICER / ADMIN only; representatives are
always scoped to their own assigned ward in the service):
- GET    /ward-rep/dashboard          — ward identity + representative + KPIs
- GET    /ward-rep/map                — the ward's complaints (by priority) + work orders
- GET    /ward-rep/summary            — AI-generated ward summary (Groq or deterministic)
- GET    /ward-rep/complaints/{complaint_id}/conversation   — authorized thread
- POST   /ward-rep/complaints/{complaint_id}/send-update    — representative sends an update
- POST   /ward-rep/complaints/{complaint_id}/escalate       — request an escalation
- GET    /ward-rep/complaints/{complaint_id}/work-order     — view the complaint's work order
- GET    /ward-rep/complaints/{complaint_id}/cluster        — view the complaint cluster
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.ward_rep import (
    ClusterOut,
    ConversationOut,
    DashboardOut,
    EscalationOut,
    ThreadMessageIn,
    WardMapOut,
    WardSummaryOut,
    WorkOrderOut,
)
from app.services import ward_rep_service
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
)

router = APIRouter(prefix="/ward-rep", tags=["ward-rep"])

_WARD_ROLES = (
    RoleName.WARD_REPRESENTATIVE.value,
    RoleName.OFFICER.value,
    RoleName.ADMIN.value,
)


def _ward_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ComplaintNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found.")
    if isinstance(exc, ComplaintAccessError):
        return HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You do not have access to this complaint in your ward.",
        )
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    user: User = Depends(require_roles(*_WARD_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> DashboardOut:
    return await ward_rep_service.get_dashboard(db, user)


@router.get("/map", response_model=WardMapOut)
async def ward_map(
    user: User = Depends(require_roles(*_WARD_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> WardMapOut:
    return await ward_rep_service.get_map(db, user)


@router.get("/summary", response_model=WardSummaryOut)
async def ward_summary(
    user: User = Depends(require_roles(*_WARD_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> WardSummaryOut:
    return await ward_rep_service.get_ward_summary(db, user)


@router.get(
    "/complaints/{complaint_id}/conversation",
    response_model=ConversationOut,
)
async def conversation(
    complaint_id: uuid.UUID,
    user: User = Depends(require_roles(*_WARD_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    try:
        return await ward_rep_service.get_conversation(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _ward_error(exc) from exc


@router.post(
    "/complaints/{complaint_id}/send-update",
    response_model=ConversationOut,
)
async def send_update(
    complaint_id: uuid.UUID,
    payload: ThreadMessageIn,
    user: User = Depends(require_roles(*_WARD_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    try:
        return await ward_rep_service.send_update(db, user, complaint_id, payload.body)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _ward_error(exc) from exc


@router.post(
    "/complaints/{complaint_id}/escalate",
    response_model=EscalationOut,
)
async def escalate(
    complaint_id: uuid.UUID,
    payload: ThreadMessageIn,
    user: User = Depends(require_roles(*_WARD_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> EscalationOut:
    """Request an escalation for a complaint (reason in ``body``)."""
    try:
        return await ward_rep_service.request_escalation(db, user, complaint_id, payload.body)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _ward_error(exc) from exc


@router.get(
    "/complaints/{complaint_id}/work-order",
    response_model=WorkOrderOut | None,
)
async def work_order(
    complaint_id: uuid.UUID,
    user: User = Depends(require_roles(*_WARD_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderOut | None:
    try:
        return await ward_rep_service.get_complaint_work_order(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _ward_error(exc) from exc


@router.get(
    "/complaints/{complaint_id}/cluster",
    response_model=ClusterOut,
)
async def cluster(
    complaint_id: uuid.UUID,
    user: User = Depends(require_roles(*_WARD_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ClusterOut:
    try:
        return await ward_rep_service.get_complaint_cluster(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _ward_error(exc) from exc
