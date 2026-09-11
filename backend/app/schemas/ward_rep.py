"""Schemas for the Ward Representative Portal (Part 16).

The portal gives a ward representative a ward-scoped operational view:
* a dashboard header (ward identity, representative, and total / open /
  critical / resolved / SLA-breach KPIs)
* a map of the ward's complaints coloured by dynamic priority
* an AI-generated ward summary grounded in the ward's actual records (a live
  Groq call when a key is configured, otherwise a deterministic synthesis)
* actions (view incident, request escalation, send an update to the citizen,
  view a work order, view a complaint cluster)
* authorized citizen ↔ representative conversations (thread messages)

Every payload is scope-checked in the service against the representative's
assigned ward, never trusting a client-supplied scope.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ComplaintStatus, CorrelationStatus


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
class WardRepKpis(BaseModel):
    """Headline counts scoped to a representative's ward."""

    total_complaints: int = 0
    open: int = 0
    critical: int = 0
    resolved: int = 0
    sla_breaches: int = 0


class RepresentativeOut(BaseModel):
    """Identity of a ward's representative."""

    name: str | None = None
    email: str | None = None
    title: str | None = None


class WardRepOut(BaseModel):
    """Identity of the representative's assigned ward."""

    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    representative: RepresentativeOut | None = None


class DashboardOut(BaseModel):
    ward: WardRepOut | None = None
    representative: RepresentativeOut | None = None
    kpis: WardRepKpis = Field(default_factory=WardRepKpis)


# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #
class WardMapComplaint(BaseModel):
    """One complaint on the ward's map, coloured by dynamic priority."""

    id: uuid.UUID
    complaint_id: uuid.UUID
    title: str
    status: ComplaintStatus
    priority: str | None = None  # dynamic bucket (P1..P4)
    department: str | None = None
    category: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    created_at: datetime


class WardMapWorkOrder(BaseModel):
    """A field-work order within the representative's ward."""

    id: uuid.UUID
    complaint_id: uuid.UUID
    department: str
    status: str
    worker_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    eta_minutes: int | None = None


class WardMapOut(BaseModel):
    complaints: list[WardMapComplaint] = Field(default_factory=list)
    work_orders: list[WardMapWorkOrder] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# AI ward summary
# --------------------------------------------------------------------------- #
class WardSummaryOut(BaseModel):
    """AI-generated summary of the ward's complaint landscape.

    ``generated_by`` is "groq" when produced live by the LLM and "synthesized"
    when no Groq key is configured (deterministic, still grounded in real
    records). ``generated_at`` and ``complaint_count`` document provenance and
    data volume so the human reader can judge confidence.
    """

    summary: str
    highlights: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    generated_by: str = "synthesized"
    generated_at: datetime
    complaint_count: int = 0


# --------------------------------------------------------------------------- #
# Conversations
# --------------------------------------------------------------------------- #
class ThreadMessageIn(BaseModel):
    """Body for sending a new message on a complaint's thread."""

    body: str = Field(..., min_length=1, max_length=4000)


class ThreadMessageOut(BaseModel):
    """One message in an authorized complaint thread."""

    id: uuid.UUID
    complaint_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str | None = None
    role: str
    body: str
    created_at: datetime


class ConversationOut(BaseModel):
    """A complaint thread plus all of its (authorized) messages."""

    complaint_id: uuid.UUID
    complaint_title: str
    messages: list[ThreadMessageOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
class EscalationOut(BaseModel):
    """Result of a successful ward-representative escalation request."""

    complaint_id: uuid.UUID
    status: ComplaintStatus
    note: str


class WorkOrderOut(BaseModel):
    """A work order surfaced for a representative to view."""

    id: uuid.UUID
    complaint_id: uuid.UUID
    incident: str | None = None
    department: str
    priority: str | None = None
    status: str
    worker_name: str | None = None
    eta_minutes: int | None = None
    due_at: datetime | None = None


class ClusterItem(BaseModel):
    """A single member complaint of a correlation cluster."""

    id: uuid.UUID
    complaint_id: uuid.UUID
    title: str
    status: ComplaintStatus
    priority: str | None = None  # dynamic bucket
    created_at: datetime
    similarity: float | None = None  # similarity to the queried complaint
    distance_m: float | None = None
    correlation_status: CorrelationStatus | None = None


class ClusterOut(BaseModel):
    """A complaint cluster: the queried complaint + its correlates."""

    base_complaint_id: uuid.UUID
    base_title: str
    status: str
    members: list[ClusterItem] = Field(default_factory=list)


__all__ = [
    "ClusterItem",
    "ClusterOut",
    "ConversationOut",
    "DashboardOut",
    "EscalationOut",
    "RepresentativeOut",
    "ThreadMessageIn",
    "ThreadMessageOut",
    "WardMapComplaint",
    "WardMapOut",
    "WardMapWorkOrder",
    "WardRepKpis",
    "WardRepOut",
    "WardSummaryOut",
    "WorkOrderOut",
]
