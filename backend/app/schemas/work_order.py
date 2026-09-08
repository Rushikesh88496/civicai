"""Schemas for Work Orders & Autonomous Dispatch (Part 14).

The Dispatch Agent deterministically selects a field worker for a complaint's
work order (availability / skill / distance / workload / equipment — never
random), computes an honest ETA (``source="live"`` vs ``source="estimated"``) and
persists a *draft* work order (``PENDING_APPROVAL``) plus a recommendation. An
officer then approves / assigns / reassigns / escalates / rejects / closes it.
Every action is recorded in an append-only status-history audit trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentStatus, AssignmentStatus, WorkOrderAction, WorkOrderStatus


class CandidateScoreOut(BaseModel):
    """Scoring breakdown for one candidate worker (deterministic, never random)."""

    worker_id: uuid.UUID
    name: str
    score: float = Field(ge=0.0, le=1.0)
    available: bool
    availability: float
    skill: float
    distance: float
    workload: float
    equipment: float
    reasons: list[str] = Field(default_factory=list)


class DispatchInputs(BaseModel):
    """The inputs the dispatch engine actually scored."""

    complaint_id: uuid.UUID
    department: str
    priority: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    required_equipment: list[str] = Field(default_factory=list)
    lat: float | None = None
    lon: float | None = None
    incident: str | None = None


class DispatchRecommendation(BaseModel):
    """The dispatch agent's deterministic recommendation (may have no worker)."""

    department: str
    priority: str | None = None
    recommended_action: str = Field(default="", max_length=1000)
    required_skills: list[str] = Field(default_factory=list)
    required_equipment: list[str] = Field(default_factory=list)
    recommended_worker_id: uuid.UUID | None = None
    recommended_worker_name: str | None = None
    candidates: list[CandidateScoreOut] = Field(default_factory=list)
    sla_hours: int | None = None
    eta_minutes: int | None = None
    eta_source: str | None = None  # "live" | "estimated"
    no_worker_reason: str | None = None


class DispatchOutput(BaseModel):
    """Validated structured result produced by the Dispatch Agent."""

    recommendation: DispatchRecommendation = Field(default_factory=DispatchRecommendation)
    inputs: DispatchInputs = Field(default_factory=DispatchInputs)


class DispatchRunOut(BaseModel):
    """Serialized dispatch agent run persisted to ``agent_runs``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID | None = None
    agent: str
    model: str | None = None
    status: AgentStatus
    duration_ms: int | None = None
    structured_result: DispatchOutput | None = None
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class DispatchRunIn(BaseModel):
    """Optional body for triggering dispatch (no caller inputs required)."""

    pass


class DispatchRunResponse(BaseModel):
    """Response envelope for running dispatch on a complaint."""

    run_id: uuid.UUID
    status: AgentStatus
    work_order_id: uuid.UUID | None = None
    result: DispatchOutput | None = None
    error: str | None = None
    retry_allowed: bool = True


class WorkOrderDetailOut(BaseModel):
    """Full work-order detail."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID
    incident: str | None = None
    department: str
    priority: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None
    address: str | None = None
    sla_hours: int | None = None
    due_at: datetime | None = None
    recommended_action: str | None = None
    status: WorkOrderStatus
    eta_minutes: int | None = None
    eta_source: str | None = None
    worker_name: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class WorkOrderListOut(BaseModel):
    """All work orders for a complaint (newest first)."""

    complaint_id: uuid.UUID
    work_orders: list[WorkOrderDetailOut] = Field(default_factory=list)


class WorkOrderStatusHistoryEntry(BaseModel):
    """A single append-only status-history row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: WorkOrderAction
    from_status: WorkOrderStatus | None = None
    to_status: WorkOrderStatus
    actor_name: str | None = None
    note: str | None = None
    recorded_at: datetime


class WorkOrderStatusHistoryOut(BaseModel):
    """Full status-history trail for a work order (newest first)."""

    work_order_id: uuid.UUID
    entries: list[WorkOrderStatusHistoryEntry] = Field(default_factory=list)


class WorkerAssignmentOut(BaseModel):
    """A worker/work-order assignment (active + archived)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    work_order_id: uuid.UUID
    worker_id: uuid.UUID
    worker_name: str | None = None
    status: AssignmentStatus
    assigned_by_name: str | None = None
    reason: str | None = None
    assigned_at: datetime


class WorkOrderAssignIn(BaseModel):
    """Officer assigns (or reassigns) a work order to a worker."""

    worker_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=600)


class WorkOrderActionIn(BaseModel):
    """Officer approves/rejects/closes a work order (optional note)."""

    note: str = Field(default="", max_length=600)


class WorkOrderEscalateIn(BaseModel):
    """Officer escalates a work order (reason required)."""

    reason: str = Field(min_length=3, max_length=600)


class WorkOrderDetailBundle(BaseModel):
    """Work-order detail plus its assignments and status history in one response."""

    work_order: WorkOrderDetailOut
    assignments: list[WorkerAssignmentOut] = Field(default_factory=list)
    status_history: list[WorkOrderStatusHistoryEntry] = Field(default_factory=list)


__all__ = [
    "CandidateScoreOut",
    "DispatchInputs",
    "DispatchOutput",
    "DispatchRecommendation",
    "DispatchRunIn",
    "DispatchRunOut",
    "DispatchRunResponse",
    "WorkOrderActionIn",
    "WorkOrderAssignIn",
    "WorkOrderDetailBundle",
    "WorkOrderDetailOut",
    "WorkOrderEscalateIn",
    "WorkOrderListOut",
    "WorkOrderStatusHistoryEntry",
    "WorkOrderStatusHistoryOut",
    "WorkerAssignmentOut",
]
