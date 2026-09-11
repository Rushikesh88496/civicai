"""Schemas for the AI Evidence Verification (Vision) Agent (Part 8).

``VisionOutput`` is the validated, structured result produced by the vision
agent after analyzing a complaint's images against its description. It records
whether visual evidence of the reported issue was found, an optional detected
issue label, severity, confidence, a short evidence explanation, and flags for
mismatch / human review so the UI can surface unsafe results.

Vision results are persisted to the shared ``agent_runs`` / ``agent_events``
tables with ``agent="vision"`` (the ``structured_result`` JSONB column), so no
new table is required.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentStatus, TriageSeverity


class VisionInput(BaseModel):
    """Signal the vision agent reasons over: the complaint description and the
    storage keys of the images to analyze (converted to base64 client-side of the
    AI call, never the raw bytes here)."""

    description: str = Field(min_length=1, max_length=4000)
    # The complaint's reported category (used only as hint context).
    category: str | None = Field(default=None, max_length=64)
    # Storage keys of the images attached to the complaint.
    image_keys: list[str] = Field(default_factory=list)


class VisionOutput(BaseModel):
    """Validated structured result produced by the vision agent."""

    # True when the image evidence supports the reported complaint.
    visual_evidence_detected: bool = False
    # Short label of the issue found in the image (e.g. "pothole", "water leak").
    # Empty when no evidence was detected.
    detected_issue: str = Field(default="", max_length=100)
    # Impact severity of what is shown, if any.
    severity: TriageSeverity = TriageSeverity.MEDIUM
    # 0..1 confidence in the visual assessment.
    confidence: float = Field(ge=0.0, le=1.0)
    # Human-readable explanation of what the model observed.
    evidence_description: str = Field(default="", max_length=700)
    # True when the images appear unrelated to the reported complaint (no
    # matching evidence) or contradict it.
    mismatch_detected: bool = False
    # True when confidence is low or a mismatch was flagged — must be reviewed
    # by a human before any action. Never auto-resolves the complaint.
    human_review_required: bool = False


class VisionRunOut(BaseModel):
    """Serialized vision agent run persisted to ``agent_runs``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID | None = None
    agent: str
    model: str | None = None
    status: AgentStatus
    duration_ms: int | None = None
    structured_result: VisionOutput | None = None
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class VisionRunResponse(BaseModel):
    """Response envelope for running vision verification on a complaint."""

    run_id: uuid.UUID
    status: AgentStatus
    result: VisionOutput | None = None
    error: str | None = None
    retry_allowed: bool = True


class VisionRunIn(BaseModel):
    """Optional body for triggering vision verification (reserved for future
    input hints); no fields are currently required by the caller."""

    pass
