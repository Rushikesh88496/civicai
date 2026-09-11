"""Citizen dashboard API endpoints (only the authenticated user's data)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.citizen import DashboardResponse, WardInfoOut
from app.services import citizen_service

router = APIRouter(prefix="/citizen", tags=["citizen"])


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    dependencies=[Depends(require_roles(RoleName.CITIZEN.value))],
)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DashboardResponse:
    """Return the authenticated citizen's complaint summary, recent complaints, and ward info."""
    return await citizen_service.get_dashboard(db, user)


@router.get(
    "/my-ward-representative",
    response_model=WardInfoOut,
    dependencies=[Depends(require_roles(RoleName.CITIZEN.value))],
)
async def get_my_ward_representative(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WardInfoOut:
    """Return the authenticated citizen's own ward and its representative.

    The ward is derived from the authenticated user's ``ward_id`` and the
    representative is looked up from the database for that ward only — a citizen
    can never see another ward's representative.
    """
    return await citizen_service.get_my_ward_representative(db, user)
