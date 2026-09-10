"""Municipal Officer Command Center business logic (Part 15).

Provides the officer-facing operational dashboards:
* KPI aggregation (total, P1/P2, pending, in-progress, resolved, SLA breaches)
* a filterable / searchable / paginated priority queue of complaints
* map data (complaints, work orders, wards, hotspots)
* an AI-activity status aggregation across all agent pipelines

Access is role-aware: OFFICER / ADMIN / FIELD_WORKER see the whole city while
WARD_REPRESENTATIVE sees only the complaints in their own ward. Citizens are
rejected at the API layer (staff-only role gate).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import case, distinct, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentRun,
    Complaint,
    ComplaintDepartmentHistory,
    ComplaintLocation,
    ComplaintPriorityHistory,
    DepartmentOverride,
    FieldWorker,
    User,
    Ward,
    WorkOrder,
)
from app.models.enums import (
    ComplaintStatus,
    DynamicPriority,
    RoleName,
    WorkOrderStatus,
)
from app.schemas.command_center import (
    AgentActivity,
    AgentSummary,
    AiActivityOut,
    CommandCenterComplaint,
    CommandCenterKpis,
    MapComplaint,
    MapDataOut,
    MapHotspot,
    MapWard,
    MapWorkOrder,
    PriorityQueueOut,
)

# The seven AI activity pipelines shown in the command center. "gis" is listed
# because it is part of the officer command-center vocabulary, but it is a
# service (geo_service) rather than an agent, so it always shows 0 runs unless
# it later gains an agent pipeline.
AGENT_LABELS: dict[str, str] = {
    "triage": "Triage",
    "vision": "Vision",
    "correlation": "Duplicate Detection",
    "gis": "GIS / Geo",
    "context": "Context",
    "priority": "Priority",
    "routing": "Routing",
    "dispatch": "Dispatch",
    "sla_monitor": "SLA Monitoring",
}
AGENT_ORDER: list[str] = [
    "triage",
    "vision",
    "correlation",
    "gis",
    "context",
    "priority",
    "routing",
    "dispatch",
    "sla_monitor",
]

# Complaint statuses that count as "pending" (open / awaiting action).
_PENDING_STATUSES = {
    ComplaintStatus.SUBMITTED,
    ComplaintStatus.AI_ANALYZING,
    ComplaintStatus.EVIDENCE_VERIFIED,
    ComplaintStatus.WARD_IDENTIFIED,
    ComplaintStatus.PRIORITIZED,
    ComplaintStatus.DEPARTMENT_ASSIGNED,
    ComplaintStatus.WORK_ORDER_CREATED,
    ComplaintStatus.OPEN,
}
# Complaint statuses that count as "in progress".
_IN_PROGRESS_STATUSES = {
    ComplaintStatus.IN_PROGRESS,
    ComplaintStatus.WORKER_ASSIGNED,
}
# Complaint statuses that count as "resolved".
_RESOLVED_STATUSES = {
    ComplaintStatus.RESOLVED,
    ComplaintStatus.CITIZEN_VERIFIED,
    ComplaintStatus.CLOSED,
}
# Work-order statuses that are no longer "open" (excluded from SLA breaches).
# WORK_COMPLETED / EVIDENCE_SUBMITTED are worker-done states — only AI +
# human verification remain — so they are not pending SLA obligations either.
_WORK_ORDER_TERMINAL = {
    WorkOrderStatus.COMPLETED,
    WorkOrderStatus.WORK_COMPLETED,
    WorkOrderStatus.EVIDENCE_SUBMITTED,
    WorkOrderStatus.CLOSED,
    WorkOrderStatus.REJECTED,
}

_PRIORITY_WEIGHT = {
    DynamicPriority.P1_CRITICAL: 1.0,
    DynamicPriority.P2_HIGH: 0.75,
    DynamicPriority.P3_MEDIUM: 0.5,
    DynamicPriority.P4_LOW: 0.25,
}


def _max_priority_calc():
    """Correlated scalar: max(calculated_at) of priority history for a complaint."""
    return (
        select(func.max(ComplaintPriorityHistory.calculated_at))
        .where(ComplaintPriorityHistory.complaint_id == Complaint.id)
        .correlate(Complaint)
        .scalar_subquery()
    )


def _latest_priority_priority():
    """Correlated scalar: the priority bucket of the latest history row per complaint."""
    return (
        select(ComplaintPriorityHistory.priority)
        .where(
            ComplaintPriorityHistory.complaint_id == Complaint.id,
            ComplaintPriorityHistory.calculated_at == _max_priority_calc(),
        )
        .order_by(
            ComplaintPriorityHistory.calculated_at.desc(),
            ComplaintPriorityHistory.id.desc(),
        )
        .limit(1)
        .correlate(Complaint)
        .scalar_subquery()
    )


def _latest_priority_score():
    """Correlated scalar: the score of the latest priority history row per complaint."""
    return (
        select(ComplaintPriorityHistory.score)
        .where(
            ComplaintPriorityHistory.complaint_id == Complaint.id,
            ComplaintPriorityHistory.calculated_at == _max_priority_calc(),
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


def _branch_complaint_scope(user: User):
    """Return the where-predicate that restricts complaints to the user's scope."""
    if user.role.name == RoleName.WARD_REPRESENTATIVE.value and user.ward_id is not None:
        return Complaint.ward_id == user.ward_id
    return None


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #
async def get_kpis(db: AsyncSession, user: User) -> CommandCenterKpis:
    scope = _branch_complaint_scope(user)

    # Total complaints in scope.
    total_stmt = select(func.count(distinct(Complaint.id)))
    if scope is not None:
        total_stmt = total_stmt.where(scope)
    total = int(await db.scalar(total_stmt) or 0)

    # Status buckets (pending / in-progress / resolved).
    status_stmt = select(Complaint.status, func.count(distinct(Complaint.id)))
    if scope is not None:
        status_stmt = status_stmt.where(scope)
    status_stmt = status_stmt.group_by(Complaint.status)
    status_rows = (await db.execute(status_stmt)).all()
    pending = in_progress = resolved = 0
    for status_value, count in status_rows:
        st = ComplaintStatus(status_value)
        if st in _PENDING_STATUSES:
            pending += count
        elif st in _IN_PROGRESS_STATUSES:
            in_progress += count
        elif st in _RESOLVED_STATUSES:
            resolved += count

    # P1..P4 from the LATEST priority history bucket per complaint (in scope).
    priority_scalar = _latest_priority_priority()
    pri_stmt = select(Complaint.id, priority_scalar.label("bucket")).where(
        priority_scalar.is_not(None)
    )
    if scope is not None:
        pri_stmt = pri_stmt.where(scope)
    pri_buckets = [row[1] for row in (await db.execute(pri_stmt)).all()]
    p1 = sum(1 for b in pri_buckets if b == DynamicPriority.P1_CRITICAL.value)
    p2 = sum(1 for b in pri_buckets if b == DynamicPriority.P2_HIGH.value)
    p3 = sum(1 for b in pri_buckets if b == DynamicPriority.P3_MEDIUM.value)
    p4 = sum(1 for b in pri_buckets if b == DynamicPriority.P4_LOW.value)

    # SLA breaches: open work orders whose due_at is in the past.
    sla_stmt = (
        select(WorkOrder.id)
        .join(Complaint, Complaint.id == WorkOrder.complaint_id)
        .where(
            WorkOrder.due_at.is_not(None),
            WorkOrder.due_at < datetime.now(UTC),
            WorkOrder.status.not_in([s.value for s in _WORK_ORDER_TERMINAL]),
        )
    )
    if scope is not None:
        sla_stmt = sla_stmt.where(scope)
    sla_rows = (await db.execute(sla_stmt)).all()
    sla_breaches = len(sla_rows)

    # SLA at risk: open orders still inside the window but in its final quarter
    # (elapsed/total >= 0.75), matching the default warning threshold.
    now = datetime.now(UTC)
    at_risk_stmt = (
        select(WorkOrder.id)
        .join(Complaint, Complaint.id == WorkOrder.complaint_id)
        .where(
            WorkOrder.due_at.is_not(None),
            WorkOrder.sla_hours.is_not(None),
            WorkOrder.due_at > now,
            WorkOrder.status.not_in([s.value for s in _WORK_ORDER_TERMINAL]),
            extract("epoch", WorkOrder.due_at - now) <= WorkOrder.sla_hours * 900,
        )
    )
    if scope is not None:
        at_risk_stmt = at_risk_stmt.where(scope)
    sla_at_risk = len((await db.execute(at_risk_stmt)).all())

    return CommandCenterKpis(
        total_complaints=total,
        p1=p1,
        p2=p2,
        p3=p3,
        p4=p4,
        pending=pending,
        in_progress=in_progress,
        resolved=resolved,
        sla_breaches=sla_breaches,
        sla_at_risk=sla_at_risk,
    )


# --------------------------------------------------------------------------- #
# Priority queue
# --------------------------------------------------------------------------- #
async def get_priority_queue(
    db: AsyncSession,
    user: User,
    *,
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    ward_id: uuid.UUID | None = None,
    department: str | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> PriorityQueueOut:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    priority_scalar = _latest_priority_priority()
    score_scalar = _latest_priority_score()
    department_scalar = _latest_department_subq()

    ward_code_scalar = (
        select(Ward.code).where(Ward.id == Complaint.ward_id).correlate(Complaint).scalar_subquery()
    )
    ward_name_scalar = (
        select(Ward.name).where(Ward.id == Complaint.ward_id).correlate(Complaint).scalar_subquery()
    )

    filters = []
    scope = _branch_complaint_scope(user)
    if scope is not None:
        filters.append(scope)
    if status:
        filters.append(Complaint.status == ComplaintStatus(status))
    if category:
        filters.append(Complaint.category == category)
    if ward_id:
        filters.append(Complaint.ward_id == ward_id)
    if priority:
        filters.append(priority_scalar == priority)
    if department:
        filters.append(department_scalar == department)
    if search and search.strip():
        q = f"%{search.strip()}%"
        filters.append(
            Complaint.title.ilike(q)
            | Complaint.description.ilike(q)
            | func.coalesce(Complaint.title, "").ilike(q)
        )
    if date_from:
        filters.append(Complaint.created_at >= date_from)
    if date_to:
        filters.append(Complaint.created_at <= date_to)

    count_stmt = (
        select(func.count(distinct(Complaint.id))).where(*filters)
        if filters
        else select(func.count(distinct(Complaint.id)))
    )
    total = int(await db.scalar(count_stmt) or 0)

    order = (
        case(
            (priority_scalar == DynamicPriority.P1_CRITICAL.value, 0),
            (priority_scalar == DynamicPriority.P2_HIGH.value, 1),
            (priority_scalar == DynamicPriority.P3_MEDIUM.value, 2),
            (priority_scalar == DynamicPriority.P4_LOW.value, 3),
            else_=4,
        ),
        Complaint.created_at.asc(),
    )

    stmt = (
        select(
            Complaint,
            priority_scalar.label("bucket"),
            score_scalar.label("bucket_score"),
            department_scalar.label("effective_department"),
            ward_code_scalar.label("ward_code"),
            ward_name_scalar.label("ward_name"),
        )
        .where(*filters)
        .order_by(*order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()

    items: list[CommandCenterComplaint] = []
    complaint_ids = [r[0].id for r in rows]
    # Latest non-terminal work-order per complaint for SLA surface.
    wo_map = {}
    if complaint_ids:
        wo_rows = (
            await db.execute(
                select(WorkOrder.complaint_id, WorkOrder.status, WorkOrder.due_at)
                .where(WorkOrder.complaint_id.in_(complaint_ids))
                .order_by(WorkOrder.created_at.desc())
            )
        ).all()
        for complaint_id, wo_status, wo_due in wo_rows:
            if complaint_id not in wo_map:
                wo_map[complaint_id] = (wo_status, wo_due)

    for complaint, bucket, score, department, ward_code, ward_name in rows:
        wo_status, wo_due = wo_map.get(complaint.id, (None, None))
        items.append(
            CommandCenterComplaint(
                id=complaint.id,
                complaint_id=complaint.id,
                title=complaint.title,
                description=complaint.description,
                incident=complaint.title,
                category=complaint.category.value
                if hasattr(complaint.category, "value")
                else str(complaint.category),
                status=complaint.status,
                priority=bucket,
                priority_score=score,
                complaint_priority=complaint.priority.value
                if hasattr(complaint.priority, "value")
                else str(complaint.priority),
                department=department,
                ward_code=ward_code,
                ward_name=ward_name,
                created_at=complaint.created_at,
                updated_at=complaint.updated_at,
                sla_due_at=wo_due,
                work_order_status=wo_status,
            )
        )

    total_pages = max(1, (total + page_size - 1) // page_size)
    return PriorityQueueOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# --------------------------------------------------------------------------- #
# Map data
# --------------------------------------------------------------------------- #
async def get_map_data(db: AsyncSession, user: User) -> MapDataOut:
    scope = _branch_complaint_scope(user)

    priority_scalar = _latest_priority_priority()
    department_scalar = _latest_department_subq()

    # Complaints (scoped) with their location + effective department + bucket.
    comp_filters = [ComplaintLocation.complaint_id == Complaint.id]
    if scope is not None:
        comp_filters.append(scope)

    comp_stmt = (
        select(
            Complaint.id,
            Complaint.title,
            Complaint.status,
            Complaint.created_at,
            Complaint.ward_id,
            Ward.code,
            priority_scalar.label("bucket"),
            department_scalar.label("department"),
            ComplaintLocation.latitude,
            ComplaintLocation.longitude,
        )
        .join(ComplaintLocation, ComplaintLocation.complaint_id == Complaint.id)
        .outerjoin(Ward, Ward.id == Complaint.ward_id)
        .where(*comp_filters)
    )
    comp_rows = (await db.execute(comp_stmt)).all()
    complaints: list[MapComplaint] = []
    for (
        cid,
        title,
        status_v,
        created_at,
        _ward_id,
        ward_code,
        bucket,
        department,
        lat,
        lon,
    ) in comp_rows:
        complaints.append(
            MapComplaint(
                id=cid,
                title=title,
                status=str(status_v),
                priority=bucket,
                department=department,
                latitude=lat,
                longitude=lon,
                ward_code=ward_code,
                created_at=created_at,
            )
        )

    # Work orders with their location (denormalized from the complaint).
    wo_filters = [WorkOrder.location_lat.is_not(None), WorkOrder.location_lon.is_not(None)]
    wo_stmt = (
        select(
            WorkOrder.id,
            WorkOrder.complaint_id,
            WorkOrder.department,
            WorkOrder.status,
            WorkOrder.location_lat,
            WorkOrder.location_lon,
            WorkOrder.eta_minutes,
            FieldWorker.user_id,
        )
        .outerjoin(FieldWorker, FieldWorker.id == WorkOrder.worker_id)
        .join(Complaint, Complaint.id == WorkOrder.complaint_id)
        .where(*wo_filters)
    )
    if scope is not None:
        wo_stmt = wo_stmt.where(scope)
    wo_rows = (await db.execute(wo_stmt)).all()
    worker_names = {}
    worker_user_ids = [r[7] for r in wo_rows if r[7] is not None]
    if worker_user_ids:
        wu_rows = (
            await db.execute(select(User.id, User.full_name).where(User.id.in_(worker_user_ids)))
        ).all()
        worker_names = {uid: name for uid, name in wu_rows}

    work_orders: list[MapWorkOrder] = []
    for wid, cid, department, wostatus, lat, lon, eta, worker_user_id in wo_rows:
        work_orders.append(
            MapWorkOrder(
                id=wid,
                complaint_id=cid,
                department=department,
                status=str(wostatus),
                worker_name=worker_names.get(worker_user_id),
                latitude=lat,
                longitude=lon,
                eta_minutes=eta,
            )
        )

    # Wards (all) with complaint counts (global, used for labels).
    ward_count_stmt = (
        select(Complaint.ward_id, func.count(Complaint.id))
        .where(Complaint.ward_id.is_not(None))
        .group_by(Complaint.ward_id)
    )
    ward_counts = dict((await db.execute(ward_count_stmt)).all())

    wards_rows = (await db.execute(select(Ward))).scalars().all()
    wards: list[MapWard] = [
        MapWard(ward_id=w.id, name=w.name, code=w.code, complaint_count=ward_counts.get(w.id, 0))
        for w in wards_rows
    ]

    # Hotspots: group the (scoped) complaints by ward -> counts + priority weight.
    # A ward without a single complaint is NOT a hotspot — with zero operational
    # data the list stays empty (Part 35), and wards with only resolved activity
    # carry open_count 0 rather than disappearing entirely.
    from collections import defaultdict

    ward_index: dict[str, list[MapComplaint]] = defaultdict(list)
    for c in complaints:
        ward_index[c.ward_code or "__none__"].append(c)

    hotspots: list[MapHotspot] = []
    for w in wards_rows:
        ward_comps = ward_index.get(w.code, [])
        if not ward_comps:
            continue
        open_count = sum(
            1
            for cc in ward_comps
            if cc.status in {s.value for s in _PENDING_STATUSES | _IN_PROGRESS_STATUSES}
        )
        weight = 0.0
        for cc in ward_comps:
            if cc.priority in {p.value for p in DynamicPriority}:
                weight += _PRIORITY_WEIGHT.get(DynamicPriority(cc.priority), 0.25)
        hotspots.append(
            MapHotspot(
                ward_id=w.id,
                ward_code=w.code,
                ward_name=w.name,
                complaint_count=ward_counts.get(w.id, 0),
                open_count=open_count,
                priority_weight=round(weight, 2),
            )
        )

    return MapDataOut(
        complaints=complaints,
        work_orders=work_orders,
        wards=wards,
        hotspots=hotspots,
    )


# --------------------------------------------------------------------------- #
# AI activity
# --------------------------------------------------------------------------- #
async def get_ai_activity(db: AsyncSession, _user: User) -> AiActivityOut:
    rows = (
        await db.execute(
            select(AgentRun.agent, AgentRun.status, func.count(AgentRun.id)).group_by(
                AgentRun.agent, AgentRun.status
            )
        )
    ).all()

    # agent_runs persist only RUNNING / SUCCEEDED / FAILED states. "Pending" is
    # surfaced for in-flight runs (status RUNNING, not yet finalized) while the
    # "Completed" / "Failed" buckets map to SUCCEEDED / FAILED respectively.
    breakdown_map: dict[tuple[str, str], int] = {}
    for agent, status_v, count in rows:
        breakdown_map[(agent, status_v)] = count

    last_rows = (
        await db.execute(
            select(AgentRun.agent, func.max(AgentRun.started_at)).group_by(AgentRun.agent)
        )
    ).all()
    last_by_agent: dict[str, datetime] = {agent: last for agent, last in last_rows}

    agents: list[AgentSummary] = []
    for agent in AGENT_ORDER:
        running = breakdown_map.get((agent, "RUNNING"), 0)
        succeeded = breakdown_map.get((agent, "SUCCEEDED"), 0)
        failed = breakdown_map.get((agent, "FAILED"), 0)
        agents.append(
            AgentSummary(
                agent=agent,
                label=AGENT_LABELS.get(agent, agent),
                enabled=agent != "gis",  # gis is a service, not an agent
                total=running + succeeded + failed,
                pending=running,
                running=running,
                completed=succeeded,
                failed=failed,
                last_activity_at=last_by_agent.get(agent),
            )
        )

    breakdown: list[AgentActivity] = [
        AgentActivity(
            agent=agent,
            status=status_v,
            count=count,
            last_run_at=last_by_agent.get(agent),
        )
        for (agent, status_v), count in sorted(breakdown_map.items())
    ]

    return AiActivityOut(last_updated=datetime.now(UTC), agents=agents, breakdown=breakdown)


# --------------------------------------------------------------------------- #
# Realtime snapshot
# --------------------------------------------------------------------------- #
async def build_snapshot(db: AsyncSession, user: User) -> dict:
    """Build the aggregate payload pushed over the command-center WebSocket."""
    kpis = await get_kpis(db, user)
    ai = await get_ai_activity(db, user)
    from app.schemas.command_center import CommandCenterSnapshot

    return CommandCenterSnapshot(
        kpis=kpis,
        ai_activity=ai,
        changed_at=datetime.now(UTC),
    ).model_dump(mode="json")
