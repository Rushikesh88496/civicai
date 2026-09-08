"""Schemas for the SLA Monitoring Agent (Part 20).

The SLA monitor turns the configurable ``sla_policies`` rulebook into per-order
health states (``ON_TRACK / AT_RISK / BREACHED / COMPLETED``) with a progress
ratio and a human-readable countdown. These schemas back the officer-facing
monitor API (live order list + run triggering) and the structured result the
agent persists to ``agent_runs`` (agent="sla_monitor").
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    ComplaintCategory,
    DepartmentCode,
    DynamicPriority,
    SlaState,
)

# Notification types produced by the monitor's escalation step (free strings,
# matching the existing notification_type convention).
NOTIFICATION_SLA_AT_RISK = "SLA_AT_RISK"
NOTIFICATION_SLA_BREACHED = "SLA_BREACHED"


class SlaPolicyOut(BaseModel):
    """A single (priority, department, category) SLA rule."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None = None
    priority: str | None = None
    department: str | None = None
    category: str | None = None
    sla_hours: int
    at_risk_percent: float
    escalate_on_breach: bool
    active: bool
    created_at: datetime
    updated_at: datetime | None = None


class SlaPolicyIn(BaseModel):
    """Create / update body for an SLA rule (PUT semantics: full replace).

    At least one of ``priority`` / ``department`` / ``category`` must be set; the
    unset dimensions behave as wildcards.
    """

    name: str | None = Field(default=None, max_length=120)
    priority: DynamicPriority | None = None
    department: DepartmentCode | None = None
    category: ComplaintCategory | None = None
    sla_hours: int = Field(gt=0, description="Deadline length in hours")
    at_risk_percent: float = Field(gt=0, le=1, default=0.75)
    escalate_on_breach: bool = True
    active: bool = True

    @model_validator(mode="after")
    def _at_least_one_dimension(self) -> SlaPolicyIn:
        if not any((self.priority, self.department, self.category)):
            raise ValueError(
                "An SLA rule must constrain at least one of priority, department or category."
            )
        return self


class SlaCounts(BaseModel):
    """Aggregate state counts for a scan or the live board."""

    open: int = 0  # at_risk + breached + on_track + no_deadline
    on_track: int = 0
    at_risk: int = 0
    breached: int = 0
    completed: int = 0
    no_deadline: int = 0  # scanned open orders with no resolvable SLA


class OrderSlaSnapshot(BaseModel):
    """SLA health for one work order at a point in time."""

    work_order_id: uuid.UUID
    complaint_id: uuid.UUID
    incident: str | None = None
    category: str | None = None
    department: str
    priority: str | None = None
    status: str
    worker_name: str | None = None
    sla_hours: int | None = None
    due_at: datetime | None = None
    state: SlaState = SlaState.ON_TRACK
    progress: float = 0.0  # 0..1 within the window; >1 once past the deadline
    remaining_seconds: float | None = None
    remaining_human: str | None = None
    breached: bool = False
    at_risk: bool = False
    policy_id: uuid.UUID | None = None


class SlaScanOutput(BaseModel):
    """Structured result persisted to ``agent_runs`` (agent="sla_monitor")."""

    checked_at: datetime
    counts: SlaCounts = Field(default_factory=SlaCounts)
    orders: list[OrderSlaSnapshot] = Field(default_factory=list)
    notifications_sent: dict[str, int] = Field(default_factory=dict)


class SlaOrdersPage(BaseModel):
    """Paginated live SLA board (breached first, then most urgent)."""

    items: list[OrderSlaSnapshot] = Field(default_factory=list)
    counts: SlaCounts = Field(default_factory=SlaCounts)
    total: int = 0
    page: int = 1
    page_size: int = 25


class SlaRunOut(BaseModel):
    """A persisted SLA-monitor run (latest run view)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent: str
    status: str
    duration_ms: int | None = None
    structured_result: SlaScanOutput | None = None
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class SlaRunResponse(BaseModel):
    """Response envelope for triggering an SLA check."""

    run_id: uuid.UUID
    status: str
    result: SlaScanOutput | None = None
    error: str | None = None
    retry_allowed: bool = True


__all__ = [
    "NOTIFICATION_SLA_AT_RISK",
    "NOTIFICATION_SLA_BREACHED",
    "OrderSlaSnapshot",
    "SlaCounts",
    "SlaOrdersPage",
    "SlaPolicyIn",
    "SlaPolicyOut",
    "SlaRunOut",
    "SlaRunResponse",
    "SlaScanOutput",
]
