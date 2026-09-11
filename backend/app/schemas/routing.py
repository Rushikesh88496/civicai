"""Schemas for the Department Routing Agent (Part 13).

The Routing Agent deterministically assigns a complaint to one of the seven fixed
departments (WATER, ROADS, ELECTRICAL, WASTE, DRAINAGE, PARKS, EMERGENCY_DISASTER)
from its category fused with the latest triage / vision / priority / context
signals. Output carries ``primary_department``, ``secondary_departments`` (for
multi-department issues), an explainable ``routing_reason`` and a deterministic
``confidence``. Results persist to ``agent_runs`` (``agent="routing"``) and each
computation appends a row to ``complaint_department_history``; an officer can
override via ``department_overrides``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentStatus


class RoutingInputs(BaseModel):
    """The exact inputs the routing engine scored, with provenance."""

    # Complaint category (the primary routing signal).
    category: str
    # The raw description used for the fallen-electrical multi-department hint.
    description_preview: str = ""
    # --- Triage ---
    triage_severity: str | None = None
    triage_confidence: float | None = None
    # --- Vision ---
    vision_severity: str | None = None
    vision_confidence: float | None = None
    # --- Priority ---
    priority_score: int | None = None
    priority_bucket: str | None = None
    # --- Context ---
    weather_condition: str | None = None
    infrastructure_hospitals: int = 0
    infrastructure_schools: int = 0
    infrastructure_bus_stops: int = 0


class RoutingOutput(BaseModel):
    """Validated structured result produced by the Routing Agent."""

    # The recommended primary department code (one of the seven DepartmentCode).
    primary_department: str | None = None
    # Optional multi-department secondaries (department codes).
    secondary_departments: list[str] = Field(default_factory=list)
    # Human-readable explanation of why this department was chosen.
    routing_reason: str = Field(default="", max_length=1000)
    # Deterministic 0..1 confidence in the decision.
    confidence: float = Field(ge=0.0, le=1.0)
    # True when the category was unrecognized / routing is ambiguous.
    ambiguous: bool = False
    # The exact inputs that produced this routing (category + upstream signals).
    inputs: RoutingInputs = Field(default_factory=RoutingInputs)
    # Primary department of the previous computation / effective override.
    previous_department: str | None = None
    # True when the primary department changed vs the previous decision.
    changed: bool = False
    # One-line human summary (department, confidence, multi-department note).
    summary: str = Field(default="", max_length=500)


class RoutingRunOut(BaseModel):
    """Serialized routing agent run persisted to ``agent_runs``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID | None = None
    agent: str
    model: str | None = None
    status: AgentStatus
    duration_ms: int | None = None
    structured_result: RoutingOutput | None = None
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class RoutingRunResponse(BaseModel):
    """Response envelope for running the routing agent on a complaint."""

    run_id: uuid.UUID
    status: AgentStatus
    result: RoutingOutput | None = None
    error: str | None = None
    retry_allowed: bool = True


class RoutingRunIn(BaseModel):
    """Optional body for triggering the routing agent (reserved for future
    input hints; no fields are currently required by the caller)."""

    pass


class RoutingHistoryEntry(BaseModel):
    """A single row of the append-only routing decision history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID
    primary_department: str | None
    secondary_departments: list[str] = Field(default_factory=list)
    confidence: float
    ambiguous: bool
    calculated_at: datetime


class RoutingHistoryOut(BaseModel):
    """Full routing decision history for a complaint (newest first)."""

    complaint_id: uuid.UUID
    entries: list[RoutingHistoryEntry] = Field(default_factory=list)


class DepartmentOverrideIn(BaseModel):
    """Officer-provided override of a complaint's assigned department."""

    new_department: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=600)


class DepartmentOverrideEntry(BaseModel):
    """A single recorded department override (audit trail)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID
    old_department: str | None = None
    new_department: str
    reason: str
    override_by: uuid.UUID
    override_by_name: str | None = None
    overridden_at: datetime


class DepartmentOverrideResponse(BaseModel):
    """Response after an officer overrides a complaint's department."""

    override: DepartmentOverrideEntry
    current_department: str


class DepartmentOverrideHistoryOut(BaseModel):
    """All recorded department overrides for a complaint (newest first)."""

    complaint_id: uuid.UUID
    overrides: list[DepartmentOverrideEntry] = Field(default_factory=list)


__all__ = [
    "DepartmentOverrideEntry",
    "DepartmentOverrideHistoryOut",
    "DepartmentOverrideIn",
    "DepartmentOverrideResponse",
    "RoutingHistoryEntry",
    "RoutingHistoryOut",
    "RoutingInputs",
    "RoutingOutput",
    "RoutingRunIn",
    "RoutingRunOut",
    "RoutingRunResponse",
]
