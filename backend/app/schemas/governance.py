"""Pydantic schemas for the AI governance & evidence APIs (Part 28)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AIDecisionOut(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID | None
    agent_name: str
    model_name: str
    prompt_version: str | None
    input_summary: str | None
    output_summary: str | None
    confidence: float | None
    tool_calls: dict | list | None
    result: dict | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceCheckOut(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID | None
    decision_id: uuid.UUID | None
    claim_type: str
    claimed_value: str
    actual_value: str | None
    source: str
    is_match: bool
    discrepancy_pct: float | None
    evidence_data: dict | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OverrideIn(BaseModel):
    override_type: str = Field(..., min_length=1, max_length=64)
    original_value: str | None = None
    new_value: str | None = None
    decision_id: uuid.UUID | None = None
    reason: str = Field(..., min_length=3, max_length=2000)


class OverrideOut(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID | None
    decision_id: uuid.UUID | None
    override_type: str
    original_value: str | None
    new_value: str | None
    original_data: dict | None
    new_data: dict | None
    reason: str
    user_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GovernanceSummary(BaseModel):
    complaint_id: uuid.UUID
    decision_count: int
    evidence_check_count: int
    override_count: int
    has_mismatches: bool
