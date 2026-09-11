"""Schemas for the AI Triage Agent (Part 7).

``TriageInput`` is what the caller feeds the agent — the complaint signal
(description, category, location, language). ``TriageOutput`` is the validated,
structured result the agent produces and persists (category, severity, urgency,
infrastructure type, summary, confidence, recommended action, and a flag the UI
uses to route low-confidence results to human review).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentStatus, ComplaintCategory, TriageSeverity, TriageUrgency


class TriageInput(BaseModel):
    """Signal the triage agent needs to reason over a complaint."""

    description: str = Field(min_length=1, max_length=4000)
    category: ComplaintCategory
    # Free-form location hint (address / ward / landmark).
    location: str | None = Field(default=None, max_length=255)
    # ISO 639-1 language code of the description (defaults to English).
    language: str = Field(default="en", pattern="^[a-zA-Z0-9-]{2,10}$")


class TriageOutput(BaseModel):
    """Validated structured result produced by the triage agent."""

    category: ComplaintCategory
    severity: TriageSeverity
    urgency: TriageUrgency
    # The type of infrastructure / subsystem affected (e.g. "road surface",
    # "pipeline", "drainage network"). A free string chosen by the model.
    infrastructure_type: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=500)
    # 0..1 estimate of how confident the model is.
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str = Field(min_length=1, max_length=500)
    # True when the model output could not be validated (after a retry) or the
    # confidence is low — the complaint is routed to a human reviewer.
    human_review_required: bool = False


class AgentRunOut(BaseModel):
    """Serialized agent run persisted to ``agent_runs``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID | None = None
    agent: str
    model: str | None = None
    status: AgentStatus
    duration_ms: int | None = None
    structured_result: TriageOutput | None = None
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class TriageRunResponse(BaseModel):
    """Response envelope for running triage on a complaint."""

    run_id: uuid.UUID
    status: AgentStatus
    result: TriageOutput | None = None
    error: str | None = None
    retry_allowed: bool = True


class TriageRunIn(BaseModel):
    """Optional body for triggering triage (only ``language`` is user-supplied;
    the description / category / location come from the stored complaint)."""

    language: str = Field(default="en", pattern="^[a-zA-Z0-9-]{2,10}$")


class AgentEventOut(BaseModel):
    """Serialized agent event persisted to ``agent_events``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    event: str
    payload: dict | None = None
    recorded_at: datetime
