"""Schemas for the multimodal complaint submission flow (Part 4) and the
complaint tracking / timeline view (Part 5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    # Device GPS horizontal accuracy (rounded to the nearest metre). Only set
    # for gps-sourced coordinates (Part 31).
    accuracy_m: float | None = Field(default=None, ge=0, le=20000)

    @field_validator("accuracy_m")
    @classmethod
    def _round_accuracy(cls, v: float | None) -> float | None:
        if v is None:
            return None
        return round(v, 1)

    @model_validator(mode="after")
    def _validate_location_rules(self) -> ComplaintLocationIn:
        # Part 33: the platform never accepts fake/placeholder coordinates.
        # (0,0) is the classic "GPS replaced by placeholder" sentinel — reject it
        # outright. A real device never reports exactly (0.000000, 0.000000).
        if self.latitude == 0 and self.longitude == 0:
            raise ValueError(
                "(0,0) is not a valid location — capture real GPS coordinates or "
                "place the pin on the map manually."
            )
        # Accuracy is a device measurement — it only makes sense for GPS points.
        if self.source != "gps" and self.accuracy_m is not None:
            raise ValueError("accuracy_m is only allowed for source='gps' coordinates.")
        return self


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
    accuracy_m: float | None = None


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
    # Part 32: work-order milestone events merged into the complaint timeline so
    # the UI can render the full lifecycle (officer review → official assignment
    # → worker accepted → in progress → …) without a separate request.
    work_order_events: list[WorkOrderTimelineEvent] = Field(default_factory=list)


class WorkOrderTimelineEvent(BaseModel):
    """A single work-order milestone surfaced in the complaint timeline (Part 32)."""

    work_order_id: uuid.UUID
    action: str
    status: str
    actor_name: str | None = None
    note: str | None = None
    recorded_at: datetime
