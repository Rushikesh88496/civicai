"""Schemas for the Field Worker Application (Part 18).

The field worker sees a mobile-first dashboard of their assigned jobs and
nearby/P1 work, then walks a guided workflow — accept → navigate (GPS check-in)
→ arrive → start → before photo → repair → after photo → notes → complete —
whose steps are recorded on the server as an append-only ``WorkOrderActivity``
trail. Every action is idempotent for the offline queue: replaying the same
``client_ref`` returns the same state without duplicating rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SlaState, WorkOrderStatus


class WorkerJobOut(BaseModel):
    """A work order as the field worker sees it in dashboard lists.

    ``distance_m`` is the straight-line distance from the worker's supplied
    GPS location (or home base) to the job. ``my_assignment`` is the worker's
    active assignment for this order (None if unassigned). The ``sla_*`` fields
    (Part 20) power the countdown banner on the worker's job page.
    """

    id: uuid.UUID
    complaint_id: uuid.UUID
    incident: str | None = None
    department: str
    priority: str | None = None
    status: WorkOrderStatus
    address: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None
    due_at: datetime | None = None
    eta_minutes: int | None = None
    distance_m: float | None = None
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    worker_notes: str | None = None
    has_before_photo: bool = False
    has_after_photo: bool = False
    sla_state: SlaState = SlaState.ON_TRACK
    sla_progress: float = 0.0
    sla_remaining_seconds: float | None = None
    sla_remaining_human: str | None = None


class WorkerDashboardOut(BaseModel):
    """Field worker dashboard: assigned / nearby / P1 / completed job queues."""

    assigned: list[WorkerJobOut] = Field(default_factory=list)
    nearby: list[WorkerJobOut] = Field(default_factory=list)
    p1: list[WorkerJobOut] = Field(default_factory=list)
    completed: list[WorkerJobOut] = Field(default_factory=list)


class WorkOrderPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    original_filename: str
    content_type: str
    size_bytes: int
    allowed: bool
    url: str = ""
    created_at: datetime


class WorkOrderActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activity_type: str
    note: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geo_denied: bool = False
    media_id: uuid.UUID | None = None
    worker_name: str | None = None
    recorded_at: datetime


class WorkerOrderDetailOut(BaseModel):
    """Full detail bundle for a field worker's job.

    Doubles as the sync payload consumed by the offline queue after reconnect,
    so the client always has the freshest server-side truth.
    """

    work_order: WorkerJobOut
    complaint_id: uuid.UUID
    complaint_title: str | None = None
    complaint_description: str | None = None
    complaint_status: str | None = None
    photos: list[WorkOrderPhotoOut] = Field(default_factory=list)
    activities: list[WorkOrderActivityOut] = Field(default_factory=list)
    status_history: list[dict] = Field(default_factory=list)


class WorkerCheckInIn(BaseModel):
    """A GPS check-in recorded during the navigate/arrive step.

    ``activity_type`` is ``EN_ROUTE`` or ``ARRIVED``. Coordinates are optional:
    when the worker denies GPS (privacy), ``geo_denied`` is set and the server
    records the check-in without a position.
    """

    activity_type: str = Field(pattern="^(EN_ROUTE|ARRIVED)$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geo_denied: bool = False
    note: str | None = Field(default=None, max_length=600)
    client_ref: str | None = Field(default=None, max_length=64)


class WorkerAcceptIn(BaseModel):
    """Accept an assigned job (idempotent via client_ref)."""

    note: str | None = Field(default=None, max_length=600)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geo_denied: bool = False
    client_ref: str | None = Field(default=None, max_length=64)


class WorkerStartIn(BaseModel):
    """Mark a job as started → IN_PROGRESS."""

    note: str | None = Field(default=None, max_length=600)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geo_denied: bool = False
    client_ref: str | None = Field(default=None, max_length=64)


class WorkerNotesIn(BaseModel):
    """Save free-text field notes for a job (offsets the guided workflow)."""

    notes: str = Field(min_length=1, max_length=4000)
    client_ref: str | None = Field(default=None, max_length=64)


class WorkerCompleteIn(BaseModel):
    """Complete a job → COMPLETED (and the complaint → RESOLVED)."""

    notes: str | None = Field(default=None, max_length=4000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geo_denied: bool = False
    client_ref: str | None = Field(default=None, max_length=64)


class WorkerDashboardIn(BaseModel):
    """Optional GPS override so the dashboard can rank "nearby" accurately.

    When omitted the worker's home base coordinates are used.
    """

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


__all__ = [
    "WorkerAcceptIn",
    "WorkerCheckInIn",
    "WorkerCompleteIn",
    "WorkerDashboardIn",
    "WorkerDashboardOut",
    "WorkerJobOut",
    "WorkerNotesIn",
    "WorkerOrderDetailOut",
    "WorkerStartIn",
    "WorkOrderActivityOut",
    "WorkOrderPhotoOut",
]
