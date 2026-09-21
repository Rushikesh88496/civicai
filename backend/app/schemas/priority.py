"""Schemas for the Dynamic Priority & Risk Engine (Part 12).

The Priority Engine is a *deterministic* (no-LLM) scorer. It maps the seven
priority inputs (severity, population impact, critical-infrastructure proximity,
weather, complaint count, historical recurrence, time unresolved) onto a single
0..100 ``score`` and a ``DynamicPriority`` bucket (P1_CRITICAL / P2_HIGH /
P3_MEDIUM / P4_LOW). Every factor is explainable: the result carries its input
value, weight and point contribution so the UI can show a breakdown and score
history. Results persist to ``agent_runs`` (``agent="priority"``) and each
computation appends a row to ``complaint_priority_history``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentStatus, DynamicPriority


class PrioritySignalInputs(BaseModel):
    """The exact inputs the engine scored, with provenance of where each came from."""

    # Deterministic severity label already stored on the complaint (the triage
    # agent set LOW/MEDIUM/HIGH/CRITICAL; the engine treats it as an input only).
    severity: str = "LOW"
    # Proxy for "population impact": number of residents linked to the ward.
    population: int = 0
    # Nearby critical infrastructure (from the context agent / GIS).
    hospitals: int = 0
    schools: int = 0
    bus_stops: int = 0
    # True when the location factor's "zero" is a verified absence (e.g. the GIS
    # lookup resolved with no facilities in range). When False the lookup could
    # not be performed at all (DATA_UNAVAILABLE) and the location factor is
    # EXCLUDED entirely — an unknown nearby never scores as "no infrastructure".
    location_available: bool = True
    # Weather risk (from the context agent / Open-Meteo).
    weather_condition: str | None = None
    rain_mm: float | None = None
    weather_available: bool = False
    # Complaint count near the location (context historical, within radius).
    complaint_count: int = 0
    # Historical recurrence in the same ward (context historical).
    historical_recurrence: int = 0
    ward_resolved: bool = False
    # Hours the complaint has been unresolved (age in the pipeline).
    time_unresolved_hours: float = 0.0


class PriorityFactor(BaseModel):
    """One explainable contributor to the score."""

    # Human-readable factor name (e.g. "Severity", "Critical infrastructure").
    factor: str
    # The raw input value this factor scored (e.g. "HIGH", 3, 12.5).
    input_value: str
    # Whether the signal was present (missing inputs contribute 0 and are absent).
    present: bool = True
    # The configured weight (0..1).
    weight: float
    # Normalized unit in 0..1 after the factor's piecewise mapping.
    unit: float = Field(ge=0.0, le=1.0)
    # Points contributed to the final score = unit * weight * 100.
    contribution: float
    # Short human phrase (e.g. "+20 Critical infrastructure proximity").
    description: str = ""


class PriorityOutput(BaseModel):
    """Validated structured result produced by the Priority Engine."""

    score: int = Field(ge=0, le=100)
    priority: DynamicPriority
    # Explainable factor breakdown (ordered by contribution, descending).
    factors: list[PriorityFactor] = Field(default_factory=list)
    # The exact inputs that produced this score.
    inputs: PrioritySignalInputs = Field(default_factory=PrioritySignalInputs)
    # Score of the previous computation (None on the first run).
    previous_score: int | None = None
    previous_priority: DynamicPriority | None = None
    # True when this score moved by >= the configured change threshold.
    changed: bool = False
    # One-line human summary (score, bucket, biggest driver).
    summary: str = Field(default="", max_length=500)


class PriorityRunOut(BaseModel):
    """Serialized priority engine run persisted to ``agent_runs``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID | None = None
    agent: str
    model: str | None = None
    status: AgentStatus
    duration_ms: int | None = None
    structured_result: PriorityOutput | None = None
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class PriorityRunResponse(BaseModel):
    """Response envelope for running the priority engine on a complaint."""

    run_id: uuid.UUID
    status: AgentStatus
    result: PriorityOutput | None = None
    error: str | None = None
    retry_allowed: bool = True


class PriorityRunIn(BaseModel):
    """Optional body for triggering the priority engine (reserved for future
    input hints; no fields are currently required by the caller)."""

    pass


class PriorityHistoryEntry(BaseModel):
    """A single row of the append-only priority score history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID
    score: int
    priority: DynamicPriority
    previous_score: int | None = None
    changed: bool = False
    calculated_at: datetime
    summary: str | None = None


class PriorityHistoryOut(BaseModel):
    """Full score history for a complaint (newest first)."""

    complaint_id: uuid.UUID
    entries: list[PriorityHistoryEntry] = Field(default_factory=list)


__all__ = [
    "PriorityFactor",
    "PriorityHistoryEntry",
    "PriorityHistoryOut",
    "PriorityOutput",
    "PriorityRunIn",
    "PriorityRunOut",
    "PriorityRunResponse",
    "PrioritySignalInputs",
]
