"""Pydantic schemas for in-app notifications (Parts 17 + 21)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    """A single in-app notification for the authenticated user."""

    id: uuid.UUID
    notification_type: str
    body: str
    is_read: bool
    created_at: datetime
    read_at: datetime | None = None
    title: str | None = None
    link: str | None = None
    channel: str = "inbox"
    payload: dict | None = None
    complaint_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    work_order_id: uuid.UUID | None = None
    actor_name: str | None = None


class NotificationListOut(BaseModel):
    """The authenticated user's notifications (newest first) + unread count."""

    items: list[NotificationOut] = Field(default_factory=list)
    unread_count: int = 0
    total: int = 0
    page: int = 1
    page_size: int = 50


class UnreadCountOut(BaseModel):
    """Convenience payload for the header badge."""

    unread_count: int = 0


class AcknowledgeOut(BaseModel):
    """Generic acknowledgement."""

    ok: bool = True


__all__ = [
    "AcknowledgeOut",
    "NotificationListOut",
    "NotificationOut",
    "UnreadCountOut",
]
