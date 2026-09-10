"""AI Governance & Evidence API (Part 28).

Exposes AI decision logs, evidence cross-checks, human overrides and a
governance summary per complaint. Read access is granted to staff roles
(OFFICER / ADMIN / WARD_REPRESENTATIVE) and SUPER_ADMIN; overrides may be
recorded by officers/admins.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import (
    AIDecisionLog,
    Complaint,
    EvidenceCheck,
    HumanOverride,
    User,
)
from app.schemas.governance import (
    AIDecisionOut,
    EvidenceCheckOut,
    GovernanceSummary,
    OverrideIn,
    OverrideOut,
)
from app.services import override_service
from app.services.ai_governance_service import get_ai_decision, list_ai_decisions
from app.services.audit_service import (
    ACTION_DEPARTMENT_OVERRIDE,
    ACTION_PRIORITY_OVERRIDE,
    ACTION_ROUTING_OVERRIDE,
    record_audit,
)
from app.services.complaint_tracking_service import user_can_view
from app.services.evidence_validation_service import list_evidence_checks

router = APIRouter(prefix="/governance", tags=["governance"])

_STAFF = Depends(require_roles("OFFICER", "ADMIN", "SUPER_ADMIN", "WARD_REPRESENTATIVE"))
# Recording a human override of an AI decision is an officer/admin-only action.
_OVERRIDE_WRITERS = Depends(require_roles("OFFICER", "ADMIN", "SUPER_ADMIN"))


async def _get_complaint_or_404(
    db: AsyncSession, complaint_id: uuid.UUID, user: User
) -> Complaint:
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found.")
    if not user_can_view(user, complaint):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have permission to access this complaint."
        )
    return complaint


def _decision_summary(decision: AIDecisionLog | None) -> str | None:
    """Best-effort human string describing a stored AI decision."""
    if decision is None:
        return None
    if decision.output_summary:
        return decision.output_summary
    if isinstance(decision.result, dict):
        for key in ("recommended_action", "summary", "action"):
            value = decision.result.get(key) or decision.result.get(key.upper())
            if value:
                return str(value)
    return None


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/complaints/{complaint_id}/decisions", response_model=list[AIDecisionOut])
async def get_complaint_decisions(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = _STAFF,
):
    await _get_complaint_or_404(db, complaint_id, user)
    return await list_ai_decisions(db, complaint_id=complaint_id)


@router.get("/complaints/{complaint_id}/evidence", response_model=list[EvidenceCheckOut])
async def get_complaint_evidence(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = _STAFF,
):
    await _get_complaint_or_404(db, complaint_id, user)
    return await list_evidence_checks(db, complaint_id=complaint_id)


@router.get("/complaints/{complaint_id}/overrides", response_model=list[OverrideOut])
async def get_complaint_overrides(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = _STAFF,
):
    await _get_complaint_or_404(db, complaint_id, user)
    return await override_service.list_overrides(db, complaint_id=complaint_id)


@router.post(
    "/complaints/{complaint_id}/overrides",
    response_model=OverrideOut,
    status_code=201,
)
async def create_override(
    complaint_id: uuid.UUID,
    payload: OverrideIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = _OVERRIDE_WRITERS,
):
    """Record a human override of an AI decision (officer/admin only)."""
    await _get_complaint_or_404(db, complaint_id, user)

    decision: AIDecisionLog | None = None
    if payload.decision_id is not None:
        decision = await get_ai_decision(db, payload.decision_id)
        if decision is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "AI decision not found.")
        if decision.complaint_id is not None and decision.complaint_id != complaint_id:
            raise HTTPException(400, "Decision does not belong to this complaint.")

    override = await override_service.record_override(
        db,
        complaint_id=complaint_id,
        override_type=payload.override_type,
        original_value=payload.original_value or _decision_summary(decision),
        new_value=payload.new_value,
        reason=payload.reason,
        user_id=user.id,
        decision_id=payload.decision_id,
    )
    if decision is not None:
        decision.is_override = True

    action = ACTION_ROUTING_OVERRIDE
    if payload.override_type == "priority":
        action = ACTION_PRIORITY_OVERRIDE
    if payload.override_type == "department":
        action = ACTION_DEPARTMENT_OVERRIDE
    await record_audit(
        db,
        actor_id=user.id,
        action=action,
        entity_type="complaint",
        entity_id=str(complaint_id),
        after={
            "override_type": payload.override_type,
            "reason": payload.reason,
        },
        ip_address=_client_ip(request),
    )
    await db.commit()
    await db.refresh(override)
    return override


@router.get("/complaints/{complaint_id}/summary", response_model=GovernanceSummary)
async def get_governance_summary(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = _STAFF,
):
    await _get_complaint_or_404(db, complaint_id, user)

    decision_count = (
        await db.execute(
            select(func.count(AIDecisionLog.id)).where(
                AIDecisionLog.complaint_id == complaint_id
            )
        )
    ).scalar_one()
    evidence_count = (
        await db.execute(
            select(func.count(EvidenceCheck.id)).where(
                EvidenceCheck.complaint_id == complaint_id
            )
        )
    ).scalar_one()
    override_count = (
        await db.execute(
            select(func.count(HumanOverride.id)).where(
                HumanOverride.complaint_id == complaint_id
            )
        )
    ).scalar_one()
    mismatch_count = (
        await db.execute(
            select(func.count(EvidenceCheck.id)).where(
                EvidenceCheck.complaint_id == complaint_id,
                EvidenceCheck.is_match.is_(False),
            )
        )
    ).scalar_one()

    return GovernanceSummary(
        complaint_id=complaint_id,
        decision_count=decision_count,
        evidence_check_count=evidence_count,
        override_count=override_count,
        has_mismatches=mismatch_count > 0,
    )
