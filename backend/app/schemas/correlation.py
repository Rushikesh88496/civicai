"""Schemas for the Duplicate / Incident Correlation Agent (Part 9).

``CorrelationInput`` is the signal the correlation agent reasons over: the new
complaint's text and coordinates. ``CorrelationOutput`` is the validated,
structured result the agent produces and persists (the decided duplicate status
and, when a possible duplicate is found, the single best matching complaint).

Correlation is a deterministic, numeric pipeline (semantic + spatial + time +
category) so it does **not** need an LLM — embeddings come from a local Sentence
Transformer, similarity from pgvector cosine distance and geospatial proximity
from PostGIS. Results persist to ``agent_runs`` (``agent="correlation"``) and
candidate links persist to the new ``complaint_correlations`` table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AgentStatus,
    CorrelationMatchStatus,
    CorrelationStatus,
)


class CorrelationInput(BaseModel):
    """Signal the correlation agent needs to reason over."""

    # The complaint text used to build the semantic embedding.
    description: str = Field(min_length=1, max_length=4000)
    category: str | None = Field(default=None, max_length=64)
    # GPS coordinates of the complaint (may be None when the location is unknown).
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)


class CorrelationMatch(BaseModel):
    """A candidate duplicate pair surfaced by the correlation agent."""

    correlation_id: uuid.UUID | None = None
    complaint_id: uuid.UUID
    title: str
    category: str | None = None
    # 0..1 cosine semantic similarity of the two complaint texts.
    similarity: float = Field(ge=0.0, le=1.0)
    # Straight-line distance (metres) between the two complaints, if both known.
    distance_m: float | None = None
    # Absolute time difference (hours) between the two complaints.
    time_diff_hours: float | None = None
    # True when both complaints share the same category.
    category_match: bool = False
    # Weighted combination of semantic + geo + time + category (0..1).
    score: float = Field(ge=0.0, le=1.0)
    # Human-readable justification for flagging the match.
    reason: str
    status: CorrelationMatchStatus = CorrelationMatchStatus.PENDING


class CorrelationOutput(BaseModel):
    """Validated structured result produced by the correlation agent."""

    # The correlation decision for the new complaint.
    status: CorrelationStatus = CorrelationStatus.NEW_INCIDENT
    # The single best matching complaint, when status is POSSIBLE_DUPLICATE.
    best_match: CorrelationMatch | None = None
    # Total candidate links considered / persisted in this run.
    candidates_found: int = 0
    # Whether the outcome required human review (always true for POSSIBLE_DUPLICATE).
    human_review_required: bool = False
    # Short summary of the decision for the timeline / UI.
    summary: str = Field(max_length=500)


class CorrelationRunOut(BaseModel):
    """Serialized correlation agent run persisted to ``agent_runs``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID | None = None
    agent: str
    model: str | None = None
    status: AgentStatus
    duration_ms: int | None = None
    structured_result: CorrelationOutput | None = None
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class CorrelationRunResponse(BaseModel):
    """Response envelope for running correlation on a complaint."""

    run_id: uuid.UUID
    status: AgentStatus
    result: CorrelationOutput | None = None
    error: str | None = None
    retry_allowed: bool = True


class CorrelationRunIn(BaseModel):
    """Optional body for triggering correlation (reserved for future input
    hints); no fields are currently required by the caller."""

    pass
