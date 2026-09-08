"""Service facade for the AI Evidence Verification (Vision) Agent (Part 8).

Wraps ``VisionAgent`` with complaint access enforcement (only an authenticated
user who may view the complaint can trigger or read its verification), reads the
stored image keys for the complaint, and returns serializable run data so the
route stays thin and free of direct DB plumbing.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.vision_agent import AGENT_NAME, VisionAgent
from app.core.config import get_settings
from app.models import AgentRun, ComplaintMedia, User
from app.models.enums import MediaType
from app.schemas.vision import VisionInput, VisionOutput, VisionRunOut, VisionRunResponse
from app.services import agent_run_service
from app.services.ai_governance_service import PROMPT_VERSION_VISION, log_ai_decision
from app.services.ai_service import get_ai_service
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
    _load_complaint,
    user_can_view,
)
from app.services.evidence_validation_service import record_evidence_check


class VisionNotFoundError(ComplaintNotFoundError):
    """Raised when a complaint does not exist (mirrors tracking semantics)."""


class VisionAccessError(ComplaintAccessError):
    """Raised when the authenticated user cannot access a complaint."""


async def _assert_can_view(db: AsyncSession, user: User, complaint_id: uuid.UUID) -> None:
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise VisionNotFoundError
    if not user_can_view(user, complaint):
        raise VisionAccessError


def _agent() -> VisionAgent:
    return VisionAgent(settings=get_settings(), ai=get_ai_service())


async def _image_keys(db: AsyncSession, complaint_id: uuid.UUID) -> list[str]:
    """Return the storage keys of the complaint's attached images (in order)."""
    result = await db.execute(
        select(ComplaintMedia.storage_key)
        .where(
            ComplaintMedia.complaint_id == complaint_id,
            ComplaintMedia.media_type == MediaType.IMAGE,
        )
        .order_by(ComplaintMedia.created_at)
    )
    return list(result.scalars().all())


async def run_vision(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
) -> VisionRunResponse:
    """Run the vision evidence-verification graph for a complaint."""
    await _assert_can_view(db, user, complaint_id)
    complaint = await _load_complaint(db, complaint_id)
    keys = await _image_keys(db, complaint_id)
    input_data = VisionInput(
        description=complaint.description or complaint.title,
        category=complaint.category.value if complaint.category else None,
        image_keys=keys,
    )
    run: AgentRun = await _agent().run(
        db,
        complaint_id=complaint_id,
        input_data=input_data,
    )
    await db.refresh(run)
    result = (
        VisionOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    if result is not None:
        await _log_vision_governance(db, run, input_data, result)
    return VisionRunResponse(
        run_id=run.id,
        status=run.status,
        result=result,
        error=run.error,
        retry_allowed=True,
    )


async def _log_vision_governance(
    db: AsyncSession,
    run: AgentRun,
    input_data: VisionInput,
    result: VisionOutput,
) -> None:
    """Part 28 — persist the vision decision + visual-evidence cross-check."""
    decision = await log_ai_decision(
        db,
        complaint_id=run.complaint_id,
        agent_name=AGENT_NAME,
        model_name=run.model or "unconfigured",
        prompt_version=PROMPT_VERSION_VISION,
        input_summary=(input_data.description or "")[:500] or None,
        output_summary=result.evidence_description,
        confidence=result.confidence,
        result=result.model_dump(mode="json"),
    )
    await record_evidence_check(
        db,
        complaint_id=run.complaint_id,
        decision_id=decision.id,
        claim_type="visual_evidence",
        claimed_value="requested",
        actual_value=result.detected_issue or "no_evidence",
        source="vision",
        is_match=not result.mismatch_detected,
        discrepancy_pct=100.0 if result.mismatch_detected else 0.0,
        evidence_data={
            "detected_issue": result.detected_issue,
            "severity": result.severity.value,
            "human_review_required": result.human_review_required,
        },
        notes=(
            "Images appear unrelated to the reported complaint."
            if result.mismatch_detected
            else None
        ),
    )


async def get_vision_result(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> VisionRunOut | None:
    """Return the most recent vision run for a complaint, if any."""
    await _assert_can_view(db, user, complaint_id)
    run = await agent_run_service.get_latest_run(db, complaint_id)
    if run is None or run.agent != AGENT_NAME:
        return None
    result: VisionOutput | None = (
        VisionOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return VisionRunOut(
        id=run.id,
        complaint_id=run.complaint_id,
        agent=run.agent,
        model=run.model,
        status=run.status,
        duration_ms=run.duration_ms,
        structured_result=result,
        error=run.error,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )
