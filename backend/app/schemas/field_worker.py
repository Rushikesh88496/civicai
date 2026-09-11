"""Schemas for the Field Worker Application (Part 18).

The field worker sees a mobile-first dashboard of their assigned jobs and
nearby/P1 work, then walks a guided workflow — accept → navigate (GPS check-in)
→ arrive → start → repair → finish work → submit resolution evidence — whose
steps are recorded on the server as an append-only ``WorkOrderActivity`` trail.
Every action is idempotent for the offline queue: replaying the same
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
    category: str | None = None
    department: str
    priority: str | None = None
    status: WorkOrderStatus
    ward_name: str | None = None
    ward_code: str | None = None
    assigned_at: datetime | None = None
    assigned_by_name: str | None = None
    address: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None
    due_at: datetime | None = None
    eta_minutes: int | None = None
    distance_m: float | None = None
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    evidence_submitted_at: datetime | None = None
    # Why an officer returned the order for rework (RETURNED_FOR_REWORK). Kept
    # through the rework cycle so the worker always sees the required fixes.
    rework_reason: str | None = None
    worker_notes: str | None = None
    has_before_photo: bool = False
    has_after_photo: bool = False
    sla_state: SlaState = SlaState.ON_TRACK
    sla_progress: float = 0.0
    sla_remaining_seconds: float | None = None
    sla_remaining_human: str | None = None


class WorkerProfileOut(BaseModel):
    """A field worker's own profile as shown in the worker app (read-only).

    ``ward`` is derived from the account's registered ward (set by auth/admin, not
    by the worker). ``department`` / ``specialty`` / ``skills`` / ``equipment``
    come from the linked ``FieldWorker`` profile and are managed by admins.
    """

    user_id: uuid.UUID
    full_name: str
    email: str
    role: str
    department_name: str | None = None
    department_code: str | None = None
    ward_name: str | None = None
    ward_code: str | None = None
    specialty: str | None = None
    status: str | None = None
    skill_tags: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    home_latitude: float | None = None
    home_longitude: float | None = None
    base_location: str | None = None
    max_active_orders: int = 0


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
    accuracy_m: float | None = None
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
    records the check-in without a position. ``accuracy_m`` is the browser's
    GPS horizontal accuracy in metres at capture time (0..10,000).
    """

    activity_type: str = Field(pattern="^(EN_ROUTE|ARRIVED)$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=10000)
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


class WorkerFinishIn(BaseModel):
    """Finish the physical work → WORK_COMPLETED (idempotent via client_ref).

    The complaint is deliberately NOT resolved here — resolution is confirmed
    by the AI resolution verification stage after the evidence is submitted.
    """

    notes: str | None = Field(default=None, max_length=4000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geo_denied: bool = False
    client_ref: str | None = Field(default=None, max_length=64)


class WorkerSubmitEvidenceIn(BaseModel):
    """Submit resolution evidence → EVIDENCE_SUBMITTED (idempotent via client_ref).

    The evidence (before/after photos) is uploaded separately through the
    worker photos endpoint; this action stores the completion notes and hands
    the order to the AI resolution verification stage.
    """

    notes: str | None = Field(default=None, max_length=4000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geo_denied: bool = False
    client_ref: str | None = Field(default=None, max_length=64)


class WorkerReworkIn(BaseModel):
    """Restart a RETURNED_FOR_REWORK job (idempotent via client_ref).

    Requires a fresh GPS check-in recorded after the officer's rework request;
    the action moves the order back to IN_PROGRESS and clears the stale
    completed / evidence timestamps so a new verification cycle can run.
    """

    note: str | None = Field(default=None, max_length=600)
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
    "WorkerDashboardIn",
    "WorkerDashboardOut",
    "WorkerFinishIn",
    "WorkerJobOut",
    "WorkerNotesIn",
    "WorkerOrderDetailOut",
    "WorkerProfileOut",
    "WorkerReworkIn",
    "WorkerStartIn",
    "WorkerSubmitEvidenceIn",
    "WorkOrderActivityOut",
    "WorkOrderPhotoOut",
]
