"""Citizen dashboard API endpoints (only the authenticated user's data)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.citizen import DashboardResponse
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
