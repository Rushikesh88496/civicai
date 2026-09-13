"""Service facade for the AI Resolution Verification (Part 19).

Wraps ``VerifyRepairAgent`` with authorization enforcement:

* **Run** — only authorized staff (OFFICER / ADMIN / WARD_REPRESENTATIVE) may
  trigger verification, on a work order whose resolution evidence has been
  submitted (``EVIDENCE_SUBMITTED``) or one already marked ``COMPLETED``.
* **View** — staff may view any verification; the assigned field worker may view
  their own order's result; the complaint owner may see it too (they are the
  ones the resolution is for).
* **Review** — only staff may take the human-approval actions:
  ``CONFIRM_VERIFIED`` (certify the repair) or ``REQUIRES_FOLLOWUP`` (reopen the
  work order so the worker returns and the complaint goes back IN_PROGRESS).

The field worker never resolves the complaint (Part 28): finishing the physical
work only moves the order to ``WORK_COMPLETED`` and submitting evidence to
``EVIDENCE_SUBMITTED``. The complaint is marked ``RESOLVED`` — and the order
``COMPLETED`` — only when an authorized officer (or admin / ward rep) reviews
the verification (Part 30): the AI verdict is advisory and never auto-resolves;
the officer's final decision certifies the resolution.

The service keeps the route thin: it resolves the BEFORE/AFTER photo storage
keys + ids, builds the :class:`VerificationInput` (enriched with the worker's
completion notes and the original complaint photo), delegates to the agent and
serializes the dedicated ``work_order_verifications`` row.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.verify_repair_agent import (
    FATAL_REASON_ANALYSIS,
    FATAL_REASON_EVIDENCE,
    FATAL_REASON_RATE_LIMIT,
    FATAL_REASON_UNAVAILABLE,
    VerifyRepairAgent,
)
from app.core.config import get_settings
from app.core.notification_types import (
    EVENT_AI_VERIFICATION_RESULT,
    EVENT_HUMAN_REVIEW,
    EVENT_RESOLVED,
    EVENT_REWORK_REQUESTED,
    EVENT_WORK_ORDER_REOPENED,
    EVENT_WORK_RESOLVED,
)
from app.models import (
    Complaint,
    ComplaintMedia,
    FieldWorker,
    Role,
    User,
    WorkOrder,
    WorkOrderPhoto,
    WorkOrderStatusHistory,
    WorkOrderVerification,
)
from app.models.enums import (
    AgentStatus,
    ComplaintStatus,
    MediaType,
    RoleName,
    VerificationReviewDecision,
    VerificationStatus,
    WorkOrderAction,
    WorkOrderStatus,
)
from app.schemas.verification import (
    AiVerificationStatus,
    ComplaintMediaOut,
    EvidencePhotoOut,
    VerificationInput,
    VerificationReviewOut,
    VerificationRunResponse,
    WorkOrderEvidenceOut,
    WorkOrderVerificationOut,
)
from app.services import notification_service
from app.services.ai_service import get_ai_service
from app.services.audit_service import (
    ACTION_WORK_ORDER_EVIDENCE_VIEWED,
    ACTION_WORK_ORDER_REOPENED,
    ACTION_WORK_ORDER_RESOLUTION_CONFIRMED,
    ACTION_WORK_ORDER_REWORK_REQUESTED,
    ACTION_WORK_ORDER_VERIFICATION_COMPLETED,
    ACTION_WORK_ORDER_VERIFICATION_STARTED,
    record_audit,
)
from app.services.complaint_service import record_status_transition
from app.services.complaint_tracking_service import user_can_view
from app.storage import get_storage

_STAFF_ROLES = (
    RoleName.OFFICER.value,
    RoleName.ADMIN.value,
    RoleName.WARD_REPRESENTATIVE.value,
)

# User-safe explanations keyed by the agent's fatal-reason tag. A provider
# failure never means "the repair failed verification" — evidence stays intact
# and the analysis is simply retryable.
_AI_MESSAGES: dict[str, str] = {
    FATAL_REASON_RATE_LIMIT: (
        "AI verification is temporarily unavailable. Groq is temporarily rate "
        "limited — your evidence has NOT been rejected. Please retry verification."
    ),
    FATAL_REASON_UNAVAILABLE: (
        "AI verification is temporarily unavailable. The AI provider could not be "
        "reached — your evidence has NOT been rejected. Please try again."
    ),
    FATAL_REASON_EVIDENCE: (
        "AI verification could not be completed because the resolution evidence is "
        "missing or invalid."
    ),
    FATAL_REASON_ANALYSIS: (
        "AI verification could not be completed. No verdict was produced — please "
        "retry verification."
    ),
}

# Optimistic tag → status fallback; anything unrecognized is a plain analysis failure.
_AI_STATUS_BY_REASON: dict[str, AiVerificationStatus] = {
    FATAL_REASON_RATE_LIMIT: AiVerificationStatus.PROVIDER_RATE_LIMITED,
    FATAL_REASON_UNAVAILABLE: AiVerificationStatus.PROVIDER_UNAVAILABLE,
    FATAL_REASON_EVIDENCE: AiVerificationStatus.INVALID_EVIDENCE,
    FATAL_REASON_ANALYSIS: AiVerificationStatus.ANALYSIS_FAILED,
}

_REQUEST_ID_IN_ERROR = re.compile(r"\(request [0-9a-f-]{36}\)")


def _sanitize_technical_error(error: str | None) -> str | None:
    """Strip internal request IDs from a technical message before it reaches the UI."""
    if not error:
        return error
    cleaned = _REQUEST_ID_IN_ERROR.sub("(internal)", error).strip()
    return cleaned[:400] or None


def _failure_meta(run: Any) -> tuple[AiVerificationStatus, str, float | None]:
    """Classify a FAILED verify run from its persisted trace events.

    Reads the agent's ``validate.provider_failed`` event (which carries the
    reason tag + the provider's ``Retry-After`` hint). Falls back to a plain
    analysis-failure classification when the reason is not recoverable so the
    API always responds with a structured, user-safe outcome.
    """
    reason: str | None = None
    retry_after: float | None = None
    for event in getattr(run, "events", []) or []:
        if getattr(event, "event", None) != "validate.provider_failed":
            continue
        payload = getattr(event, "payload", None) or {}
        if isinstance(payload, dict):
            reason = payload.get("reason") or reason
            retry_after = payload.get("retry_after_seconds") or retry_after

    key = (
        reason
        if reason in _AI_STATUS_BY_REASON
        else FATAL_REASON_ANALYSIS
    )
    return (
        _AI_STATUS_BY_REASON[key],
        _AI_MESSAGES[key],
        _coerce_retry_after(retry_after),
    )


def _coerce_retry_after(value: object) -> float | None:
    try:
        if isinstance(value, (int, float)):
            return max(0.0, float(value))
    except Exception:  # noqa: BLE001 - best-effort hint only
        return None
    return None


class VerifyNotFoundError(Exception):
    """Raised when a work order does not exist (404, never leaks internals)."""


class VerifyAccessError(Exception):
    """Raised when the authenticated user may not run/view/review this order."""


class VerifyStateError(Exception):
    """Raised when a verification action is illegal for the current state."""


class VerifyEvidenceError(Exception):
    """Raised when resolution evidence is missing (422, a validation failure)."""


async def _load_order(db: AsyncSession, order_id: uuid.UUID) -> WorkOrder | None:
    return await db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == order_id)
        .execution_options(populate_existing=True)
        .options(
            selectinload(WorkOrder.complaint),
            selectinload(WorkOrder.worker).selectinload(FieldWorker.user),
        )
    )


def _is_staff(user: User) -> bool:
    return user.role.name in _STAFF_ROLES


async def _require_staff(user: User) -> None:
    if not _is_staff(user):
        raise VerifyAccessError("You do not have permission to perform this action.")


async def _assert_can_view(db: AsyncSession, user: User, order: WorkOrder) -> None:
    """Staff may view; the assigned worker may too.

    Citizens do NOT see verification payloads (confidence, review notes, officer
    decisions). They follow resolution through the citizen-safe complaint
    timeline, which surfaces only status milestones + citizen-facing notes.
    """
    if _is_staff(user):
        complaint = order.complaint
        if complaint is None:
            complaint = await db.get(Complaint, order.complaint_id)
        if complaint is not None and not user_can_view(user, complaint):
            raise VerifyAccessError("You do not have permission to view this verification.")
        return
    if user.role.name == RoleName.FIELD_WORKER.value and order.worker_id is not None:
        worker = await db.scalar(select(FieldWorker).where(FieldWorker.user_id == user.id))
        if worker is not None and worker.id == order.worker_id:
            return
    raise VerifyAccessError("You do not have permission to view this verification.")


async def _load_photos(
    db: AsyncSession, order_id: uuid.UUID
) -> tuple[WorkOrderPhoto | None, WorkOrderPhoto | None]:
    """Return the newest allowed BEFORE / AFTER photo for a work order."""
    result = await db.execute(
        select(WorkOrderPhoto)
        .where(WorkOrderPhoto.work_order_id == order_id, WorkOrderPhoto.allowed.is_(True))
        .order_by(WorkOrderPhoto.created_at)
    )
    photos = list(result.scalars().all())
    before = next((p for p in reversed(photos) if p.category == "BEFORE"), None)
    after = next((p for p in reversed(photos) if p.category == "AFTER"), None)
    return before, after


def _to_out(verification: WorkOrderVerification) -> WorkOrderVerificationOut:
    """Serialize a verification row with resolved photo URLs + reviewer name."""
    reviewer_name = None
    if verification.reviewed_by_user is not None:
        reviewer_name = verification.reviewed_by_user.full_name
    return WorkOrderVerificationOut(
        id=verification.id,
        work_order_id=verification.work_order_id,
        complaint_id=verification.complaint_id,
        before_photo_id=verification.before_photo_id,
        after_photo_id=verification.after_photo_id,
        before_url=(
            get_storage().url(verification.before_photo.storage_key)
            if verification.before_photo is not None
            else ""
        ),
        after_url=(
            get_storage().url(verification.after_photo.storage_key)
            if verification.after_photo is not None
            else ""
        ),
        repair_evidence=verification.repair_evidence,
        remaining_issue=verification.remaining_issue,
        confidence=verification.confidence,
        verification_status=verification.verification_status,
        human_review_required=verification.human_review_required,
        source=verification.source,
        reviewed_by=verification.reviewed_by,
        reviewed_by_name=reviewer_name,
        reviewed_at=verification.reviewed_at,
        review_note=verification.review_note,
        created_at=verification.created_at,
    )


async def _latest_verification(
    db: AsyncSession, order_id: uuid.UUID
) -> WorkOrderVerification | None:
    return await db.scalar(
        select(WorkOrderVerification)
        .where(WorkOrderVerification.work_order_id == order_id)
        .options(
            selectinload(WorkOrderVerification.before_photo),
            selectinload(WorkOrderVerification.after_photo),
            selectinload(WorkOrderVerification.reviewed_by_user),
        )
        .order_by(WorkOrderVerification.created_at.desc())
        .limit(1)
    )


async def _record_verification_audit(
    db: AsyncSession,
    actor: User,
    action: str,
    order_id: uuid.UUID,
    after: dict | None = None,
    *,
    note: str | None = None,
) -> None:
    """Append a resolution-verification audit event (Part 30) for the officer trail."""
    details: dict = dict(after or {})
    details["actor_role"] = actor.role.name if actor.role is not None else None
    if note:
        details["note"] = note
    await record_audit(
        db,
        actor_id=actor.id,
        action=action,
        entity_type="work_order",
        entity_id=str(order_id),
        after=details,
    )


async def _latest_complaint_image_key(db: AsyncSession, complaint: Complaint | None) -> str | None:
    """The storage key of the newest IMAGE attached to the complaint (if any)."""
    if complaint is None:
        return None
    media = await db.scalar(
        select(ComplaintMedia)
        .where(
            ComplaintMedia.complaint_id == complaint.id,
            ComplaintMedia.media_type == MediaType.IMAGE,
        )
        .order_by(ComplaintMedia.created_at.desc())
        .limit(1)
    )
    return media.storage_key if media is not None else None


def _evidence_photo_out(photo: WorkOrderPhoto) -> EvidencePhotoOut:
    return EvidencePhotoOut(
        id=photo.id,
        category=photo.category,
        url=get_storage().url(photo.storage_key),
        original_filename=photo.original_filename,
        content_type=photo.content_type,
        size_bytes=photo.size_bytes,
        created_at=photo.created_at,
        uploaded_by_name=(
            photo.worker.user.full_name
            if photo.worker is not None and photo.worker.user is not None
            else None
        ),
    )


def _complaint_media_out(media: ComplaintMedia) -> ComplaintMediaOut:
    return ComplaintMediaOut(
        id=media.id,
        media_type=media.media_type.value,
        url=get_storage().url(media.storage_key),
        original_filename=media.original_filename,
        content_type=media.content_type,
        created_at=media.created_at,
    )


async def _load_order_with_photographer(db: AsyncSession, order_id: uuid.UUID) -> WorkOrder | None:
    """Load an order with complaint (+media) and photos (with uploader) eagerly."""
    return await db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == order_id)
        .execution_options(populate_existing=True)
        .options(
            selectinload(WorkOrder.complaint).selectinload(Complaint.media),
            selectinload(WorkOrder.worker).selectinload(FieldWorker.user),
            selectinload(WorkOrder.photos)
            .selectinload(WorkOrderPhoto.worker)
            .selectinload(FieldWorker.user),
        )
    )


async def get_work_order_evidence(
    db: AsyncSession, user: User, order_id: uuid.UUID
) -> WorkOrderEvidenceOut:
    """Return the full resolution-review bundle for an officer (Part 30).

    Staff only: pairs the work-order details (worker, completion timestamps,
    completion notes), the original complaint (title / description / attached
    media) and the field worker's BEFORE / AFTER photo evidence — everything an
    officer needs to complete the review. Every staff view is audited.
    """
    await _require_staff(user)
    order = await _load_order_with_photographer(db, order_id)
    if order is None:
        raise VerifyNotFoundError("Work order not found.")
    await _assert_can_view(db, user, order)

    complaint: Complaint | None = order.complaint
    worker_name = (
        order.worker.user.full_name
        if order.worker is not None and order.worker.user is not None
        else None
    )
    photos = sorted(order.photos, key=lambda p: p.created_at)
    before = [p for p in photos if p.category == "BEFORE"]
    after = [p for p in photos if p.category == "AFTER"]

    await _record_verification_audit(
        db,
        user,
        ACTION_WORK_ORDER_EVIDENCE_VIEWED,
        order.id,
        {"order_status": str(order.status), "viewer_role": user.role.name if user.role else None},
    )
    await db.commit()

    return WorkOrderEvidenceOut(
        order_id=order.id,
        order_status=order.status,
        complaint_id=order.complaint_id,
        complaint_title=complaint.title if complaint is not None else None,
        complaint_description=complaint.description if complaint is not None else None,
        complaint_category=(
            complaint.category.value if complaint is not None and complaint.category else None
        ),
        complaint_media=[_complaint_media_out(m) for m in (complaint.media if complaint else [])],
        worker_id=order.worker_id,
        worker_name=worker_name,
        completed_at=order.completed_at,
        evidence_submitted_at=order.evidence_submitted_at,
        completion_notes=order.worker_notes,
        before_photos=[_evidence_photo_out(p) for p in before],
        after_photos=[_evidence_photo_out(p) for p in after],
    )


def _agent() -> VerifyRepairAgent:
    return VerifyRepairAgent(settings=get_settings(), ai=get_ai_service())


async def run_verification(
    db: AsyncSession, user: User, order_id: uuid.UUID
) -> VerificationRunResponse:
    """Run the resolution-verification agent (staff).

    Allowed once a work order's resolution evidence has been submitted
    (``EVIDENCE_SUBMITTED``) or the order is already ``COMPLETED``. Both a
    BEFORE and an AFTER photo are required (validation failure, 422). The AI
    verdict is advisory only — it never resolves the complaint or completes the
    order; an authorized officer makes that call via ``review_verification``.
    """
    await _require_staff(user)
    order = await _load_order(db, order_id)
    if order is None:
        raise VerifyNotFoundError("Work order not found.")
    await _assert_can_view(db, user, order)
    if order.status not in (
        WorkOrderStatus.EVIDENCE_SUBMITTED,
        WorkOrderStatus.COMPLETED,
    ):
        raise VerifyStateError(
            "Repair verification can only be run once the resolution evidence has been submitted."
        )

    before, after = await _load_photos(db, order_id)
    if before is None:
        raise VerifyEvidenceError("Before photo is required.")
    if after is None:
        raise VerifyEvidenceError("After photo is required.")

    complaint: Complaint | None = order.complaint
    input_data = VerificationInput(
        complaint_description=(complaint.description or complaint.title if complaint else ""),
        category=complaint.category.value if complaint and complaint.category else None,
        before_key=before.storage_key,
        after_key=after.storage_key,
        before_photo_id=before.id,
        after_photo_id=after.id,
        priority_bucket=order.priority,
        completion_notes=order.worker_notes,
        original_complaint_key=await _latest_complaint_image_key(db, complaint),
    )

    await _record_verification_audit(
        db,
        user,
        ACTION_WORK_ORDER_VERIFICATION_STARTED,
        order.id,
        {"order_status": str(order.status), "source": "groq"},
    )
    await db.commit()

    run = await _agent().run(
        db,
        work_order_id=order.id,
        complaint_id=order.complaint_id,
        input_data=input_data,
    )
    if run.status == AgentStatus.FAILED:
        ai_status, message, retry_after = _failure_meta(run)
        return VerificationRunResponse(
            run_id=run.id,
            status=run.status,
            result=None,
            error=_sanitize_technical_error(run.error),
            retry_allowed=True,
            ai_status=ai_status,
            message=message,
            retry_after_seconds=retry_after,
        )
    verification = await _latest_verification(db, order_id)
    if verification is not None:
        await _notify_ai_result(db, order, verification)
    if verification is not None and verification.human_review_required:
        await _notify_human_review(db, order, verification)
    if verification is not None:
        # Part 30: the AI verdict never auto-resolves — the officer makes the
        # final decision. The verification result is advisory + always reviewable.
        await _record_verification_audit(
            db,
            user,
            ACTION_WORK_ORDER_VERIFICATION_COMPLETED,
            order.id,
            {
                "verification_status": str(verification.verification_status),
                "confidence": verification.confidence,
                "human_review_required": verification.human_review_required,
                "source": verification.source,
            },
        )
        await db.commit()
    return VerificationRunResponse(
        run_id=run.id,
        status=run.status,
        result=_to_out(verification) if verification is not None else None,
        error=None,
        retry_allowed=True,
        ai_status=AiVerificationStatus.COMPLETED,
    )


async def get_verification(
    db: AsyncSession, user: User, order_id: uuid.UUID
) -> WorkOrderVerificationOut | None:
    """Return the latest verification for a work order (staff / worker / owner)."""
    order = await _load_order(db, order_id)
    if order is None:
        raise VerifyNotFoundError("Work order not found.")
    await _assert_can_view(db, user, order)
    verification = await _latest_verification(db, order_id)
    return _to_out(verification) if verification is not None else None


async def review_verification(
    db: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    *,
    decision: VerificationReviewDecision,
    note: str | None,
) -> VerificationReviewOut:
    """Authorized-human review of a verification (staff only).

    ``CONFIRM_VERIFIED`` certifies the repair: the complaint is marked RESOLVED
    and the order COMPLETED (the field worker can previously only have moved it
    to EVIDENCE_SUBMITTED).
    ``REQUIRES_FOLLOWUP`` rejects the outcome and reopens the work order so the
    field worker can return (COMPLETED / EVIDENCE_SUBMITTED → IN_PROGRESS,
    complaint back IN_PROGRESS).
    ``REQUEST_REWORK`` rejects the submitted evidence and moves the order to
    ``RETURNED_FOR_REWORK`` with ``rework_reason`` set, so the worker performs
    the required fixes (fresh GPS check-in + START_REWORK) and re-submits fresh
    evidence before a new verification cycle.

    The officer is the final authority (Part 30): every persisted AI verdict —
    including a high-confidence ``VERIFIED`` that needed no human review — must
    be reviewed here before the complaint is resolved. The officer never
    delegates that decision to the AI.
    """
    await _require_staff(user)
    order = await _load_order(db, order_id)
    if order is None:
        raise VerifyNotFoundError("Work order not found.")
    await _assert_can_view(db, user, order)

    verification = await _latest_verification(db, order_id)
    if verification is None:
        raise VerifyStateError("No verification has been run for this work order.")
    if verification.reviewed_at is not None:
        raise VerifyStateError("This verification has already been reviewed.")

    reopened = decision == VerificationReviewDecision.REQUIRES_FOLLOWUP
    rework_requested = decision == VerificationReviewDecision.REQUEST_REWORK
    confirmed = not (reopened or rework_requested)
    audit_action = (
        ACTION_WORK_ORDER_RESOLUTION_CONFIRMED
        if confirmed
        else ACTION_WORK_ORDER_REWORK_REQUESTED
        if rework_requested
        else ACTION_WORK_ORDER_REOPENED
    )
    if reopened or rework_requested:
        if order.status not in (
            WorkOrderStatus.COMPLETED,
            WorkOrderStatus.EVIDENCE_SUBMITTED,
        ):
            raise VerifyStateError(
                "Only completed or evidence-submitted work orders can be rejected for follow-up."
            )
        verification.verification_status = VerificationStatus.NOT_RESOLVED
        from_status = order.status
        if rework_requested:
            # The officer wants specific fixes; the order returns to the worker
            # for rework. completed_at / evidence_submitted_at are KEPT so the
            # rework is auditably a follow-up round on the original evidence —
            # they are cleared by START_REWORK (the worker's ack of the rework).
            order.status = WorkOrderStatus.RETURNED_FOR_REWORK
            order.rework_reason = note or "The officer requested rework for this job."
            db.add(
                WorkOrderStatusHistory(
                    work_order_id=order.id,
                    action=WorkOrderAction.REWORK_REQUESTED.value,
                    from_status=from_status,
                    to_status=WorkOrderStatus.RETURNED_FOR_REWORK,
                    actor_id=user.id,
                    note=order.rework_reason,
                )
            )
        else:
            order.status = WorkOrderStatus.IN_PROGRESS
            order.completed_at = None
            order.evidence_submitted_at = None
            db.add(
                WorkOrderStatusHistory(
                    work_order_id=order.id,
                    action=WorkOrderAction.REOPEN.value,
                    from_status=from_status,
                    to_status=WorkOrderStatus.IN_PROGRESS,
                    actor_id=user.id,
                    note=note or "Reopened after a failed repair verification.",
                )
            )
        complaint: Complaint | None = order.complaint
        if complaint is not None:
            if complaint.status.value != ComplaintStatus.IN_PROGRESS.value:
                complaint.status = ComplaintStatus.IN_PROGRESS
                db.add(
                    record_status_transition(
                        complaint,
                        ComplaintStatus.IN_PROGRESS,
                        actor_id=user.id,
                        note=(
                            "Repair verification rejected; rework requested."
                            if rework_requested
                            else "Repair verification failed; follow-up required."
                        ),
                    )
                )
            if rework_requested:
                await _notify_rework_requested(db, order, complaint, note)
            else:
                await _notify_reopened(db, order, complaint, note)
    else:
        verification.verification_status = VerificationStatus.VERIFIED
        # The human reviewer certifies the repair → complaint RESOLVED + order COMPLETED.
        await _confirm_resolution(db, order, user)

    verification.human_review_required = False
    verification.reviewed_by = user.id
    verification.reviewed_at = datetime.now(UTC)
    verification.review_note = note
    await _record_verification_audit(
        db,
        user,
        audit_action,
        order.id,
        {
            "decision": str(decision),
            "verification_status": str(verification.verification_status),
            "complaint_status": (
                str(order.complaint.status) if order.complaint is not None else None
            ),
        },
        note=note,
    )
    await db.commit()

    verification = await _latest_verification(db, order_id)
    assert verification is not None
    return VerificationReviewOut(
        verification=_to_out(verification),
        work_order_status=WorkOrderStatus(order.status).value,
        reopened=reopened,
        rework_requested=rework_requested,
    )


async def _confirm_resolution(db: AsyncSession, order: WorkOrder, actor: User) -> None:
    """Confirm a resolution: order → COMPLETED, complaint → RESOLVED + notify.

    The field worker can only ever take an order to ``EVIDENCE_SUBMITTED``;
    marking the complaint ``RESOLVED`` (and the order ``COMPLETED``) happens here
    — when an authorized officer reviews/applies the final decision. Idempotent
    for the legacy path where the order is already ``COMPLETED``.
    """
    if order.status != WorkOrderStatus.COMPLETED:
        from_status = order.status
        order.status = WorkOrderStatus.COMPLETED
        db.add(
            WorkOrderStatusHistory(
                work_order_id=order.id,
                action=WorkOrderAction.RESOLUTION_CONFIRMED.value,
                from_status=from_status,
                to_status=WorkOrderStatus.COMPLETED,
                actor_id=actor.id,
                note="Repair verification confirmed the resolution.",
            )
        )
    complaint: Complaint | None = order.complaint
    if complaint is None:
        complaint = await db.get(Complaint, order.complaint_id)
    if complaint is not None and complaint.status.value != ComplaintStatus.RESOLVED.value:
        complaint.status = ComplaintStatus.RESOLVED
        db.add(
            record_status_transition(
                complaint,
                ComplaintStatus.RESOLVED,
                actor_id=actor.id,
                note="Repair verification confirmed the resolution.",
            )
        )
        await _notify_resolved(db, complaint, order)
    await _notify_worker_resolved(db, order)
    await db.commit()


async def _notify_worker_resolved(db: AsyncSession, order: WorkOrder) -> None:
    """Tell the assigned field worker their job was confirmed resolved (Part 28)."""
    if order.worker is None or order.worker.user_id is None:
        return
    worker_user = await db.get(User, order.worker.user_id)
    if worker_user is None or not worker_user.is_active:
        return
    incident = order.incident or (order.complaint.title if order.complaint else "a work order")
    await notification_service.notify(
        db,
        targets=[worker_user],
        event=EVENT_WORK_RESOLVED,
        complaint_id=order.complaint_id,
        work_order_id=order.id,
        body=f"The repair verification for '{incident}' was confirmed — your work is resolved.",
        link=f"/work/orders/{order.id}",
    )


async def _notify_ai_result(
    db: AsyncSession, order: WorkOrder, verification: WorkOrderVerification
) -> None:
    """Tell the assigned field worker the AI reviewed their submitted work."""
    if order.worker is None or order.worker.user_id is None:
        return
    worker_user = await db.get(User, order.worker.user_id)
    if worker_user is None or not worker_user.is_active:
        return
    incident = order.incident or (order.complaint.title if order.complaint else "a work order")
    await notification_service.notify(
        db,
        targets=[worker_user],
        event=EVENT_AI_VERIFICATION_RESULT,
        complaint_id=order.complaint_id,
        work_order_id=order.id,
        body=(
            f"The AI reviewed the evidence you submitted for '{incident}'. "
            f"Result: {verification.verification_status}."
        ),
        link=f"/work/orders/{order.id}",
    )
    await db.commit()


async def _notify_resolved(db: AsyncSession, complaint: Complaint, order: WorkOrder) -> None:
    """Notify the complaint owner (+ ward representatives) the job is resolved (Part 21)."""
    link = f"/dashboard/complaints/{complaint.id}"
    owner = await db.get(User, complaint.user_id)
    if owner is not None and owner.is_active:
        await notification_service.notify(
            db,
            targets=[owner],
            event=EVENT_RESOLVED,
            complaint_id=complaint.id,
            work_order_id=order.id,
            body=f"Your complaint '{complaint.title}' was marked resolved.",
            link=link,
        )
    if complaint.ward_id is not None:
        reps = (
            (
                await db.execute(
                    select(User).where(
                        User.ward_id == complaint.ward_id,
                        User.is_active.is_(True),
                        User.role.has(Role.name == RoleName.WARD_REPRESENTATIVE.value),
                    )
                )
            )
            .scalars()
            .all()
        )
        if reps:
            await notification_service.notify(
                db,
                targets=[rep for rep in reps if rep.is_active],
                event=EVENT_RESOLVED,
                complaint_id=complaint.id,
                work_order_id=order.id,
                body=f"Work order for '{complaint.title}' was completed.",
                link=link,
            )


async def _notify_human_review(
    db: AsyncSession, order: WorkOrder, verification: WorkOrderVerification
) -> None:
    """Alert staff (OFFICER / ADMIN) that a verification needs human review (Part 21)."""
    staff = await notification_service.active_users_by_role(
        db, RoleName.OFFICER.value, RoleName.ADMIN.value
    )
    if not staff:
        return
    incident = order.incident if order.incident else None
    subject = incident or (order.complaint.title if order.complaint else "a work order")
    await notification_service.notify(
        db,
        targets=staff,
        event=EVENT_HUMAN_REVIEW,
        complaint_id=order.complaint_id,
        work_order_id=order.id,
        body=(
            f"The AI repair verification for '{subject}' needs human review "
            f"(confidence {verification.confidence})."
        ),
        link=f"/officer/work-orders/{order.id}",
    )
    await db.commit()


async def _notify_rework_requested(
    db: AsyncSession, order: WorkOrder, complaint: Complaint, note: str | None
) -> None:
    """Tell the assigned worker (+ complaint owner) the officer requested rework."""
    link = f"/work/orders/{order.id}"
    reason = note or "The officer requested rework for this job."
    if order.worker is not None and order.worker.user_id is not None:
        worker_user = await db.get(User, order.worker.user_id)
        if worker_user is not None and worker_user.is_active:
            await notification_service.notify(
                db,
                targets=[worker_user],
                event=EVENT_REWORK_REQUESTED,
                complaint_id=complaint.id,
                work_order_id=order.id,
                body=(f"An officer requested rework on '{complaint.title}': {reason}"),
                link=link,
            )
    owner = await db.get(User, complaint.user_id)
    if owner is not None and owner.is_active:
        await notification_service.notify(
            db,
            targets=[owner],
            event=EVENT_WORK_ORDER_REOPENED,
            complaint_id=complaint.id,
            work_order_id=order.id,
            body=(
                f"Rework was requested for '{complaint.title}' — the initial "
                "repair needs additional fixes."
            ),
            link=link,
        )


async def _notify_reopened(
    db: AsyncSession, order: WorkOrder, complaint: Complaint, note: str | None
) -> None:
    """Nudge the assigned worker (+ complaint owner) that more work is needed."""
    link = f"/officer/work-orders/{order.id}"
    if order.worker is not None and order.worker.user_id is not None:
        worker_user = await db.get(User, order.worker.user_id)
        if worker_user is not None and worker_user.is_active:
            await notification_service.notify(
                db,
                targets=[worker_user],
                event=EVENT_WORK_ORDER_REOPENED,
                complaint_id=complaint.id,
                work_order_id=order.id,
                body=(
                    f"Your work order for '{complaint.title}' was reopened for "
                    "follow-up after a repair verification."
                ),
                link=f"/work/orders/{order.id}",
            )
    owner = await db.get(User, complaint.user_id)
    if owner is not None and owner.is_active:
        await notification_service.notify(
            db,
            targets=[owner],
            event=EVENT_WORK_ORDER_REOPENED,
            complaint_id=complaint.id,
            work_order_id=order.id,
            body=(
                f"More work is scheduled for '{complaint.title}' — the initial "
                "repair needs follow-up."
            ),
            link=link,
        )


__all__ = [
    "VerifyAccessError",
    "VerifyEvidenceError",
    "VerifyNotFoundError",
    "VerifyStateError",
    "get_verification",
    "get_work_order_evidence",
    "review_verification",
    "run_verification",
]
