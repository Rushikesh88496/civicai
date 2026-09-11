"""In-app notification API (Part 17 + Part 21).

Endpoints (authenticated, scoped to the current user):
- GET    /notifications                — the user's notifications, newest first
                                       (paged; filters: page, page_size, unread_only)
- GET    /notifications/unread-count   — badge count
- POST   /notifications/{id}/read      — mark one notification read
- POST   /notifications/read-all       — mark every notification read
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.notification import (
    AcknowledgeOut,
    NotificationListOut,
    NotificationOut,
    UnreadCountOut,
)
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListOut)
async def notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
    language: str = Query(None, min_length=2, max_length=10),
) -> NotificationListOut:
    return await notification_service.list_notifications(
        db,
        user,
        page=page,
        page_size=page_size,
        unread_only=unread_only,
        language=language,
    )


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UnreadCountOut:
    return UnreadCountOut(unread_count=await notification_service.unread_count(db, user))


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationOut:
    try:
        return await notification_service.mark_read(db, user, notification_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/read-all", response_model=AcknowledgeOut)
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AcknowledgeOut:
    await notification_service.mark_all_read(db, user)
    return AcknowledgeOut(ok=True)
