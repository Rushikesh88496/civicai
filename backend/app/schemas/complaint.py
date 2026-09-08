"""Schemas for the multimodal complaint submission flow (Part 4) and the
complaint tracking / timeline view (Part 5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ComplaintCategory,
    ComplaintPriority,
    ComplaintStatus,
    MediaType,
)


class ComplaintLocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str | None = Field(default=None, max_length=255)
    # "gps" (from device) or "manual" (typed by the user).
    source: str = Field(default="manual", pattern="^(gps|manual)$")
    # True when the user denied/navigator.geolocation was unavailable and
    # they supplied coordinates by hand.
    geopoint_denied: bool = False


class ComplaintMediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    media_type: MediaType
    original_filename: str
    content_type: str
    size_bytes: int
    url: str = ""
    created_at: datetime


class ComplaintCreateIn(BaseModel):
    description: str = Field(min_length=10, max_length=4000)
    category: ComplaintCategory
    # References to media uploaded first via POST /complaints/media.
    media_ids: list[uuid.UUID] = Field(default_factory=list)
    location: ComplaintLocationIn | None = None
    # Optional ISO 639-1 language for the description (Part 26). When omitted the
    # deterministic language pipeline detects it from the description.
    language: str | None = Field(default=None, min_length=2, max_length=10)


class ComplaintCreateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: ComplaintCategory
    title: str
    description: str | None
    location: str | None
    priority: str
    status: str
    user_id: uuid.UUID
    language: str | None = None
    created_at: datetime
    media: list[ComplaintMediaOut] = Field(default_factory=list)


class UploadResult(BaseModel):
    media: ComplaintMediaOut


class ComplaintLocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    latitude: float
    longitude: float
    address: str | None = None
    source: str
    geopoint_denied: bool = False


class WardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID | None = None
    name: str | None = None
    code: str | None = None


class ComplaintStatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ComplaintStatus
    actor_id: uuid.UUID | None = None
    note: str | None = None
    recorded_at: datetime


class ComplaintDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None = None
    category: ComplaintCategory
    priority: ComplaintPriority
    status: ComplaintStatus
    location: str | None = None
    created_at: datetime
    updated_at: datetime
    user_id: uuid.UUID
    ward: WardOut | None = None
    department: str | None = None
    complaint_location: ComplaintLocationOut | None = None
    media: list[ComplaintMediaOut] = Field(default_factory=list)


class ComplaintTimelineOut(BaseModel):
    complaint_id: uuid.UUID
    current_status: ComplaintStatus
    events: list[ComplaintStatusHistoryOut] = Field(default_factory=list)
