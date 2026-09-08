"""Municipal Officer Command Center API (Part 15).

Endpoints (officer / admin / ward-representative only):
- GET /command-center/kpis         — headline operational counts
- GET /command-center/queue        — filterable / searchable / paginated priority queue
- GET /command-center/map          — complaints + work orders + wards + hotspots
- GET /command-center/ai-activity  — per-agent run status aggregation
- GET /command-center/snapshot     — aggregate KPI + AI payload (used by the WS fallback)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.command_center import (
    AiActivityOut,
    CommandCenterKpis,
    CommandCenterSnapshot,
    MapDataOut,
    PriorityQueueOut,
)
from app.services import command_center_service

router = APIRouter(prefix="/command-center", tags=["command-center"])

_STAFF_ROLES = (RoleName.OFFICER.value, RoleName.ADMIN.value, RoleName.WARD_REPRESENTATIVE.value)


def _require_staff(user: User) -> User:
    if user.role.name not in _STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access the command center.",
        )
    return user


@router.get("/kpis", response_model=CommandCenterKpis)
async def get_kpis(
    user: User = Depends(require_roles(*_STAFF_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> CommandCenterKpis:
    _require_staff(user)
    return await command_center_service.get_kpis(db, user)


@router.get("/queue", response_model=PriorityQueueOut)
async def get_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status", description="ComplaintStatus"),
    category: str | None = None,
    priority: str | None = Query(None, description="P1_CRITICAL..P4_LOW bucket"),
    ward_id: uuid.UUID | None = None,
    department: str | None = Query(None, description="DepartmentCode routing target"),
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    user: User = Depends(require_roles(*_STAFF_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> PriorityQueueOut:
    _require_staff(user)
    return await command_center_service.get_priority_queue(
        db,
        user,
        page=page,
        page_size=page_size,
        status=status_filter,
        category=category,
        priority=priority,
        ward_id=ward_id,
        department=department,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/map", response_model=MapDataOut)
async def get_map(
    user: User = Depends(require_roles(*_STAFF_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> MapDataOut:
    _require_staff(user)
    return await command_center_service.get_map_data(db, user)


@router.get("/ai-activity", response_model=AiActivityOut)
async def get_ai_activity(
    user: User = Depends(require_roles(*_STAFF_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> AiActivityOut:
    _require_staff(user)
    return await command_center_service.get_ai_activity(db, user)


@router.get("/snapshot", response_model=CommandCenterSnapshot)
async def get_snapshot(
    user: User = Depends(require_roles(*_STAFF_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> CommandCenterSnapshot:
    _require_staff(user)
    snapshot = await command_center_service.build_snapshot(db, user)
    return CommandCenterSnapshot(**snapshot)
