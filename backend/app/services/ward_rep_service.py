"""Ward Representative Portal business logic (Part 16).

Gives a ward representative a ward-scoped operational view built purely from
their assigned ward's real records:

* **Dashboard** — ward identity, representative identity, and KPIs (total /
  open / critical / resolved / SLA breaches) scoped to the representative's ward.
* **Map** — the ward's complaints (coloured by dynamic priority) and their work
  orders.
* **AI ward summary** — an LLM-generated summary via Groq when a key is
  configured; otherwise a deterministic synthesis, both grounded in actual
  complaints (never hallucinated counts).
* **Actions** — request an escalation, send an update to a citizen on the
  complaint thread, view a work order, and view a complaint cluster.
* **Authorized conversations** — thread messages between the representative and
  the complaint's citizen owner.

Every read / write is scope-checked against the requesting user (via
``complaint_tracking_service.user_can_view``, which restricts a representative
to their own ward). The authenticated ``User`` comes from the dependency, never
from a client-supplied ID.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.notification_types import EVENT_ESCALATION
from app.models import (
    Complaint,
    ComplaintCorrelation,
    ComplaintDepartmentHistory,
    ComplaintLocation,
    ComplaintPriorityHistory,
    DepartmentOverride,
    FieldWorker,
    User,
    Ward,
    WardRepresentative,
    WorkOrder,
)
from app.models.enums import (
    ComplaintStatus,
    CorrelationMatchStatus,
    CorrelationStatus,
    DynamicPriority,
    RoleName,
    WorkOrderStatus,
)
from app.schemas.conversation import ConversationOut
from app.schemas.ward_rep import (
    ClusterItem,
    ClusterOut,
    DashboardOut,
    EscalationOut,
    RepresentativeOut,
    WardMapComplaint,
    WardMapOut,
    WardMapWorkOrder,
    WardRepKpis,
    WardRepOut,
    WardSummaryOut,
    WorkOrderOut,
)
from app.services import conversation_service, notification_service
from app.services.ai_service import AIService, get_ai_service
from app.services.complaint_service import record_status_transition
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
    user_can_view,
)

# Complaint statuses treated as "open" (awaiting / in action).
_OPEN_STATUSES = {
    ComplaintStatus.SUBMITTED,
    ComplaintStatus.AI_ANALYZING,
    ComplaintStatus.EVIDENCE_VERIFIED,
    ComplaintStatus.WARD_IDENTIFIED,
    ComplaintStatus.PRIORITIZED,
    ComplaintStatus.DEPARTMENT_ASSIGNED,
    ComplaintStatus.WORK_ORDER_CREATED,
    ComplaintStatus.OPEN,
    ComplaintStatus.IN_PROGRESS,
    ComplaintStatus.WORKER_ASSIGNED,
}
# Complaint statuses treated as "resolved".
_RESOLVED_STATUSES = {
    ComplaintStatus.RESOLVED,
    ComplaintStatus.CITIZEN_VERIFIED,
    ComplaintStatus.CLOSED,
}
# Work-order statuses no longer open (excluded from SLA breaches).
_WORK_ORDER_TERMINAL = {
    WorkOrderStatus.COMPLETED,
    WorkOrderStatus.CLOSED,
    WorkOrderStatus.REJECTED,
}


def _max_priority_at():
    return (
        select(func.max(ComplaintPriorityHistory.calculated_at))
        .where(ComplaintPriorityHistory.complaint_id == Complaint.id)
        .correlate(Complaint)
        .scalar_subquery()
    )


def _latest_priority_priority():
    return (
        select(ComplaintPriorityHistory.priority)
        .where(
            ComplaintPriorityHistory.complaint_id == Complaint.id,
            ComplaintPriorityHistory.calculated_at == _max_priority_at(),
        )
        .order_by(
            ComplaintPriorityHistory.calculated_at.desc(),
            ComplaintPriorityHistory.id.desc(),
        )
        .limit(1)
        .correlate(Complaint)
        .scalar_subquery()
    )


def _latest_department_subq():
    """Effective department per complaint: override wins, else latest routing."""
    max_routing = (
        select(func.max(ComplaintDepartmentHistory.calculated_at))
        .where(ComplaintDepartmentHistory.complaint_id == Complaint.id)
        .correlate(Complaint)
        .scalar_subquery()
    )
    routing_dept = (
        select(ComplaintDepartmentHistory.primary_department)
        .where(
            ComplaintDepartmentHistory.complaint_id == Complaint.id,
            ComplaintDepartmentHistory.calculated_at == max_routing,
        )
        .order_by(
            ComplaintDepartmentHistory.calculated_at.desc(),
            ComplaintDepartmentHistory.id.desc(),
        )
        .limit(1)
        .correlate(Complaint)
        .scalar_subquery()
    )
    override_dept = (
        select(DepartmentOverride.new_department)
        .where(DepartmentOverride.complaint_id == Complaint.id)
        .order_by(DepartmentOverride.overridden_at.desc())
        .limit(1)
        .correlate(Complaint)
        .scalar_subquery()
    )
    return func.coalesce(override_dept, routing_dept)


async def _ward_of(db: AsyncSession, user: User) -> Ward | None:
    if user.ward_id is None:
        return None
    return await db.get(Ward, user.ward_id)


async def _rep_of(db: AsyncSession, ward_id: uuid.UUID) -> WardRepresentative | None:
    return await db.scalar(
        select(WardRepresentative)
        .where(WardRepresentative.ward_id == ward_id)
        .order_by(WardRepresentative.created_at.asc())
        .limit(1)
    )


def _rep_out(rep: WardRepresentative | None, rep_user: User | None) -> RepresentativeOut | None:
    if rep is None or rep_user is None:
        return None
    return RepresentativeOut(name=rep_user.full_name, email=rep_user.email, title=rep.title)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
async def get_dashboard(db: AsyncSession, user: User) -> DashboardOut:
    ward = await _ward_of(db, user)
    if ward is None:
        return DashboardOut(ward=None, representative=None, kpis=WardRepKpis())

    scope = Complaint.ward_id == user.ward_id

    total = int((await db.scalar(select(func.count(Complaint.id)).where(scope))) or 0)

    status_rows = (
        await db.execute(
            select(Complaint.status, func.count(Complaint.id))
            .where(scope)
            .group_by(Complaint.status)
        )
    ).all()
    open_count = resolved = 0
    for status_value, count in status_rows:
        st = ComplaintStatus(status_value)
        if st in _OPEN_STATUSES:
            open_count += count
        elif st in _RESOLVED_STATUSES:
            resolved += count

    # Critical: complaints whose LATEST dynamic priority bucket is P1_CRITICAL.
    pri_scalar = _latest_priority_priority()
    critical = int(
        (
            await db.scalar(
                select(func.count(Complaint.id)).where(
                    scope, pri_scalar == DynamicPriority.P1_CRITICAL.value
                )
            )
        )
        or 0
    )

    # SLA breaches: open work orders in the ward whose due date has passed.
    sla = int(
        (
            await db.scalar(
                select(func.count(WorkOrder.id))
                .join(Complaint, Complaint.id == WorkOrder.complaint_id)
                .where(
                    scope,
                    WorkOrder.due_at.is_not(None),
                    WorkOrder.due_at < datetime.now(UTC),
                    WorkOrder.status.not_in([s.value for s in _WORK_ORDER_TERMINAL]),
                )
            )
        )
        or 0
    )

    rep = await _rep_of(db, ward.id)
    rep_user = await db.get(User, rep.user_id) if rep is not None else None

    return DashboardOut(
        ward=WardRepOut(
            id=ward.id,
            code=ward.code,
            name=ward.name,
            description=ward.description,
            representative=_rep_out(rep, rep_user),
        ),
        representative=_rep_out(rep, rep_user),
        kpis=WardRepKpis(
            total_complaints=total,
            open=open_count,
            critical=critical,
            resolved=resolved,
            sla_breaches=sla,
        ),
    )


# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #
async def get_map(db: AsyncSession, user: User) -> WardMapOut:
    if user.ward_id is None:
        return WardMapOut()

    scope = Complaint.ward_id == user.ward_id
    pri_scalar = _latest_priority_priority()
    dept_scalar = _latest_department_subq()

    comp_stmt = (
        select(
            Complaint,
            pri_scalar.label("bucket"),
            dept_scalar.label("department"),
            ComplaintLocation.latitude,
            ComplaintLocation.longitude,
        )
        .outerjoin(ComplaintLocation, ComplaintLocation.complaint_id == Complaint.id)
        .where(scope)
    )
    comp_rows = (await db.execute(comp_stmt)).all()

    complaints: list[WardMapComplaint] = []
    complaint_ids: list[uuid.UUID] = []
    for complaint, bucket, department, lat, lon in comp_rows:
        complaint_ids.append(complaint.id)
        complaints.append(
            WardMapComplaint(
                id=complaint.id,
                complaint_id=complaint.id,
                title=complaint.title,
                status=complaint.status,
                priority=bucket,
                department=department,
                category=complaint.category.value
                if hasattr(complaint.category, "value")
                else str(complaint.category),
                latitude=lat,
                longitude=lon,
                created_at=complaint.created_at,
            )
        )

    work_orders: list[WardMapWorkOrder] = []
    if complaint_ids:
        wo_stmt = (
            select(
                WorkOrder,
                FieldWorker.user_id,
            )
            .outerjoin(FieldWorker, FieldWorker.id == WorkOrder.worker_id)
            .where(WorkOrder.complaint_id.in_(complaint_ids))
        )
        wo_rows = (await db.execute(wo_stmt)).all()
        worker_user_ids = [r[1] for r in wo_rows if r[1] is not None]
        worker_names = {}
        if worker_user_ids:
            name_rows = (
                await db.execute(
                    select(User.id, User.full_name).where(User.id.in_(worker_user_ids))
                )
            ).all()
            worker_names = {uid: name for uid, name in name_rows}
        for order, worker_user_id in wo_rows:
            work_orders.append(
                WardMapWorkOrder(
                    id=order.id,
                    complaint_id=order.complaint_id,
                    department=order.department,
                    status=order.status,
                    worker_name=worker_names.get(worker_user_id),
                    latitude=order.location_lat,
                    longitude=order.location_lon,
                    eta_minutes=order.eta_minutes,
                )
            )

    return WardMapOut(complaints=complaints, work_orders=work_orders)


# --------------------------------------------------------------------------- #
# AI ward summary
# --------------------------------------------------------------------------- #
async def get_ward_summary(
    db: AsyncSession,
    user: User,
    *,
    ai: AIService | None = None,
) -> WardSummaryOut:
    """Generate a ward summary grounded in the ward's actual complaints.

    Uses Groq (via the shared ``AIService``) when a key is configured; otherwise
    produces a deterministic synthesis from the same real records so the UI
    always has a factual, useful result. ``complaint_count`` and
    ``generated_by`` document provenance.
    """
    if user.ward_id is None:
        return WardSummaryOut(summary="No ward assigned.", generated_at=datetime.now(UTC))

    scope = Complaint.ward_id == user.ward_id
    pri_scalar = _latest_priority_priority()
    rows = (await db.execute(select(Complaint, pri_scalar.label("bucket")).where(scope))).all()
    complaints = [r[0] for r in rows]
    buckets = [r[1] for r in rows]

    total = len(complaints)
    open_count = sum(1 for c in complaints if c.status in _OPEN_STATUSES)
    critical_count = sum(1 for b in buckets if b == DynamicPriority.P1_CRITICAL.value)
    resolved_count = sum(1 for c in complaints if c.status in _RESOLVED_STATUSES)

    disabled_service = ai or get_ai_service()
    real = disabled_service.is_configured

    system_prompt = (
        "You are the AI advisor to a municipal ward representative. Write a concise, "
        "professional situation brief for the representative's ward in 3-5 sentences, "
        "and provide a few bullet highlights and recommended actions. Base everything "
        "strictly on the provided data — do not invent counts or complaints. If there "
        "are no complaints, say so plainly."
    )

    if real:
        try:
            recent_sorted = sorted(rows, key=lambda x: x[0].created_at, reverse=True)[:20]
            recent_lines = []
            for c, p in recent_sorted:
                recent_lines.append(f"[{c.title}] status={c.status.value} priority={p or 'n/a'}")
            result = await disabled_service.chat_completion(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Ward has {total} complaints ({open_count} open, "
                            f"{critical_count} critical, {resolved_count} resolved). "
                            "Recent complaints: " + "; ".join(recent_lines)
                        ),
                    },
                ],
                temperature=0.3,
                max_tokens=400,
            )
            summary = result.text.strip()
            return WardSummaryOut(
                summary=summary,
                highlights=[],  # the free-text brief is authoritative for live mode
                recommended_actions=[],
                generated_by="groq",
                generated_at=datetime.now(UTC),
                complaint_count=total,
            )
        except Exception:
            # Fall through to the deterministic synthesis on any provider error.
            pass

    # Deterministic synthesis (no Groq key or provider failure) -- grounded in
    # the real data above.
    summary = _synthesize_summary(total, open_count, critical_count, resolved_count, complaints)
    return WardSummaryOut(
        summary=summary["summary"],
        highlights=summary["highlights"],
        recommended_actions=summary["recommended_actions"],
        generated_by="synthesized",
        generated_at=datetime.now(UTC),
        complaint_count=total,
    )


def _synthesize_summary(total, open_count, critical_count, resolved_count, complaints) -> dict:
    if total == 0:
        return {
            "summary": "This ward currently has no recorded complaints in the system.",
            "highlights": ["No open complaints."],
            "recommended_actions": ["Monitor the portal for new submissions."],
        }

    recent = sorted(complaints, key=lambda c: c.created_at, reverse=True)[:5]
    recent_titles = [c.title for c in recent][:5]
    highlights = [
        f"{open_count} complaints currently open",
        f"{critical_count} critical-priority (P1) complaints",
        f"{resolved_count} complaints resolved",
    ]
    actions = ["Prioritise P1 critical complaints for immediate response."]
    if open_count and critical_count:
        actions.append("Review critical complaints and coordinate with the relevant department.")
    if resolved_count:
        actions.append("Confirm resolved complaints with citizens to close them out.")
    if not actions:
        actions.append("Continue monitoring the ward dashboard.")

    title_fragment = ", ".join(f'"{t}"' for t in recent_titles) or "recent submissions"
    summary = (
        f"This ward has {total} complaint(s) recorded: {open_count} open, "
        f"{critical_count} critical-priority and {resolved_count} resolved. "
        f"Recent submissions include {title_fragment}. "
        "The representative should keep critical-priority items moving and follow up "
        "on resolved complaints with citizens."
    )
    return {"summary": summary, "highlights": highlights, "recommended_actions": actions}


# --------------------------------------------------------------------------- #
# Complaint access helper
# --------------------------------------------------------------------------- #
async def _load_complaint(db: AsyncSession, user: User, complaint_id: uuid.UUID) -> Complaint:
    complaint = await db.scalar(
        select(Complaint).where(Complaint.id == complaint_id).options(selectinload(Complaint.ward))
    )
    if complaint is None:
        raise ComplaintNotFoundError
    if not user_can_view(user, complaint):
        raise ComplaintAccessError
    return complaint


# --------------------------------------------------------------------------- #
# Escalation
# --------------------------------------------------------------------------- #
async def request_escalation(
    db: AsyncSession, user: User, complaint_id: uuid.UUID, reason: str
) -> EscalationOut:
    """Mark a complaint as ESCALATED with a reason (if not already terminal)."""
    complaint = await _load_complaint(db, user, complaint_id)
    if complaint.status in (
        ComplaintStatus.ESCALATED,
        ComplaintStatus.RESOLVED,
        ComplaintStatus.CLOSED,
        ComplaintStatus.CITIZEN_VERIFIED,
    ):
        raise ValueError(f"Cannot escalate a complaint in state {complaint.status.value}.")
    complaint.status = ComplaintStatus.ESCALATED
    db.add(
        record_status_transition(
            complaint,
            ComplaintStatus.ESCALATED,
            actor_id=user.id,
            note=reason,
        )
    )
    await _notify_escalation(db, complaint, reason)
    await db.commit()
    return EscalationOut(complaint_id=complaint.id, status=ComplaintStatus.ESCALATED, note=reason)


async def _notify_escalation(db: AsyncSession, complaint: Complaint, reason: str) -> None:
    """Alert officers/admins that a representative escalated a complaint (Part 21)."""
    staff = await notification_service.active_users_by_role(
        db, RoleName.OFFICER.value, RoleName.ADMIN.value
    )
    if not staff:
        return
    await notification_service.notify(
        db,
        targets=staff,
        event=EVENT_ESCALATION,
        complaint_id=complaint.id,
        body=(
            f"Complaint '{complaint.title}' was escalated by a ward representative: "
            f"{reason or 'No reason given.'}"
        ),
        link=f"/officer/complaints/{complaint.id}",
    )


# --------------------------------------------------------------------------- #
# Conversations (delegated to the Part 17 conversation service)
# --------------------------------------------------------------------------- #
async def get_conversation(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> ConversationOut:
    """Return the complaint's authorized thread (now a full conversation)."""
    return await conversation_service.get_conversation(db, user, complaint_id)


async def send_update(
    db: AsyncSession, user: User, complaint_id: uuid.UUID, body: str
) -> ConversationOut:
    """Post a message on a complaint's conversation (authorized by ward / ownership)."""
    return await conversation_service.send_message(db, user, complaint_id, body)


# --------------------------------------------------------------------------- #
# Work order view
# --------------------------------------------------------------------------- #
async def get_complaint_work_order(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> WorkOrderOut | None:
    complaint = await _load_complaint(db, user, complaint_id)
    order = await db.scalar(
        select(WorkOrder)
        .where(WorkOrder.complaint_id == complaint.id)
        .options(selectinload(WorkOrder.worker).selectinload(FieldWorker.user))
        .order_by(WorkOrder.created_at.desc())
    )
    if order is None:
        return None
    worker_name = order.worker.user.full_name if order.worker and order.worker.user else None
    return WorkOrderOut(
        id=order.id,
        complaint_id=order.complaint_id,
        incident=order.incident,
        department=order.department,
        priority=order.priority,
        status=order.status,
        worker_name=worker_name,
        eta_minutes=order.eta_minutes,
        due_at=order.due_at,
    )


# --------------------------------------------------------------------------- #
# Complaint cluster
# --------------------------------------------------------------------------- #
async def get_complaint_cluster(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> ClusterOut:
    complaint = await _load_complaint(db, user, complaint_id)

    _verified_statuses = [
        CorrelationMatchStatus.PENDING.value,
        CorrelationMatchStatus.CONFIRMED.value,
    ]
    as_source = (
        (
            await db.execute(
                select(ComplaintCorrelation).where(
                    ComplaintCorrelation.source_complaint_id == complaint_id,
                    ComplaintCorrelation.status.in_(_verified_statuses),
                )
            )
        )
        .scalars()
        .all()
    )
    as_target = (
        (
            await db.execute(
                select(ComplaintCorrelation).where(
                    ComplaintCorrelation.target_complaint_id == complaint_id,
                    ComplaintCorrelation.status.in_(_verified_statuses),
                )
            )
        )
        .scalars()
        .all()
    )

    members: list[ClusterItem] = []
    for corr in as_source:
        item = await _cluster_item(
            db,
            corr.target_complaint_id,
            complaint_id,
            corr.similarity,
            corr.distance_m,
            _map_match_status(corr.status),
        )
        if item is not None:
            members.append(item)

    for corr in as_target:
        item = await _cluster_item(
            db,
            corr.source_complaint_id,
            complaint_id,
            corr.similarity,
            corr.distance_m,
            _map_match_status(corr.status),
        )
        if item is not None:
            members.append(item)

    # De-duplicate by complaint id (a complaint can appear from both directions).
    seen: set[uuid.UUID] = set()
    unique: list[ClusterItem] = []
    for item in members:
        if item.complaint_id in seen:
            continue
        seen.add(item.complaint_id)
        unique.append(item)

    return ClusterOut(
        base_complaint_id=complaint.id,
        base_title=complaint.title,
        status=complaint.status.value,
        members=unique,
    )


def _map_match_status(status: CorrelationMatchStatus) -> CorrelationStatus:
    if status == CorrelationMatchStatus.CONFIRMED:
        return CorrelationStatus.CONFIRMED_DUPLICATE
    if status == CorrelationMatchStatus.PENDING:
        return CorrelationStatus.POSSIBLE_DUPLICATE
    return CorrelationStatus.NEW_INCIDENT


async def _cluster_item(
    db: AsyncSession,
    member_id: uuid.UUID,
    base_id: uuid.UUID,
    similarity: float | None,
    distance_m: float | None,
    corr_status: CorrelationStatus,
) -> ClusterItem | None:
    member = await db.get(Complaint, member_id)
    if member is None:
        return None
    bucket = await db.scalar(select(_latest_priority_priority()).where(Complaint.id == member_id))
    return ClusterItem(
        id=member.id,
        complaint_id=member.id,
        title=member.title,
        status=member.status,
        priority=bucket,
        created_at=member.created_at,
        similarity=similarity,
        distance_m=distance_m,
        correlation_status=corr_status,
    )
