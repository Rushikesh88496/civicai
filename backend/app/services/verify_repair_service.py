"""Service facade for the AI Resolution Verification (Part 19).

Wraps ``VerifyRepairAgent`` with authorization enforcement:

* **Run** — only authorized staff (OFFICER / ADMIN / WARD_REPRESENTATIVE) may
  trigger verification, and only on a ``COMPLETED`` work order.
* **View** — staff may view any verification; the assigned field worker may view
  their own order's result; the complaint owner may see it too (they are the
  ones the resolution is for).
* **Review** — only staff may take the human-approval actions:
  ``CONFIRM_VERIFIED`` (certify the repair) or ``REQUIRES_FOLLOWUP`` (reopen the
  work order so the worker returns and the complaint goes back IN_PROGRESS).

The service keeps the route thin: it resolves the BEFORE/AFTER photo storage
keys + ids, builds the :class:`VerificationInput`, delegates to the agent and
serializes the dedicated ``work_order_verifications`` row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.verify_repair_agent import VerifyRepairAgent
from app.core.config import get_settings
from app.core.notification_types import (
    EVENT_HUMAN_REVIEW,
    EVENT_WORK_ORDER_REOPENED,
)
from app.models import (
    Complaint,
    FieldWorker,
    User,
    WorkOrder,
    WorkOrderPhoto,
    WorkOrderStatusHistory,
    WorkOrderVerification,
)
from app.models.enums import (
    AgentStatus,
    ComplaintStatus,
    RoleName,
    VerificationReviewDecision,
    VerificationStatus,
    WorkOrderAction,
    WorkOrderStatus,
)
from app.schemas.verification import (
    VerificationInput,
    VerificationReviewOut,
    VerificationRunResponse,
    WorkOrderVerificationOut,
)
from app.services import notification_service
from app.services.ai_service import get_ai_service
from app.services.complaint_service import record_status_transition
from app.storage import get_storage

_STAFF_ROLES = (
    RoleName.OFFICER.value,
    RoleName.ADMIN.value,
    RoleName.WARD_REPRESENTATIVE.value,
)


class VerifyNotFoundError(Exception):
    """Raised when a work order does not exist (404, never leaks internals)."""


class VerifyAccessError(Exception):
    """Raised when the authenticated user may not run/view/review this order."""


class VerifyStateError(Exception):
    """Raised when a verification action is illegal for the current state."""


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
    """Staff may view; the assigned worker + the complaint owner may too."""
    if _is_staff(user):
        return
    if user.role.name == RoleName.FIELD_WORKER.value and order.worker_id is not None:
        worker = await db.scalar(select(FieldWorker).where(FieldWorker.user_id == user.id))
        if worker is not None and worker.id == order.worker_id:
            return
    complaint = order.complaint
    if complaint is not None and complaint.user_id == user.id:
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


def _agent() -> VerifyRepairAgent:
    return VerifyRepairAgent(settings=get_settings(), ai=get_ai_service())


async def run_verification(
    db: AsyncSession, user: User, order_id: uuid.UUID
) -> VerificationRunResponse:
    """Run the resolution-verification agent for a completed work order (staff)."""
    await _require_staff(user)
    order = await _load_order(db, order_id)
    if order is None:
        raise VerifyNotFoundError("Work order not found.")
    if order.status != WorkOrderStatus.COMPLETED:
        raise VerifyStateError("Repair verification can only be run on a completed work order.")

    before, after = await _load_photos(db, order_id)
    complaint: Complaint | None = order.complaint
    input_data = VerificationInput(
        complaint_description=(complaint.description or complaint.title if complaint else ""),
        category=complaint.category.value if complaint and complaint.category else None,
        before_key=before.storage_key if before else None,
        after_key=after.storage_key if after else None,
        before_photo_id=before.id if before else None,
        after_photo_id=after.id if after else None,
        priority_bucket=order.priority,
    )

    run = await _agent().run(
        db,
        work_order_id=order.id,
        complaint_id=order.complaint_id,
        input_data=input_data,
    )
    if run.status == AgentStatus.FAILED:
        return VerificationRunResponse(
            run_id=run.id,
            status=run.status,
            result=None,
            error=run.error,
            retry_allowed=True,
        )
    verification = await _latest_verification(db, order_id)
    if verification is not None and verification.human_review_required:
        await _notify_human_review(db, order, verification)
    return VerificationRunResponse(
        run_id=run.id,
        status=run.status,
        result=_to_out(verification) if verification is not None else None,
        error=None,
        retry_allowed=True,
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

    ``CONFIRM_VERIFIED`` certifies the repair (clears the review flag).
    ``REQUIRES_FOLLOWUP`` rejects the outcome and reopens the work order so the
    field worker can return (COMPLETED → IN_PROGRESS, complaint back IN_PROGRESS).
    """
    await _require_staff(user)
    order = await _load_order(db, order_id)
    if order is None:
        raise VerifyNotFoundError("Work order not found.")

    verification = await _latest_verification(db, order_id)
    if verification is None:
        raise VerifyStateError("No verification has been run for this work order.")
    if verification.reviewed_at is not None:
        raise VerifyStateError("This verification has already been reviewed.")
    if verification.human_review_required is False:
        raise VerifyStateError("This verification does not require human review.")

    reopened = decision == VerificationReviewDecision.REQUIRES_FOLLOWUP
    if reopened:
        if order.status != WorkOrderStatus.COMPLETED:
            raise VerifyStateError("Only completed work orders can be reopened for follow-up.")
        order.status = WorkOrderStatus.IN_PROGRESS
        order.completed_at = None
        db.add(
            WorkOrderStatusHistory(
                work_order_id=order.id,
                action=WorkOrderAction.REOPEN.value,
                from_status=WorkOrderStatus.COMPLETED,
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
                        note="Repair verification failed; follow-up required.",
                    )
                )
            await _notify_reopened(db, order, complaint, note)
        verification.verification_status = VerificationStatus.NOT_RESOLVED
    else:
        verification.verification_status = VerificationStatus.VERIFIED

    verification.human_review_required = False
    verification.reviewed_by = user.id
    verification.reviewed_at = datetime.now(UTC)
    verification.review_note = note
    await db.commit()

    verification = await _latest_verification(db, order_id)
    assert verification is not None
    return VerificationReviewOut(
        verification=_to_out(verification),
        work_order_status=WorkOrderStatus(order.status).value,
        reopened=reopened,
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
    "VerifyNotFoundError",
    "VerifyStateError",
    "get_verification",
    "review_verification",
    "run_verification",
]
