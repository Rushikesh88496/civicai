"""Civic analytics aggregation business logic (Part 22).

Produces the staff-facing analytics dashboard:

* KPIs — total complaints, resolution rate, response / resolution time
  (avg + median over "measured" complaints), SLA compliance (from work-order
  deadlines), AI triage rate, escalation rate and citizen satisfaction.
* Chart series — complaints over time, resolution trend, category / ward /
  department / SLA breakdowns.
* Heatmap — pre-aggregated complaint clusters for the Leaflet map.
* CSV export — a flattened per-complaint snapshot of the filtered dataset.

Role scoping mirrors the command center: OFFICER / ADMIN / FIELD_WORKER see the
whole city while WARD_REPRESENTATIVE sees only their own ward.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import median

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentRun,
    Complaint,
    ComplaintLocation,
    ComplaintRating,
    ComplaintStatusHistory,
    User,
    Ward,
    WorkOrder,
)
from app.models.enums import AgentStatus, DynamicPriority, WorkOrderStatus
from app.schemas.analytics import (
    AnalyticsCharts,
    AnalyticsFilters,
    AnalyticsKpis,
    AnalyticsOverview,
    CategoryPoint,
    DepartmentPoint,
    HeatmapCluster,
    HeatmapOut,
    SatisfactionBucket,
    SlaPoint,
    TimePoint,
    WardPoint,
)
from app.services.command_center_service import (
    _RESOLVED_STATUSES,
    _branch_complaint_scope,
    _latest_department_subq,
    _latest_priority_priority,
)

_RESOLVED_VALUES = {s.value for s in _RESOLVED_STATUSES}
_WORK_ORDER_TERMINAL = {WorkOrderStatus.COMPLETED, WorkOrderStatus.CLOSED, WorkOrderStatus.REJECTED}
_TERMINAL_VALUES = {s.value for s in _WORK_ORDER_TERMINAL}

_PRIORITY_WEIGHT = {
    DynamicPriority.P1_CRITICAL.value: 1.0,
    DynamicPriority.P2_HIGH.value: 0.75,
    DynamicPriority.P3_MEDIUM.value: 0.5,
    DynamicPriority.P4_LOW.value: 0.25,
}

# Heatmap grid cell size in decimal degrees (~550 m at the equator).
_HEATMAP_PRECISION = 0.005
_MAX_HEATMAP_CLUSTERS = 500


def _fmt(value):
    return value.value if hasattr(value, "value") else str(value)


def _fmt_or_none(value):
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _complaint_filters(
    user: User,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    ward_id: uuid.UUID | None = None,
    department: str | None = None,
    category: str | None = None,
    priority: str | None = None,
):
    """Complaint-level WHERE clauses shared by every aggregation."""
    filters = []
    scope = _branch_complaint_scope(user)
    if scope is not None:
        filters.append(scope)
    if date_from is not None:
        filters.append(Complaint.created_at >= date_from)
    if date_to is not None:
        filters.append(Complaint.created_at <= date_to)
    if ward_id is not None:
        filters.append(Complaint.ward_id == ward_id)
    if category:
        filters.append(Complaint.category == category)
    if priority:
        filters.append(_latest_priority_priority() == priority)
    if department:
        filters.append(_latest_department_subq() == department)
    return filters


async def _base_rows(
    db: AsyncSession, user: User, filters: list
) -> tuple[list, Select]:
    """Per-complaint rows (id/status/category/ward/timestamps/effective dept/bucket)."""
    priority_scalar = _latest_priority_priority()
    department_scalar = _latest_department_subq()
    sub = select(Complaint.id).where(*filters)
    stmt = (
        select(
            Complaint.id,
            Complaint.status,
            Complaint.category,
            Complaint.ward_id,
            Complaint.created_at,
            Complaint.updated_at,
            priority_scalar.label("bucket"),
            department_scalar.label("department"),
        )
        .where(*filters)
    )
    rows = (await db.execute(stmt)).all()
    return rows, sub


async def _event_maps(db: AsyncSession, sub) -> dict:
    """Derived complaint-event maps for the filtered complaint set."""
    resolution_rows = (
        await db.execute(
            select(
                ComplaintStatusHistory.complaint_id,
                func.min(ComplaintStatusHistory.recorded_at).label("resolved_at"),
            )
            .where(
                ComplaintStatusHistory.complaint_id.in_(sub),
                ComplaintStatusHistory.status.in_(sorted(_RESOLVED_VALUES)),
            )
            .group_by(ComplaintStatusHistory.complaint_id)
        )
    ).all()
    resolution_map = {cid: ts for cid, ts in resolution_rows}

    response_rows = (
        await db.execute(
            select(
                ComplaintStatusHistory.complaint_id,
                func.min(ComplaintStatusHistory.recorded_at).label("response_at"),
            )
            .where(
                ComplaintStatusHistory.complaint_id.in_(sub),
                ComplaintStatusHistory.status.not_in(["SUBMITTED", "OPEN"]),
            )
            .group_by(ComplaintStatusHistory.complaint_id)
        )
    ).all()
    response_map = {cid: ts for cid, ts in response_rows}

    escalated_rows = (
        await db.execute(
            select(ComplaintStatusHistory.complaint_id)
            .where(
                ComplaintStatusHistory.complaint_id.in_(sub),
                ComplaintStatusHistory.status.in_(["ESCALATED"]),
            )
            .distinct()
        )
    ).all()
    escalated = {cid for (cid,) in escalated_rows}

    ai_rows = (
        await db.execute(
            select(AgentRun.complaint_id)
            .where(
                AgentRun.complaint_id.in_(sub),
                AgentRun.agent == "triage",
                AgentRun.status == AgentStatus.SUCCEEDED,
            )
            .distinct()
        )
    ).all()
    ai_triaged = {cid for (cid,) in ai_rows if cid is not None}

    return {
        "resolution_map": resolution_map,
        "response_map": response_map,
        "escalated": escalated,
        "ai_triaged": ai_triaged,
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(median(values), 1)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


# --------------------------------------------------------------------------- #
# Timeseries
# --------------------------------------------------------------------------- #
def _month_keys(first: date, last: date) -> list[str]:
    keys = []
    y, m = first.year, first.month
    while (y < last.year) or (y == last.year and m <= last.month):
        keys.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y += 1
            m = 1
    return keys


def _day_keys(first: date, last: date) -> list[str]:
    keys = []
    d = first
    while d <= last:
        keys.append(d.isoformat())
        d += timedelta(days=1)
    return keys


def _build_timeseries(points, start: date | None, end: date | None) -> list[TimePoint]:
    """Bucket created/resolved timestamps into daily (<=92d span) or monthly keys."""
    if not points:
        return []
    dates = [p[0].date() for p in points if p[0] is not None]
    if not dates:
        return []
    first = start if start is not None else min(dates)
    last = end if end is not None else max(dates)
    span_days = (last - first).days
    if span_days < 0:
        return []
    step = "d" if span_days <= 92 else "m"

    keys = _day_keys(first, last) if step == "d" else _month_keys(first, last)
    totals = Counter()
    resolved = Counter()
    for created_at, resolved_at in points:
        if created_at is not None:
            created_key = (
                created_at.date().isoformat()
                if step == "d"
                else f"{created_at.year:04d}-{created_at.month:02d}"
            )
            totals[created_key] += 1
        if resolved_at is not None:
            r_key = (
                resolved_at.date().isoformat()
                if step == "d"
                else f"{resolved_at.year:04d}-{resolved_at.month:02d}"
            )
            resolved[r_key] += 1
    return [
        TimePoint(period=key, total=totals.get(key, 0), resolved=resolved.get(key, 0))
        for key in keys
    ]


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
async def get_overview(
    db: AsyncSession,
    user: User,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    ward_id: uuid.UUID | None = None,
    department: str | None = None,
    category: str | None = None,
    priority: str | None = None,
) -> AnalyticsOverview:
    filters = _complaint_filters(
        user,
        date_from=date_from,
        date_to=date_to,
        ward_id=ward_id,
        department=department,
        category=category,
        priority=priority,
    )
    rows, sub = await _base_rows(db, user, filters)
    maps = await _event_maps(db, sub)
    resolution_map: dict = maps["resolution_map"]
    response_map: dict = maps["response_map"]
    escalated: set = maps["escalated"]
    ai_triaged: set = maps["ai_triaged"]

    total = len(rows)

    # Resolved set: reached a resolved state (history) OR currently resolved.
    resolved_ids = set(resolution_map.keys())
    current_resolved = {r[0] for r in rows if r[1] is not None and _fmt(r[1]) in _RESOLVED_VALUES}
    resolved_ids |= current_resolved
    resolved = len(resolved_ids)

    # Response / resolution times (seconds) over measured complaints.
    response_secs: list[float] = []
    resolution_secs: list[float] = []
    for cid, status_v, _cat, _w, created_at, updated_at, _b, _d in rows:
        if created_at is None:
            continue
        r_at = response_map.get(cid)
        if r_at is not None:
            response_secs.append((r_at - created_at).total_seconds())
        res_at = resolution_map.get(cid)
        if res_at is None and status_v is not None and _fmt(status_v) in _RESOLVED_VALUES:
            if updated_at is not None and updated_at > created_at:
                res_at = updated_at
        if res_at is not None:
            resolution_secs.append((res_at - created_at).total_seconds())

    # Work-order based SLA + department performance (complaint scope applies).
    wo_filters = filters.copy() if filters else []
    wo_stmt = (
        select(
            WorkOrder.department,
            WorkOrder.priority,
            WorkOrder.status,
            WorkOrder.completed_at,
            WorkOrder.created_at,
            WorkOrder.due_at,
        )
        .join(Complaint, Complaint.id == WorkOrder.complaint_id)
        .where(*wo_filters)
    )
    if department:
        wo_stmt = wo_stmt.where(WorkOrder.department == department)
    if priority:
        wo_stmt = wo_stmt.where(WorkOrder.priority == priority)
    wo_rows = (await db.execute(wo_stmt)).all()

    now = datetime.now(UTC)
    dept_index: dict[str, dict] = defaultdict(
        lambda: {
            "total": 0,
            "completed": 0,
            "completion": [],
            "within": 0,
            "overdue": 0,
            "escalated": 0,
        }
    )
    sla_index: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "within": 0, "overdue": 0}
    )
    sla_within = sla_overdue = 0
    sla_queue = sla_none = 0
    for dept, wo_priority, wo_status, completed_at, wo_created, due_at in wo_rows:
        d = dept_index[dept]
        d["total"] += 1
        if completed_at is not None:
            d["completed"] += 1
            if wo_created is not None and completed_at > wo_created:
                d["completion"].append((completed_at - wo_created).total_seconds())
        if _fmt(wo_status or WorkOrderStatus.PENDING_APPROVAL) == WorkOrderStatus.ESCALATED.value:
            d["escalated"] += 1

        if due_at is not None:
            sla_queue += 1
            bucket = sla_index[wo_priority or "UNASSESSED"]
            bucket["total"] += 1
            if completed_at is not None:
                if completed_at <= due_at:
                    d["within"] += 1
                    bucket["within"] += 1
                    sla_within += 1
                else:
                    d["overdue"] += 1
                    bucket["overdue"] += 1
                    sla_overdue += 1
            else:
                if due_at < now:
                    d["overdue"] += 1
                    bucket["overdue"] += 1
                    sla_overdue += 1
        else:
            sla_none += 1

    sla_compliance_rate = (
        round(sla_within / (sla_within + sla_overdue), 4)
        if (sla_within + sla_overdue) > 0
        else None
    )

    # Category distribution.
    category_index: dict[str, list] = defaultdict(list)
    for cid, _s, cat_v, _w, _c, _u, _b, _d in rows:
        category_index[_fmt(cat_v)].append(cid)
    categories: list[CategoryPoint] = []
    for cat, ids in category_index.items():
        r = len(resolved_ids & set(ids))
        categories.append(
            CategoryPoint(
                category=cat,
                total=len(ids),
                resolved=r,
                rate=round(r / len(ids), 4) if ids else 0.0,
            )
        )
    categories.sort(key=lambda c: c.total, reverse=True)

    # Ward distribution (all wards; scoped to the representative's ward when applicable).
    ward_rows = (await db.execute(select(Ward.id, Ward.name).order_by(Ward.name))).all()
    ward_index: dict[uuid.UUID | None, list] = defaultdict(list)
    for cid, _s, _cat, wid, _c, _u, _b, _d in rows:
        ward_index[wid].append(cid)
    wards: list[WardPoint] = []
    for wid, name in ward_rows:
        ids = ward_index.get(wid, [])
        r = len(resolved_ids & set(ids))
        wards.append(WardPoint(ward_id=wid, ward_name=name, total=len(ids), resolved=r))
    unassigned = ward_index.get(None, [])
    if unassigned:
        r = len(resolved_ids & set(unassigned))
        wards.append(
            WardPoint(
                ward_id=None,
                ward_name="Unassigned",
                total=len(unassigned),
                resolved=r,
            )
        )

    # Department performance.
    departments: list[DepartmentPoint] = []
    for dept, d in sorted(dept_index.items()):
        within = d["within"]
        overdue = d["overdue"]
        compliance = round(within / (within + overdue), 4) if (within + overdue) > 0 else None
        departments.append(
            DepartmentPoint(
                department=dept,
                total=d["total"],
                completed=d["completed"],
                avg_completion_seconds=_mean(d["completion"]),
                sla_within=within,
                sla_overdue=overdue,
                compliance_rate=compliance,
                escalated=d["escalated"],
            )
        )
    departments.sort(key=lambda d: d.total, reverse=True)

    # SLA performance by priority bucket.
    sla_performance: list[SlaPoint] = []
    for pr, s in sorted(sla_index.items()):
        sla_performance.append(
            SlaPoint(priority=pr, total=s["total"], within=s["within"], overdue=s["overdue"])
        )
    sla_performance.sort(key=lambda s: s.total, reverse=True)

    # Citizen satisfaction.
    sat_rows = (
        await db.execute(
            select(ComplaintRating.rating)
            .join(Complaint, Complaint.id == ComplaintRating.complaint_id)
            .where(*filters)
        )
    ).all()
    sat_values = [int(r[0]) for r in sat_rows]
    sat_counter = Counter(sat_values)
    satisfaction_distribution = [
        SatisfactionBucket(rating=rv, count=sat_counter.get(rv, 0)) for rv in range(1, 6)
    ]

    # Timeseries.
    points = []
    for cid, status_v, _cat, _w, created_at, updated_at, _b, _d in rows:
        res_at = resolution_map.get(cid)
        if res_at is None and status_v is not None and _fmt(status_v) in _RESOLVED_VALUES:
            if updated_at is not None and updated_at > created_at:
                res_at = updated_at
        points.append((created_at, res_at))
    start = date_from.date() if date_from else None
    end = date_to.date() if date_to else None
    series = _build_timeseries(points, start, end)

    ai_triaged_count = len(ai_triaged & set({r[0] for r in rows}))
    escalated_count = len(escalated & set({r[0] for r in rows}))

    kpis = AnalyticsKpis(
        total_complaints=total,
        resolved=resolved,
        resolution_rate=round(resolved / total, 4) if total else 0.0,
        response_seconds_avg=_mean(response_secs),
        response_seconds_median=_median(response_secs),
        response_count=len(response_secs),
        resolution_seconds_avg=_mean(resolution_secs),
        resolution_seconds_median=_median(resolution_secs),
        resolution_count=len(resolution_secs),
        sla_compliance_rate=sla_compliance_rate,
        sla_within=sla_within,
        sla_overdue=sla_overdue,
        sla_orders_with_deadline=sla_queue,
        ai_triaged=ai_triaged_count,
        ai_triage_rate=round(ai_triaged_count / total, 4) if total else 0.0,
        escalated=escalated_count,
        escalation_rate=round(escalated_count / total, 4) if total else 0.0,
        satisfaction_avg=round(sum(sat_values) / len(sat_values), 2) if sat_values else None,
        satisfaction_count=len(sat_values),
        satisfaction_distribution=satisfaction_distribution,
    )

    charts = AnalyticsCharts(
        complaints_over_time=series,
        resolution_trend=series,
        categories=categories,
        wards=wards,
        departments=departments,
        sla_performance=sla_performance,
    )

    return AnalyticsOverview(
        applied_filters=AnalyticsFilters(
            date_from=date_from,
            date_to=date_to,
            ward_id=ward_id,
            department=department,
            category=category,
            priority=priority,
        ),
        kpis=kpis,
        charts=charts,
    )


# --------------------------------------------------------------------------- #
# Heatmap
# --------------------------------------------------------------------------- #
async def get_heatmap(
    db: AsyncSession,
    user: User,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    ward_id: uuid.UUID | None = None,
    department: str | None = None,
    category: str | None = None,
    priority: str | None = None,
) -> HeatmapOut:
    filters = _complaint_filters(
        user,
        date_from=date_from,
        date_to=date_to,
        ward_id=ward_id,
        department=department,
        category=category,
        priority=priority,
    )
    priority_scalar = _latest_priority_priority()
    stmt = (
        select(
            ComplaintLocation.latitude,
            ComplaintLocation.longitude,
            priority_scalar.label("bucket"),
        )
        .join(Complaint, Complaint.id == ComplaintLocation.complaint_id)
        .where(
            ComplaintLocation.latitude.is_not(None),
            ComplaintLocation.longitude.is_not(None),
            *filters,
        )
    )
    loc_rows = (await db.execute(stmt)).all()

    grid: dict[tuple[float, float], dict] = defaultdict(lambda: {"count": 0, "weight": 0.0})
    precision = _HEATMAP_PRECISION
    for lat, lon, bucket in loc_rows:
        key = (round(lat / precision) * precision, round(lon / precision) * precision)
        cell = grid[key]
        cell["count"] += 1
        cell["weight"] += _PRIORITY_WEIGHT.get(bucket, 0.25)

    ordered = sorted(
        grid.items(), key=lambda item: (item[1]["count"], item[1]["weight"]), reverse=True
    )
    clusters = [
        HeatmapCluster(
            latitude=round(lat, 5),
            longitude=round(lon, 5),
            count=cell["count"],
            weight=round(cell["weight"], 2),
        )
        for (lat, lon), cell in ordered[:_MAX_HEATMAP_CLUSTERS]
    ]
    return HeatmapOut(total_points=len(loc_rows), clusters=clusters)


# --------------------------------------------------------------------------- #
# CSV export
# --------------------------------------------------------------------------- #
async def get_export_csv(
    db: AsyncSession,
    user: User,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    ward_id: uuid.UUID | None = None,
    department: str | None = None,
    category: str | None = None,
    priority: str | None = None,
) -> tuple[str, str]:
    filters = _complaint_filters(
        user,
        date_from=date_from,
        date_to=date_to,
        ward_id=ward_id,
        department=department,
        category=category,
        priority=priority,
    )
    rows, sub = await _base_rows(db, user, filters)
    maps = await _event_maps(db, sub)
    resolution_map: dict = maps["resolution_map"]
    response_map: dict = maps["response_map"]
    escalated: set = maps["escalated"]
    ai_triaged: set = maps["ai_triaged"]

    ward_names = {wid: name for wid, name in (await db.execute(select(Ward.id, Ward.name))).all()}

    rating_rows = (
        await db.execute(
            select(ComplaintRating.complaint_id, ComplaintRating.rating)
            .where(ComplaintRating.complaint_id.in_(sub))
        )
    ).all()
    ratings = {cid: int(rr) for cid, rr in rating_rows}

    resolved_now = {r[0] for r in rows if r[1] is not None and _fmt(r[1]) in _RESOLVED_VALUES}

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "complaint_id",
            "created_at",
            "status",
            "category",
            "ward",
            "priority_bucket",
            "department",
            "ai_triaged",
            "escalated",
            "resolved",
            "resolved_at",
            "response_seconds",
            "resolution_seconds",
            "rating",
        ]
    )
    for cid, status_v, cat_v, wid, created_at, updated_at, bucket, dept in rows:
        cid_str = str(cid)
        resolved_at = resolution_map.get(cid)
        if resolved_at is None and cid in resolved_now:
            if updated_at is not None and (created_at is None or updated_at > created_at):
                resolved_at = updated_at
            else:
                resolved_at = created_at
        response_at = response_map.get(cid)
        response_secs = (
            round((response_at - created_at).total_seconds(), 1)
            if response_at is not None and created_at is not None
            else ""
        )
        resolution_secs = (
            round((resolved_at - created_at).total_seconds(), 1)
            if resolved_at is not None and created_at is not None
            else ""
        )
        writer.writerow(
            [
                cid_str,
                created_at.isoformat() if created_at is not None else "",
                _fmt(status_v) if status_v is not None else "",
                _fmt(cat_v),
                ward_names.get(wid, ""),
                bucket if bucket is not None else "",
                dept if dept is not None else "",
                "true" if cid in ai_triaged else "false",
                "true" if cid in escalated else "false",
                "true" if (cid in resolved_now or cid in resolution_map) else "false",
                resolved_at.isoformat() if resolved_at is not None else "",
                response_secs,
                resolution_secs,
                ratings.get(cid, ""),
            ]
        )

    filename = f"analytics_complaints_{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return filename, buffer.getvalue()
