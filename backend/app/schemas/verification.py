"""Schemas for the AI Resolution Verification (Part 19).

The Resolution-Verification agent compares a completed work order's BEFORE /
AFTER photos against the original complaint description and emits a
:class:`VerificationOutput`. That raw model output is then passed through the
deterministic safety gates (confidence floors + the critical-priority
human-approval rule) and persisted both as a ``structured_result`` on the
``agent_runs`` row (agent="verify_repair") and as a dedicated
``work_order_verifications`` row — where it is ultimately readable (and, for
staff, reviewable) through the work-order API.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    AgentStatus,
    VerificationReviewDecision,
    VerificationStatus,
)


class AiVerificationStatus(enum.StrEnum):
    """UI-facing state of an AI repair-verification attempt.

    Deliberately separates *analysis outcomes* from *provider availability* so
    the officer UI can distinguish "the evidence failed verification" from "the
    AI provider is temporarily unavailable / rate limited". States:

    * ``NOT_STARTED`` — no run has been attempted.
    * ``PROCESSING`` — a run is in flight (used by clients rendering async state).
    * ``COMPLETED`` — the model produced a verdict; a verification row exists.
    * ``PROVIDER_RATE_LIMITED`` — Groq returned 429; retryable, evidence intact.
    * ``PROVIDER_UNAVAILABLE`` — timeout / connection / config; retryable.
    * ``INVALID_EVIDENCE`` — BEFORE/AFTER evidence is missing or unreadable.
    * ``ANALYSIS_FAILED`` — the provider responded but analysis could not finish.
    """

    NOT_STARTED = "NOT_STARTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


class VerificationInput(BaseModel):
    """Signal the resolution-verification agent reasons over.

    ``before_key`` / ``after_key`` are the object-storage keys (not raw bytes) of
    the work order's BEFORE / AFTER evidence photos; ``before_photo_id`` /
    ``after_photo_id`` let the persist node link the verification to the exact
    photo rows. ``priority_bucket`` (e.g. "P1_CRITICAL") drives the configured
    critical human-approval rule.
    """

    complaint_description: str = Field(min_length=1, max_length=4000)
    # The complaint's reported category (used only as hint context).
    category: str | None = Field(default=None, max_length=64)
    before_key: str | None = Field(default=None, max_length=512)
    after_key: str | None = Field(default=None, max_length=512)
    before_photo_id: uuid.UUID | None = None
    after_photo_id: uuid.UUID | None = None
    # Work-order priority bucket ("P1_CRITICAL" .. "P4_LOW") for the safety gate.
    priority_bucket: str | None = Field(default=None, max_length=16)
    # The field worker's completion notes (advisory signal the model considers
    # alongside the photos when judging whether the reported issue is resolved).
    completion_notes: str | None = Field(default=None, max_length=2000)
    # Storage key of the original complaint photo (if the citizen attached one) so
    # the model can compare the reported condition against the repair evidence.
    original_complaint_key: str | None = Field(default=None, max_length=512)


class VerificationOutput(BaseModel):
    """The validated structured result produced by the model (pre-enforcement).

    ``verification_status`` is the model's raw verdict; the agent's validate node
    MAY override it to NEEDS_HUMAN_REVIEW when the configured confidence /
    critical-priority gates demand human sign-off. ``repair_evidence`` describes
    what the model observed that supports the fix; ``remaining_issue`` describes
    anything still unresolved.
    """

    repair_evidence: str = Field(default="", max_length=700)
    remaining_issue: str = Field(default="", max_length=700)
    # 0..1 confidence in the verdict.
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    verification_status: VerificationStatus = VerificationStatus.NEEDS_HUMAN_REVIEW
    # True when the after photo still shows the reported issue (NOT_RESOLVED).
    issue_fixed: bool = False
    # The model may itself flag a human-review requirement (e.g. ambiguous scene).
    human_review_required: bool = False

    @field_validator("verification_status", mode="before")
    @classmethod
    def _coerce_status(cls, value: object) -> object:
        """Normalize the model's free-form verdict into a canonical enum member.

        Multimodal models frequently paraphrase the verdict (for example
        ``"NOT_VERIFIED"``, ``"RESOLVED"``, ``"PARTIAL"`` or ``"UNKNOWN"``)
        instead of emitting our exact enum strings. Coerce the common variants
        here so a near-miss verdict is interpreted toward the closest canonical
        state instead of failing validation (which would otherwise route the run
        to an opaque fallback); genuinely unknown values stay NEEDS_HUMAN_REVIEW.
        """
        if isinstance(value, VerificationStatus):
            return value
        key = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
        normalized = {
            "VERIFIED": VerificationStatus.VERIFIED,
            "RESOLVED": VerificationStatus.VERIFIED,
            "FIXED": VerificationStatus.VERIFIED,
            "REPAIRED": VerificationStatus.VERIFIED,
            "COMPLETE": VerificationStatus.VERIFIED,
            "COMPLETED": VerificationStatus.VERIFIED,
            "YES": VerificationStatus.VERIFIED,
            "PARTIALLY_RESOLVED": VerificationStatus.PARTIALLY_RESOLVED,
            "PARTIALLY": VerificationStatus.PARTIALLY_RESOLVED,
            "PARTIAL": VerificationStatus.PARTIALLY_RESOLVED,
            "SOMEWHAT_RESOLVED": VerificationStatus.PARTIALLY_RESOLVED,
            "NOT_RESOLVED": VerificationStatus.NOT_RESOLVED,
            "NOT_VERIFIED": VerificationStatus.NOT_RESOLVED,
            "UNRESOLVED": VerificationStatus.NOT_RESOLVED,
            "FAILED": VerificationStatus.NOT_RESOLVED,
            "NO_FIX": VerificationStatus.NOT_RESOLVED,
            "NOT_FIXED": VerificationStatus.NOT_RESOLVED,
            "NO": VerificationStatus.NOT_RESOLVED,
            "NEEDS_HUMAN_REVIEW": VerificationStatus.NEEDS_HUMAN_REVIEW,
            "UNCLEAR": VerificationStatus.NEEDS_HUMAN_REVIEW,
            "UNKNOWN": VerificationStatus.NEEDS_HUMAN_REVIEW,
            "INCONCLUSIVE": VerificationStatus.NEEDS_HUMAN_REVIEW,
            "AMBIGUOUS": VerificationStatus.NEEDS_HUMAN_REVIEW,
        }
        if key in normalized:
            return normalized[key]
        try:
            return VerificationStatus(key)
        except ValueError:
            return VerificationStatus.NEEDS_HUMAN_REVIEW


class WorkOrderVerificationOut(BaseModel):
    """A persisted verification as exposed by the work-order API.

    ``before_url`` / ``after_url`` are resolved object-storage URLs so the UI can
    render the required side-by-side comparison without a second request.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    work_order_id: uuid.UUID
    complaint_id: uuid.UUID
    before_photo_id: uuid.UUID | None = None
    after_photo_id: uuid.UUID | None = None
    before_url: str = ""
    after_url: str = ""
    repair_evidence: str | None = None
    remaining_issue: str | None = None
    confidence: float = 0.0
    verification_status: VerificationStatus
    human_review_required: bool = True
    source: str = "groq"
    reviewed_by: uuid.UUID | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    created_at: datetime


class VerificationRunResponse(BaseModel):
    """Response envelope for running (or fetching) constraint verification.

    ``ai_status`` distinguishes a failed analysis from a temporarily unavailable
    provider (rate limit / outage): a provider failure is retryable and does NOT
    mean the evidence was rejected. ``message`` is a user-safe explanation;
    ``retry_after_seconds`` carries the provider's ``Retry-After`` hint when one
    was returned. The technical ``error`` is a short sanitized reason — internal
    request IDs stay in the persisted agent run, not in this response.
    """

    run_id: uuid.UUID
    status: AgentStatus
    result: WorkOrderVerificationOut | None = None
    error: str | None = None
    retry_allowed: bool = True
    ai_status: AiVerificationStatus = AiVerificationStatus.NOT_STARTED
    message: str | None = None
    retry_after_seconds: float | None = None


class VerificationReviewIn(BaseModel):
    """An authorized human's decision on a verification that needs review.

    ``CONFIRM_VERIFIED`` certifies the repair is complete; ``REQUIRES_FOLLOWUP``
    rejects it and reopens the work order so the worker returns;
    ``REQUEST_REWORK`` rejects the submitted evidence and moves the order to
    ``RETURNED_FOR_REWORK`` so the worker performs the required fixes and
    re-submits fresh evidence.
    """

    decision: VerificationReviewDecision
    note: str | None = Field(default=None, max_length=1000)


class VerificationReviewOut(BaseModel):
    """The result of a human review: the (updated) verification + order status."""

    verification: WorkOrderVerificationOut
    work_order_status: str
    reopened: bool = False
    # True when the review moved the order to RETURNED_FOR_REWORK; the worker is
    # expected to redo the work (fresh GPS check-in + START_REWORK) and re-submit.
    rework_requested: bool = False


class EvidencePhotoOut(BaseModel):
    """A work-order evidence photo as exposed in the resolution-review bundle."""

    id: uuid.UUID
    category: str
    url: str = ""
    original_filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    created_at: datetime
    uploaded_by_name: str | None = None


class ComplaintMediaOut(BaseModel):
    """A citizen-attached complaint media asset (photo/video) for comparison."""

    id: uuid.UUID
    media_type: str
    url: str = ""
    original_filename: str = ""
    content_type: str = ""
    created_at: datetime


class WorkOrderEvidenceOut(BaseModel):
    """The full resolution-review bundle an officer needs to verify a repair.

    Pairs the work-order details (worker, completion timestamps, notes), the
    original complaint (title / description / attached media) and the field
    worker's BEFORE / AFTER evidence photos — all with resolved URLs — so the
    officer can compare the original issue against the actual repair without a
    second request.
    """

    order_id: uuid.UUID
    order_status: str
    complaint_id: uuid.UUID
    complaint_title: str | None = None
    complaint_description: str | None = None
    complaint_category: str | None = None
    complaint_media: list[ComplaintMediaOut] = []
    worker_id: uuid.UUID | None = None
    worker_name: str | None = None
    completed_at: datetime | None = None
    evidence_submitted_at: datetime | None = None
    completion_notes: str | None = None
    before_photos: list[EvidencePhotoOut] = []
    after_photos: list[EvidencePhotoOut] = []


__all__ = [
    "AiVerificationStatus",
    "ComplaintMediaOut",
    "EvidencePhotoOut",
    "VerificationInput",
    "VerificationOutput",
    "VerificationReviewIn",
    "VerificationReviewOut",
    "VerificationRunResponse",
    "WorkOrderEvidenceOut",
    "WorkOrderVerificationOut",
]
