"""Core SLA computation service (Part 20).

Turns the configurable ``sla_policies`` rulebook and each open work order's
timeline into a per-order health snapshot (state, progress, countdown) used by:

* the **SLA monitoring agent** (``agents/sla_agent.py``) — scan every open order,
  backfill missing deadlines, escalate warnings/breaches to staff; and
* the **live board API** (``GET /sla/orders``) — read-only, no writes, so an
  officer can refresh the board without mutating anything.

The SLA clock always starts at approval (``approved_at``), which is when the
deadline is computed and persisted as ``due_at``. Orders approved before this
feature are backfilled on the first agent run (base = ``due_at - sla_hours`` so
existing deadlines stay stable).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Complaint, FieldWorker, SlaPolicy, WorkOrder
from app.models.enums import SlaState, WorkOrderStatus
from app.schemas.sla import (
    OrderSlaSnapshot,
    SlaCounts,
    SlaRunOut,
    SlaScanOutput,
)
from app.services import sla_policy_service

# Orders that are no longer monitored (terminal / abandoned drafts).
_TERMINAL = {
    WorkOrderStatus.CLOSED.value,
    WorkOrderStatus.REJECTED.value,
}
# Orders whose work is done (state = COMPLETED, never at risk / breached).
# Includes the worker-completion states: from WORK_COMPLETED on, the physical
# work is finished and only evidence/verification remains.
_DONE = {
    WorkOrderStatus.COMPLETED.value,
    WorkOrderStatus.WORK_COMPLETED.value,
    WorkOrderStatus.EVIDENCE_SUBMITTED.value,
}

_DEFAULT_AT_RISK_PERCENT = 0.75


def human_remaining(seconds: float | None) -> str | None:
    """Human-friendly countdown, e.g. "2d 4h" / "12m" / "overdue 3h 5m"."""
    if seconds is None:
        return None
    if seconds < 0:
        prefix = "overdue "
        total = abs(int(seconds))
    else:
        prefix = ""
        total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return prefix + " ".join(parts)


async def _resolve_policy(
    db: AsyncSession, order: WorkOrder, category: str | None
) -> SlaPolicy | None:
    return await sla_policy_service.resolve(
        db,
        priority=order.priority,
        department=order.department,
        category=category,
    )


async def compute_snapshot(
    db: AsyncSession,
    order: WorkOrder,
    *,
    now: datetime,
    category: str | None = None,
    policy: SlaPolicy | None = None,
    backfill: bool = False,
    worker_name: str | None = None,
) -> OrderSlaSnapshot:
    """Compute the SLA health snapshot for one work order.

    ``now`` is injectable so tests can simulate time; ``backfill`` lets the agent
    persist a missing ``due_at`` / ``sla_hours`` computed from the resolved rule.
    """
    status = order.status.value if hasattr(order.status, "value") else str(order.status)
    if policy is None:
        policy = await _resolve_policy(db, order, category)

    sla_hours = (
        order.sla_hours
        if order.sla_hours is not None
        else (policy.sla_hours if policy is not None else None)
    )
    due_at = order.due_at

    # SLA clock anchor: approval time, else derived from the persisted deadline,
    # else complaint creation.
    base: datetime | None = None
    if order.approved_at is not None:
        base = order.approved_at
    elif due_at is not None and sla_hours is not None:
        base = due_at - timedelta(hours=sla_hours)
    elif order.created_at is not None:
        base = order.created_at

    effective_deadline = due_at
    if effective_deadline is None and sla_hours is not None and base is not None:
        effective_deadline = base + timedelta(hours=sla_hours)
        if backfill:
            order.sla_hours = sla_hours
            order.due_at = effective_deadline

    snapshot = OrderSlaSnapshot(
        work_order_id=order.id,
        complaint_id=order.complaint_id,
        incident=order.incident,
        status=status,
        department=order.department,
        priority=order.priority,
        category=category,
        worker_name=worker_name,
        sla_hours=sla_hours,
        due_at=due_at or effective_deadline,
        policy_id=policy.id if policy is not None else None,
    )

    if status in _DONE:
        snapshot.state = SlaState.COMPLETED
        snapshot.progress = 1.0
        snapshot.remaining_seconds = 0.0
        snapshot.remaining_human = "Completed"
        return snapshot

    if effective_deadline is None:
        snapshot.state = SlaState.ON_TRACK
        snapshot.progress = 0.0
        snapshot.remaining_seconds = None
        snapshot.remaining_human = None
        return snapshot

    total = (
        sla_hours * 3600
        if sla_hours is not None
        else ((effective_deadline - base).total_seconds() if base is not None else None)
    )
    remaining = (effective_deadline - now).total_seconds()
    snapshot.remaining_seconds = remaining
    snapshot.remaining_human = human_remaining(remaining)

    if remaining < 0:
        progress = max(1.0, (total - remaining) / total) if total else 1.0
        snapshot.state = SlaState.BREACHED
        snapshot.progress = round(progress, 4)
        snapshot.breached = True
        return snapshot

    if total is not None and total > 0:
        elapsed = max(0.0, total - remaining)
        progress = elapsed / total
    else:
        progress = 0.0
    snapshot.progress = round(progress, 4)

    threshold = float(policy.at_risk_percent) if policy is not None else _DEFAULT_AT_RISK_PERCENT
    if progress >= threshold:
        snapshot.state = SlaState.AT_RISK
        snapshot.at_risk = True
    else:
        snapshot.state = SlaState.ON_TRACK
    return snapshot


async def scan(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    department: str | None = None,
    priority: str | None = None,
    ward_id: uuid.UUID | None = None,
    backfill: bool = False,
) -> SlaScanOutput:
    """Scan monitored work orders and return per-order snapshots + counts.

    ``ward_id`` restricts the scan to a single ward (WARD_REPRESENTATIVE); when
    omitted the whole city is scanned (officer / admin / SLA agent).

    ``backfill=True`` (agent path) persists missing deadlines; the read-only
    board path leaves ``backfill=False``.
    """
    now = now or datetime.now(UTC)
    stmt = (
        select(WorkOrder)
        .where(WorkOrder.status.not_in(list(_TERMINAL)))
        .options(
            selectinload(WorkOrder.complaint),
            selectinload(WorkOrder.worker).selectinload(FieldWorker.user),
        )
    )
    if ward_id is not None:
        stmt = stmt.join(Complaint, Complaint.id == WorkOrder.complaint_id).where(
            Complaint.ward_id == ward_id
        )
    if department:
        stmt = stmt.where(WorkOrder.department == department)
    if priority:
        stmt = stmt.where(WorkOrder.priority == priority)
    orders = (await db.execute(stmt)).scalars().all()

    snapshots: list[OrderSlaSnapshot] = []
    for order in orders:
        category = None
        if order.complaint is not None:
            category = order.complaint.category.value
            if hasattr(order.complaint.category, "value") is False:
                category = str(order.complaint.category)
        worker_name = None
        if order.worker is not None and order.worker.user is not None:
            worker_name = order.worker.user.full_name
        snapshots.append(
            await compute_snapshot(
                db,
                order,
                now=now,
                category=category,
                backfill=backfill,
                worker_name=worker_name,
            )
        )
    if backfill:
        await db.flush()

    counts = _counts(snapshots)
    return SlaScanOutput(
        checked_at=now,
        counts=counts,
        orders=snapshots,
        notifications_sent={},
    )


def _counts(snapshots: list[OrderSlaSnapshot]) -> SlaCounts:
    counts = SlaCounts()
    for s in snapshots:
        state = s.state.value if hasattr(s.state, "value") else s.state
        if state == "COMPLETED":
            counts.completed += 1
        elif state == "BREACHED":
            counts.breached += 1
            counts.open += 1
        elif state == "AT_RISK":
            counts.at_risk += 1
            counts.open += 1
        elif s.remaining_seconds is None and s.due_at is None:
            counts.no_deadline += 1
            counts.open += 1
        else:
            counts.on_track += 1
            counts.open += 1
    return counts


def _severity_sort_key(s: OrderSlaSnapshot) -> tuple:
    state = s.state.value if hasattr(s.state, "value") else s.state
    order_map = {"BREACHED": 0, "AT_RISK": 1, "ON_TRACK": 2, "COMPLETED": 3}
    return (
        order_map.get(state, 4),
        s.remaining_seconds if s.remaining_seconds is not None else float("inf"),
    )


async def list_sla_orders(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 25,
    state: str | None = None,
    department: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    ward_id: uuid.UUID | None = None,
) -> tuple[list[OrderSlaSnapshot], SlaCounts, int]:
    """Live read-only SLA board: newest computation, sorted by severity.

    ``ward_id`` scopes the board to one ward (WARD_REPRESENTATIVE).

    Returns ``(items, counts, total)`` for the requested page.
    """
    scan_out = await scan(
        db,
        department=department,
        priority=priority,
        ward_id=ward_id,
        backfill=False,
    )
    snapshots = scan_out.orders
    counts = scan_out.counts

    if state:
        snapshots = [
            s
            for s in snapshots
            if (s.state.value if hasattr(s.state, "value") else s.state) == state
        ]
    if search and search.strip():
        q = search.strip().lower()
        snapshots = [
            s
            for s in snapshots
            if (s.incident or "").lower().find(q) >= 0
            or s.work_order_id.__str__().lower().find(q) >= 0
        ]

    snapshots.sort(key=_severity_sort_key)

    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = len(snapshots)
    start = (page - 1) * page_size
    items = snapshots[start : start + page_size]
    return items, counts, total


async def latest_run(db: AsyncSession, *, ward_id: uuid.UUID | None = None) -> dict | None:
    """The most recent persisted ``sla_monitor`` run, if any.

    ``ward_id`` (WARD_REPRESENTATIVE) filters the returned order snapshots to a
    single ward.
    """
    from app.models import AgentRun

    run = await db.scalar(
        select(AgentRun)
        .where(AgentRun.agent == "sla_monitor")
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )
    if run is None:
        return None
    result = (
        SlaScanOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    if ward_id is not None and result is not None and result.orders:
        complaint_ids = (
            await db.scalars(select(Complaint.id).where(Complaint.ward_id == ward_id))
        ).all()
        allowed = set(complaint_ids)
        result.orders = [o for o in result.orders if o.complaint_id in allowed]
    return SlaRunOut(
        id=run.id,
        agent=run.agent,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        duration_ms=run.duration_ms,
        structured_result=result,
        error=run.error,
        started_at=run.started_at,
        ended_at=run.ended_at,
    ).model_dump(mode="json")


def complaint_sla_status(
    *,
    priority: str,
    department: str | None,
    category: str | None,
    submitted_at: datetime,
    now: datetime | None = None,
    policy: SlaPolicy | None,
) -> dict:
    """SLA/Escalation snapshot for a *complaint* (score-independent, Part 12).

    The priority engine tracks SLA separately from the numeric risk score: the
    clock starts at submission (``submitted_at``) and runs toward the deadline of
    the resolved ``sla_policies`` rule. A breach NEVER raises the priority score —
    it only raises the ``state``/``escalation_level`` reported here.

    Returns:
        state (NO_POLICY / ON_TRACK / AT_RISK / BREACHED), sla_hours, due_at,
        remaining_seconds, remaining_human, at_risk_percent, breached,
        escalation_level (0 none / 1 at-risk / 2 breached / 3 breach+warn), and
        the applied policy provenance.
    """
    now = now or datetime.now(UTC)
    base: dict = {
        "state": "NO_POLICY",
        "sla_hours": None,
        "due_at": None,
        "remaining_seconds": None,
        "remaining_human": None,
        "at_risk_percent": None,
        "breached": False,
        "escalation_level": 0,
        "policy_id": None,
        "policy_name": None,
    }
    if policy is None or policy.sla_hours is None or policy.sla_hours <= 0:
        return base

    sla_hours = int(policy.sla_hours)
    due_at = submitted_at + timedelta(hours=sla_hours)
    remaining = (due_at - now).total_seconds()
    total = sla_hours * 3600
    breached = remaining < 0

    attrs = {
        "sla_hours": sla_hours,
        "due_at": due_at,
        "remaining_seconds": remaining,
        "remaining_human": human_remaining(remaining),
        "at_risk_percent": float(policy.at_risk_percent),
        "breached": breached,
        "policy_id": policy.id,
        "policy_name": policy.name,
    }
    if breached:
        attrs["state"] = "BREACHED"
        attrs["escalation_level"] = 3 if bool(policy.escalate_on_breach) else 2
        return attrs

    if total > 0:
        progress = max(0.0, (total - remaining) / total)
        attrs["progress"] = round(progress, 4)
        if progress >= float(policy.at_risk_percent):
            attrs["state"] = "AT_RISK"
            attrs["escalation_level"] = 1
            return attrs
    attrs["state"] = "ON_TRACK"
    return attrs


# Re-exported for the agent / API layer.
__all__ = [
    "complaint_sla_status",
    "compute_snapshot",
    "human_remaining",
    "latest_run",
    "list_sla_orders",
    "scan",
]
