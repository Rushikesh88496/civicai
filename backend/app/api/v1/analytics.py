"""Civic Analytics API (Part 22).

Staff-only analytics for OFFICER / ADMIN / WARD_REPRESENTATIVE:

- GET  /analytics/overview — headline KPIs + chart series (filters applied)
- GET  /analytics/heatmap  — pre-aggregated complaint clusters for the map
- GET  /analytics/export   — CSV snapshot of the filtered complaint set

WARD_REPRESENTATIVE is automatically scoped to their own ward (mirrors the
command center). Citizens and field workers are rejected at the role gate.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.analytics import AnalyticsOverview, HeatmapOut
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])

_STAFF_ROLES = (RoleName.OFFICER.value, RoleName.ADMIN.value, RoleName.WARD_REPRESENTATIVE.value)


def _require_staff(user: User) -> User:
    if user.role.name not in _STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access civic analytics.",
        )
    return user


def _date_filter(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid timestamp: {value}",
        ) from None
    return parsed


@router.get("/overview", response_model=AnalyticsOverview)
async def get_overview(
    date_from: str | None = Query(None, description="ISO timestamp (complaint.created_at)"),
    date_to: str | None = Query(None, description="ISO timestamp (complaint.created_at)"),
    ward_id: uuid.UUID | None = None,
    department: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    user: User = Depends(require_roles(*_STAFF_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOverview:
    _require_staff(user)
    return await analytics_service.get_overview(
        db,
        user,
        date_from=_date_filter(date_from),
        date_to=_date_filter(date_to),
        ward_id=ward_id,
        department=department,
        category=category,
        priority=priority,
    )


@router.get("/heatmap", response_model=HeatmapOut)
async def get_heatmap(
    date_from: str | None = Query(None, description="ISO timestamp (complaint.created_at)"),
    date_to: str | None = Query(None, description="ISO timestamp (complaint.created_at)"),
    ward_id: uuid.UUID | None = None,
    department: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    user: User = Depends(require_roles(*_STAFF_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> HeatmapOut:
    _require_staff(user)
    return await analytics_service.get_heatmap(
        db,
        user,
        date_from=_date_filter(date_from),
        date_to=_date_filter(date_to),
        ward_id=ward_id,
        department=department,
        category=category,
        priority=priority,
    )


@router.get("/export")
async def export_csv(
    date_from: str | None = Query(None, description="ISO timestamp (complaint.created_at)"),
    date_to: str | None = Query(None, description="ISO timestamp (complaint.created_at)"),
    ward_id: uuid.UUID | None = None,
    department: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    user: User = Depends(require_roles(*_STAFF_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _require_staff(user)
    filename, content = await analytics_service.get_export_csv(
        db,
        user,
        date_from=_date_filter(date_from),
        date_to=_date_filter(date_to),
        ward_id=ward_id,
        department=department,
        category=category,
        priority=priority,
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
