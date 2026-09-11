"""Schemas for the Municipal Officer Command Center (Part 15).

Provides the officer-facing operational dashboard data:
* KPIs (total, P1/P2, pending, in-progress, resolved, SLA breaches)
* a filterable / searchable / paginated priority queue of complaints
* map data (complaints, incidents, work orders, wards, hotspots)
* an AI-activity status panel (per-agent + status aggregates)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ComplaintStatus


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #
class CommandCenterKpis(BaseModel):
    """High-level operational counts for the command center header."""

    total_complaints: int = 0
    p1: int = 0
    p2: int = 0
    p3: int = 0
    p4: int = 0
    pending: int = 0
    in_progress: int = 0
    resolved: int = 0
    sla_breaches: int = 0
    sla_at_risk: int = 0  # open orders in the warning window (Part 20)


# --------------------------------------------------------------------------- #
# Priority queue
# --------------------------------------------------------------------------- #
class CommandCenterComplaint(BaseModel):
    """A single row in the officer priority queue."""

    id: uuid.UUID
    complaint_id: uuid.UUID
    title: str
    description: str | None = None
    incident: str | None = None
    category: str
    status: ComplaintStatus
    priority: str | None = None  # deterministic bucket (e.g. P1_CRITICAL)
    priority_score: int | None = None
    complaint_priority: str | None = None  # triage severity label
    department: str | None = None  # effective department
    ward_code: str | None = None
    ward_name: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    sla_due_at: datetime | None = None
    work_order_status: str | None = None


class PriorityQueueOut(BaseModel):
    """Paginated priority queue of complaints."""

    items: list[CommandCenterComplaint] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25
    total_pages: int = 1


# --------------------------------------------------------------------------- #
# Map data
# --------------------------------------------------------------------------- #
class MapComplaint(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    priority: str | None = None
    department: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    ward_code: str | None = None
    created_at: datetime


class MapWorkOrder(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID
    department: str
    status: str
    worker_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    eta_minutes: int | None = None


class MapWard(BaseModel):
    ward_id: uuid.UUID
    name: str
    code: str
    complaint_count: int = 0


class MapHotspot(BaseModel):
    """A hotspot bin (one per ward) with aggregated open-complaint weight."""

    ward_id: uuid.UUID | None = None
    ward_code: str | None = None
    ward_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    complaint_count: int = 0
    open_count: int = 0
    priority_weight: float = 0.0  # P1=1.0, P2=0.75, P3=0.5, P4/P0=0.25


class MapDataOut(BaseModel):
    complaints: list[MapComplaint] = Field(default_factory=list)
    work_orders: list[MapWorkOrder] = Field(default_factory=list)
    wards: list[MapWard] = Field(default_factory=list)
    hotspots: list[MapHotspot] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# AI activity
# --------------------------------------------------------------------------- #
class AgentActivity(BaseModel):
    """Aggregate run counts for one agent name + status."""

    agent: str
    status: str
    count: int = 0
    last_run_at: datetime | None = None


class AgentSummary(BaseModel):
    """One row in the AI-activity panel (one per agent)."""

    agent: str
    label: str
    enabled: bool = True
    total: int = 0
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    last_activity_at: datetime | None = None


class AiActivityOut(BaseModel):
    last_updated: datetime
    agents: list[AgentSummary] = Field(default_factory=list)
    breakdown: list[AgentActivity] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Realtime
# --------------------------------------------------------------------------- #
class CommandCenterSnapshot(BaseModel):
    """Aggregate payload pushed over the command-center WebSocket."""

    type: str = "snapshot"
    kpis: CommandCenterKpis = Field(default_factory=CommandCenterKpis)
    ai_activity: AiActivityOut | None = None
    changed_at: datetime


# Realtime event published when agent/full pipeline activity changes.
COMMAND_CENTER_CHANNEL = "civicagent:command-center"


__all__ = [
    "AgentActivity",
    "AgentSummary",
    "AiActivityOut",
    "CommandCenterComplaint",
    "CommandCenterKpis",
    "CommandCenterSnapshot",
    "MapComplaint",
    "MapDataOut",
    "MapHotspot",
    "MapWard",
    "MapWorkOrder",
    "PriorityQueueOut",
    "COMMAND_CENTER_CHANNEL",
]
