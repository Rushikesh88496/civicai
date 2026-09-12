"""Service facade for Work Orders & Autonomous Dispatch (Part 14).

Wraps ``DispatchAgent`` (which deterministically selects a worker, computes an
honest ETA and creates a *draft* work order) with access enforcement, and provides
the officer actions — approve, assign, reassign, escalate, reject — each of which
records an append-only ``WorkOrderStatusHistory`` row. Citizens may view their own
complaint's work orders; managing them (approve/assign/reassign/escalate/reject)
is restricted to staff (OFFICER / ADMIN / WARD_REPRESENTATIVE).

All access decisions receive the authenticated ``User`` from the dependency —
never a client-supplied ID.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.dispatch_agent import AGENT_NAME, DispatchAgent
from app.core.config import get_settings
from app.core.notification_types import (
    EVENT_ESCALATION,
    EVENT_NEW_ASSIGNMENT,
    EVENT_REASSIGNMENT,
    EVENT_WORKER_ASSIGNED,
)
from app.models import (
    AgentRun,
    Complaint,
    FieldWorker,
    Role,
    User,
    WorkerAssignment,
    WorkOrder,
    WorkOrderStatusHistory,
)
from app.models.enums import AssignmentStatus, RoleName, WorkOrderAction, WorkOrderStatus
from app.schemas.work_order import (
    DispatchOutput,
    DispatchRunOut,
    DispatchRunResponse,
    WorkerAssignmentOut,
    WorkOrderDetailBundle,
    WorkOrderDetailOut,
    WorkOrderListOut,
    WorkOrderStatusHistoryEntry,
    WorkOrderStatusHistoryOut,
)
from app.services import notification_service, sla_policy_service
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    _load_complaint,
    user_can_view,
)
from app.services.override_service import OVERRIDE_ASSIGNMENT, record_override

# Assignment provenance (Part 32 — human-in-the-loop). An assignment is either the
# officer accepting the AI recommendation, an override with a different worker, or
# a manual pick when no recommendation existed. The AI recommendation itself is
# never called an assignment.
ASSIGNMENT_ORIGIN_AI = "AI_RECOMMENDATION"
ASSIGNMENT_ORIGIN_OVERRIDE = "OFFICER_OVERRIDE"
ASSIGNMENT_ORIGIN_MANUAL = "MANUAL"


class WorkOrderNotFoundError(Exception):
    """Raised when a complaint or work order does not exist."""


class WorkOrderAccessError(ComplaintAccessError):
    """Raised when the authenticated user cannot access a resource."""


class WorkOrderStateError(Exception):
    """Raised when an action is illegal given the current work-order status."""


async def _assert_can_view_complaint(db: AsyncSession, user: User, complaint_id: uuid.UUID) -> None:
    complaint = await _load_complaint(db, complaint_id)
    if complaint is None:
        raise WorkOrderNotFoundError
    if not user_can_view(user, complaint):
        raise WorkOrderAccessError


async def _load_work_order(db: AsyncSession, work_order_id: uuid.UUID) -> WorkOrder | None:
    return await db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == work_order_id)
        .options(
            selectinload(WorkOrder.worker).selectinload(FieldWorker.user),
            selectinload(WorkOrder.recommended_worker).selectinload(FieldWorker.user),
            selectinload(WorkOrder.assignments)
            .selectinload(WorkerAssignment.worker)
            .selectinload(FieldWorker.user),
            selectinload(WorkOrder.assignments).selectinload(WorkerAssignment.assigned_by_user),
            selectinload(WorkOrder.status_history).selectinload(WorkOrderStatusHistory.actor),
            selectinload(WorkOrder.complaint),
        )
    )


async def _assert_can_view_work_order(
    db: AsyncSession, user: User, work_order_id: uuid.UUID
) -> WorkOrder:
    order = await _load_work_order(db, work_order_id)
    if order is None or order.complaint is None:
        raise WorkOrderNotFoundError
    if not user_can_view(user, order.complaint):
        raise WorkOrderAccessError
    return order


def _agent() -> DispatchAgent:
    return DispatchAgent(settings=get_settings())


async def dispatch_work_order(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> DispatchRunResponse:
    """Run the dispatch agent for a complaint, returning the run state + draft order."""
    await _assert_can_view_complaint(db, user, complaint_id)
    if not get_settings().DISPATCH_ENABLED:
        raise WorkOrderNotFoundError("Dispatch is currently disabled.")
    run, work_order_id = await _agent().run(db, complaint_id=complaint_id, created_by=user.id)
    await db.refresh(run)
    result = (
        DispatchOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return DispatchRunResponse(
        run_id=run.id,
        status=run.status,
        work_order_id=work_order_id,
        result=result,
        error=run.error,
        retry_allowed=True,
    )


async def get_dispatch_result(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> DispatchRunOut | None:
    """Return the most recent dispatch agent run for a complaint, if any."""
    await _assert_can_view_complaint(db, user, complaint_id)
    run = await db.scalar(
        select(AgentRun)
        .where(AgentRun.complaint_id == complaint_id, AgentRun.agent == AGENT_NAME)
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )
    if run is None:
        return None
    result = (
        DispatchOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return DispatchRunOut(
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


async def list_work_orders(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> WorkOrderListOut:
    """Return all work orders for a complaint (newest first)."""
    await _assert_can_view_complaint(db, user, complaint_id)
    rows = (
        (
            await db.execute(
                select(WorkOrder)
                .where(WorkOrder.complaint_id == complaint_id)
                .order_by(WorkOrder.created_at.desc())
                .options(
                    selectinload(WorkOrder.worker).selectinload(FieldWorker.user),
                    # _detail_out resolves recommended_worker.* / complaint.* — without
                    # eager loading these are lazily hit on a no-begin greenlet during
                    # response serialization (MissingGreenlet → 500), so the officer
                    # "complaint work orders" list silently vanished for orders that
                    # carry an AI recommendation.
                    selectinload(WorkOrder.recommended_worker).selectinload(FieldWorker.user),
                    selectinload(WorkOrder.complaint),
                )
            )
        )
        .scalars()
        .all()
    )
    return WorkOrderListOut(
        complaint_id=complaint_id,
        work_orders=[_detail_out(o) for o in rows],
    )


async def get_work_order(
    db: AsyncSession, user: User, work_order_id: uuid.UUID
) -> WorkOrderDetailBundle:
    """Return a work order's detail plus its assignments and status history."""
    order = await _assert_can_view_work_order(db, user, work_order_id)
    return WorkOrderDetailBundle(
        work_order=_detail_out(order),
        assignments=[_assignment_out(a) for a in order.assignments],
        status_history=[
            _status_history_entry(h)
            for h in sorted(order.status_history, key=lambda h: h.recorded_at, reverse=True)
        ],
    )


async def get_work_order_history(
    db: AsyncSession, user: User, work_order_id: uuid.UUID
) -> WorkOrderStatusHistoryOut:
    """Return the append-only status-history trail (newest first)."""
    order = await _assert_can_view_work_order(db, user, work_order_id)
    entries = [
        _status_history_entry(h)
        for h in sorted(order.status_history, key=lambda h: h.recorded_at, reverse=True)
    ]
    return WorkOrderStatusHistoryOut(work_order_id=work_order_id, entries=entries)


async def _owner_for(db: AsyncSession, complaint_id: uuid.UUID | None) -> User | None:
    if complaint_id is None:
        return None
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        return None
    owner = await db.get(User, complaint.user_id)
    return owner if owner is not None and owner.is_active else None


async def _ward_agents_for(db: AsyncSession, complaint_id: uuid.UUID | None) -> list[User]:
    """Active WARD_REPRESENTATIVE users for the complaint's ward (Part 21)."""
    if complaint_id is None:
        return []
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None or complaint.ward_id is None:
        return []
    rows = (
        (
            await db.execute(
                select(User)
                .join(Role, Role.id == User.role_id)
                .where(
                    User.ward_id == complaint.ward_id,
                    User.is_active.is_(True),
                    Role.name == RoleName.WARD_REPRESENTATIVE.value,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _work_order_link(work_order_id: uuid.UUID) -> str:
    return f"/officer/work-orders/{work_order_id}"


async def _notify_assignment(
    db: AsyncSession, order: WorkOrder, worker: User, *, is_new: bool
) -> None:
    """Notify the citizen of the assigned worker + the worker of their new job."""
    link = _work_order_link(order.id)
    owner = await _owner_for(db, order.complaint_id)
    if owner is not None:
        await notification_service.notify(
            db,
            targets=[owner],
            event=EVENT_WORKER_ASSIGNED,
            complaint_id=order.complaint_id,
            work_order_id=order.id,
            body=(
                f"A field worker was assigned to '{order.incident or order.complaint_id}' "
                f"({worker.full_name})."
            ),
            link=link,
        )
    await notification_service.notify(
        db,
        targets=[worker],
        event=EVENT_NEW_ASSIGNMENT if is_new else EVENT_REASSIGNMENT,
        complaint_id=order.complaint_id,
        work_order_id=order.id,
        body=f"You have been assigned to work order '{order.incident or order.id}'.",
        link=f"/work/orders/{order.id}",
    )


async def _notify_escalation(db: AsyncSession, order: WorkOrder, reason: str) -> None:
    """Alert the ward's representatives that a work order was escalated (Part 21)."""
    agents = await _ward_agents_for(db, order.complaint_id)
    if not agents:
        return
    await notification_service.notify(
        db,
        targets=agents,
        event=EVENT_ESCALATION,
        complaint_id=order.complaint_id,
        work_order_id=order.id,
        body=(
            f"Work order '{order.incident or order.id}' was escalated: "
            f"{reason or 'No reason given.'}"
        ),
        link=_work_order_link(order.id),
    )


async def approve_work_order(
    db: AsyncSession, user: User, work_order_id: uuid.UUID, note: str = ""
) -> WorkOrderDetailBundle:
    """Officer approves a draft → approved. The recommended worker (if any) is
    formalized into an active assignment (``origin=AI_RECOMMENDATION``); the
    order moves to ASSIGNED."""
    order = await _assert_can_view_work_order(db, user, work_order_id)
    if order.status not in (WorkOrderStatus.PENDING_APPROVAL,):
        raise WorkOrderStateError(f"Cannot approve a work order in state {order.status}.")
    order.status = WorkOrderStatus.ASSIGNED
    order.approved_by = user.id
    order.approved_at = _now()
    await _apply_sla_deadline(db, order, base_at=order.approved_at)

    if order.worker_id is not None:
        _supersede_active_assignment(db, order)
        db.add(
            WorkerAssignment(
                work_order_id=order.id,
                worker_id=order.worker_id,
                status=AssignmentStatus.ASSIGNED,
                assigned_by=user.id,
                origin=ASSIGNMENT_ORIGIN_AI,
                reason="Recommended worker confirmed on approval.",
            )
        )
    db.add(
        WorkOrderStatusHistory(
            work_order_id=order.id,
            action=WorkOrderAction.APPROVE.value,
            from_status=WorkOrderStatus.PENDING_APPROVAL,
            to_status=WorkOrderStatus.ASSIGNED,
            actor_id=user.id,
            note=note or "Approved by officer.",
        )
    )
    if order.worker is not None and order.worker.user is not None:
        await _notify_assignment(db, order, order.worker.user, is_new=True)
    await db.commit()
    db.expire_all()
    return await get_work_order(db, user, work_order_id)


async def assign_work_order(
    db: AsyncSession,
    user: User,
    work_order_id: uuid.UUID,
    worker_id: uuid.UUID,
    reason: str,
) -> WorkOrderDetailBundle:
    """Officer assigns a worker to a work order (or reassigns if one is held).

    The chosen worker is classified against the frozen AI recommendation
    (``order.recommended_worker_id``): accepting it is ``AI_RECOMMENDATION``,
    picking a different worker is ``OFFICER_OVERRIDE`` (a ``human_overrides``
    row is written), and picking any worker without a recommendation is
    ``MANUAL``.
    """
    order = await _assert_can_view_work_order(db, user, work_order_id)
    if order.status in (
        WorkOrderStatus.COMPLETED,
        WorkOrderStatus.CLOSED,
        WorkOrderStatus.REJECTED,
    ):
        raise WorkOrderStateError(f"Cannot assign a work order in state {order.status}.")

    worker = await db.scalar(
        select(FieldWorker)
        .where(FieldWorker.id == worker_id)
        .options(selectinload(FieldWorker.user))
    )
    if worker is None:
        raise WorkOrderNotFoundError("Worker not found.")
    if worker.status.value != "ACTIVE":
        raise WorkOrderStateError("Worker is not active.")

    origin = _assignment_origin(order, worker_id)
    recommended_id = order.recommended_worker_id
    recommended_name = (
        order.recommended_worker.user.full_name
        if order.recommended_worker is not None and order.recommended_worker.user is not None
        else None
    )
    new_name = worker.user.full_name if worker.user is not None else None

    previous = order.worker_id
    _supersede_active_assignment(db, order)
    order.worker_id = worker.id
    order.status = WorkOrderStatus.ASSIGNED
    await _apply_sla_deadline(db, order, base_at=order.approved_at or order.created_at)
    if previous is not None and previous != worker.id:
        action = WorkOrderAction.REASSIGN
    else:
        action = WorkOrderAction.ASSIGN
    db.add(
        WorkerAssignment(
            work_order_id=order.id,
            worker_id=worker.id,
            status=AssignmentStatus.ASSIGNED,
            assigned_by=user.id,
            origin=origin,
            reason=reason,
        )
    )
    db.add(
        WorkOrderStatusHistory(
            work_order_id=order.id,
            action=action.value,
            from_status=None,
            to_status=WorkOrderStatus.ASSIGNED,
            actor_id=user.id,
            note=reason,
        )
    )
    if origin == ASSIGNMENT_ORIGIN_OVERRIDE:
        await record_override(
            db,
            complaint_id=order.complaint_id,
            override_type=OVERRIDE_ASSIGNMENT,
            original_value=recommended_name,
            new_value=new_name,
            original_data={"recommended_worker_id": str(recommended_id)}
            if recommended_id is not None
            else None,
            new_data={"assigned_worker_id": str(worker.id)},
            reason=f"{reason} (AI recommended {recommended_name or 'no worker'}).",
            user_id=user.id,
        )
    if worker.user is not None:
        await _notify_assignment(db, order, worker.user, is_new=action == WorkOrderAction.ASSIGN)
    await db.commit()
    db.expire_all()
    return await get_work_order(db, user, work_order_id)


async def reassign_work_order(
    db: AsyncSession,
    user: User,
    work_order_id: uuid.UUID,
    worker_id: uuid.UUID,
    reason: str,
) -> WorkOrderDetailBundle:
    """Officer reassigns a work order to a different worker (supersede + record)."""
    order = await _assert_can_view_work_order(db, user, work_order_id)
    if order.status in (
        WorkOrderStatus.COMPLETED,
        WorkOrderStatus.CLOSED,
        WorkOrderStatus.REJECTED,
    ):
        raise WorkOrderStateError(f"Cannot reassign a work order in state {order.status}.")

    worker = await db.scalar(
        select(FieldWorker)
        .where(FieldWorker.id == worker_id)
        .options(selectinload(FieldWorker.user))
    )
    if worker is None:
        raise WorkOrderNotFoundError("Worker not found.")
    if worker.status.value != "ACTIVE":
        raise WorkOrderStateError("Worker is not active.")
    if order.worker_id == worker.id:
        raise WorkOrderStateError("Worker is already assigned to this work order.")

    origin = _assignment_origin(order, worker.id)
    recommended_id = order.recommended_worker_id
    recommended_name = (
        order.recommended_worker.user.full_name
        if order.recommended_worker is not None and order.recommended_worker.user is not None
        else None
    )
    new_name = worker.user.full_name if worker.user is not None else None

    _supersede_active_assignment(db, order)
    order.worker_id = worker.id
    order.status = WorkOrderStatus.ASSIGNED
    await _apply_sla_deadline(db, order, base_at=order.approved_at or order.created_at)
    db.add(
        WorkerAssignment(
            work_order_id=order.id,
            worker_id=worker.id,
            status=AssignmentStatus.REASSIGNED,
            assigned_by=user.id,
            origin=origin,
            reason=reason,
        )
    )
    db.add(
        WorkOrderStatusHistory(
            work_order_id=order.id,
            action=WorkOrderAction.REASSIGN.value,
            from_status=None,
            to_status=WorkOrderStatus.ASSIGNED,
            actor_id=user.id,
            note=reason,
        )
    )
    if origin == ASSIGNMENT_ORIGIN_OVERRIDE:
        await record_override(
            db,
            complaint_id=order.complaint_id,
            override_type=OVERRIDE_ASSIGNMENT,
            original_value=recommended_name,
            new_value=new_name,
            original_data={"recommended_worker_id": str(recommended_id)}
            if recommended_id is not None
            else None,
            new_data={"assigned_worker_id": str(worker.id)},
            reason=f"{reason} (AI recommended {recommended_name or 'no worker'}).",
            user_id=user.id,
        )
    if worker.user is not None:
        await _notify_assignment(db, order, worker.user, is_new=False)
    await db.commit()
    db.expire_all()
    return await get_work_order(db, user, work_order_id)


async def escalate_work_order(
    db: AsyncSession, user: User, work_order_id: uuid.UUID, reason: str
) -> WorkOrderDetailBundle:
    """Officer escalates a work order (no worker / out of SLA)."""
    order = await _assert_can_view_work_order(db, user, work_order_id)
    if order.status in (
        WorkOrderStatus.COMPLETED,
        WorkOrderStatus.CLOSED,
        WorkOrderStatus.REJECTED,
        WorkOrderStatus.ESCALATED,
    ):
        raise WorkOrderStateError(f"Cannot escalate a work order in state {order.status}.")
    previous_status = order.status
    order.status = WorkOrderStatus.ESCALATED
    order.note = reason
    db.add(
        WorkOrderStatusHistory(
            work_order_id=order.id,
            action=WorkOrderAction.ESCALATE.value,
            from_status=previous_status,
            to_status=WorkOrderStatus.ESCALATED,
            actor_id=user.id,
            note=reason,
        )
    )
    await _notify_escalation(db, order, reason)
    await db.commit()
    db.expire_all()
    return await get_work_order(db, user, work_order_id)


async def reject_work_order(
    db: AsyncSession, user: User, work_order_id: uuid.UUID, note: str = ""
) -> WorkOrderDetailBundle:
    """Officer rejects a draft work order (it should not proceed)."""
    order = await _assert_can_view_work_order(db, user, work_order_id)
    if order.status not in (WorkOrderStatus.PENDING_APPROVAL,):
        raise WorkOrderStateError(f"Cannot reject a work order in state {order.status}.")
    order.status = WorkOrderStatus.REJECTED
    order.note = note
    db.add(
        WorkOrderStatusHistory(
            work_order_id=order.id,
            action=WorkOrderAction.REJECT.value,
            from_status=WorkOrderStatus.PENDING_APPROVAL,
            to_status=WorkOrderStatus.REJECTED,
            actor_id=user.id,
            note=note or "Rejected by officer.",
        )
    )
    await db.commit()
    db.expire_all()
    return await get_work_order(db, user, work_order_id)


def _supersede_active_assignment(db: AsyncSession, order: WorkOrder) -> None:
    """Mark any currently-ASSIGNED assignment row as superseded."""
    for a in order.assignments:
        if a.status == AssignmentStatus.ASSIGNED:
            a.status = AssignmentStatus.UNASSIGNED


def _assignment_origin(order: WorkOrder, worker_id: uuid.UUID) -> str:
    """Classify an officer's pick against the frozen AI recommendation.

    ``recommended_worker_id`` is captured at dispatch time and never mutated,
    so even a later reassignment can still say whether a given pick honoured
    (or overrode) the AI recommendation.
    """
    recommended = order.recommended_worker_id
    if recommended is None:
        return ASSIGNMENT_ORIGIN_MANUAL
    return ASSIGNMENT_ORIGIN_AI if recommended == worker_id else ASSIGNMENT_ORIGIN_OVERRIDE


def _worker_name(order: WorkOrder) -> str | None:
    if order.worker is None:
        return None
    return order.worker.user.full_name if order.worker.user else None


def _detail_out(o: WorkOrder) -> WorkOrderDetailOut:
    return WorkOrderDetailOut(
        id=o.id,
        complaint_id=o.complaint_id,
        incident=o.incident,
        department=o.department,
        priority=o.priority,
        location_lat=o.location_lat,
        location_lon=o.location_lon,
        address=o.address,
        sla_hours=o.sla_hours,
        due_at=o.due_at,
        recommended_action=o.recommended_action,
        status=o.status,
        eta_minutes=o.eta_minutes,
        eta_source=o.eta_source,
        worker_name=_worker_name(o),
        recommended_worker_id=o.recommended_worker_id,
        recommended_worker_name=(
            o.recommended_worker.user.full_name
            if o.recommended_worker is not None and o.recommended_worker.user is not None
            else None
        ),
        created_at=o.created_at,
        updated_at=o.updated_at,
    )


def _status_history_entry(h: WorkOrderStatusHistory) -> WorkOrderStatusHistoryEntry:
    return WorkOrderStatusHistoryEntry(
        id=h.id,
        action=h.action,
        from_status=h.from_status,
        to_status=h.to_status,
        actor_name=h.actor.full_name if h.actor else None,
        note=h.note,
        recorded_at=h.recorded_at,
    )


def _assignment_out(a: WorkerAssignment) -> WorkerAssignmentOut:
    return WorkerAssignmentOut(
        id=a.id,
        work_order_id=a.work_order_id,
        worker_id=a.worker_id,
        worker_name=a.worker.user.full_name if a.worker and a.worker.user else None,
        status=a.status,
        assigned_by_name=a.assigned_by_user.full_name if a.assigned_by_user else None,
        origin=a.origin,
        reason=a.reason,
        assigned_at=a.assigned_at,
    )


def _now():
    return datetime.now(UTC)


async def _apply_sla_deadline(
    db: AsyncSession, order: WorkOrder, *, base_at: datetime | None
) -> None:
    """Backfill an SLA deadline from the configurable rulebook (Part 20).

    Sets ``sla_hours`` (when missing) from the most specific
    ``(priority, department, category)`` rule and derives ``due_at`` from the
    SLA clock start (``base_at``). Existing values are always respected so an
    officer override is never clobbered by a routine approve/assign.
    """
    if order.sla_hours is not None and order.due_at is not None:
        return
    category = None
    if order.complaint is not None:
        cat = order.complaint.category
        category = cat.value if hasattr(cat, "value") else str(cat)
    policy = await sla_policy_service.resolve(
        db,
        priority=order.priority,
        department=order.department,
        category=category,
    )
    if policy is None:
        return
    if order.sla_hours is None:
        order.sla_hours = policy.sla_hours
    if order.due_at is None and order.sla_hours is not None and base_at is not None:
        order.due_at = base_at + timedelta(hours=order.sla_hours)
