"""Dispatch Agent (Part 14) — creates a draft work order + worker recommendation.

A deterministic LangGraph agent (no LLM). It:

1. Reads the routed ``department`` (via the complaint's effective department),
   the complaint's dynamic priority, and its location.
2. Enumerates eligible field workers and scores them with the deterministic
   dispatch engine against availability / skill / distance / workload /
   equipment (never random).
3. Computes an honest ETA via the routing abstraction
   (``source="live"`` only if a live provider answered; otherwise the documented
   estimate with ``source="estimated"``).
4. Persists a **draft** ``WorkOrder`` (``PENDING_APPROVAL``) with the recommended
   worker + ETA + a ``DISPATCH`` status-history row, and stores the full
   ``DispatchOutput`` to ``agent_runs`` (``agent="dispatch"``).

The order is a *draft*: an officer must approve it before it becomes active.
A draft with no eligible worker is still created but flagged, so escalation is
possible; a route with no worker is deferred for officer review.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import replace
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.notification_types import (
    EVENT_P1_ALERT,
    EVENT_WORK_ORDER_CREATED,
)
from app.models import (
    AgentRun,
    Complaint,
    ComplaintLocation,
    ComplaintPriorityHistory,
    FieldWorker,
    User,
    Ward,
    WorkOrder,
    WorkOrderStatusHistory,
)
from app.models.enums import (
    AgentStatus,
    DynamicPriority,
    RoleName,
    WorkerStatus,
    WorkOrderAction,
    WorkOrderStatus,
)
from app.schemas.work_order import (
    CandidateScoreOut,
    DispatchInputs,
    DispatchOutput,
    DispatchRecommendation,
)
from app.services import agent_run_service
from app.services.ai_governance_service import PROMPT_VERSION_DISPATCH, log_ai_decision
from app.services.audit_service import ACTION_WORK_ORDER_DISPATCH, record_audit
from app.services.classification_service import _rules_department
from app.services.complaint_tracking_service import get_effective_department
from app.services.dispatch_engine import CandidateInput, rank_candidates
from app.services.eta_service import estimate_eta
from app.services.evidence_validation_service import validate_department_claim
from app.services.notification_service import active_users_by_role, notify

logger = logging.getLogger(__name__)

AGENT_NAME = "dispatch"


class DispatchState(TypedDict, total=False):
    """Graph state for the dispatch agent."""

    complaint_id: uuid.UUID
    db: AsyncSession
    settings: Settings
    run: AgentRun
    created_by: uuid.UUID | None
    work_order_id: uuid.UUID | None
    output: DispatchOutput | None
    fatal_error: bool
    error: str | None
    duration_ms: int | None
    event_log: list[tuple[str, dict | None]]


async def _load_workers(db: AsyncSession) -> list[CandidateInput]:
    """Load all ACTIVE field workers with their crew, home ward, base and workloads."""
    rows = (
        (
            await db.execute(
                select(FieldWorker)
                .where(FieldWorker.status == WorkerStatus.ACTIVE.value)
                .options(
                    selectinload(FieldWorker.user).selectinload(User.ward),
                    selectinload(FieldWorker.department),
                    selectinload(FieldWorker.assignments),
                )
            )
        )
        .scalars()
        .all()
    )

    candidates: list[CandidateInput] = []
    for fw in rows:
        active = [a for a in fw.assignments if str(a.status) in ("ASSIGNED", "REASSIGNED")]
        user: User = fw.user
        candidates.append(
            CandidateInput(
                worker_id=fw.id,
                name=user.full_name,
                department_code=fw.department.code if fw.department else None,
                status=WorkerStatus(fw.status),
                specialty=fw.specialty,
                skill_tags=list(fw.skill_tags or []),
                equipment=list(fw.equipment or []),
                home_lat=fw.home_latitude,
                home_lon=fw.home_longitude,
                active_orders=len(active),
                max_active_orders=fw.max_active_orders,
                ward_code=user.ward.code if user.ward else None,
            )
        )
    return candidates


async def _postgis_distances(
    db: AsyncSession,
    worker_ids: list[uuid.UUID],
    lat: float | None,
    lon: float | None,
) -> dict[uuid.UUID, float]:
    """Kilometre distance each worker is from the order location, via PostGIS.

    Uses ``ST_Distance`` on the geography cast so the number is on the WGS84
    ellipsoid. Returns an empty dict when PostGIS is unavailable or the order
    has no coordinates — the engine then falls back to in-process haversine.
    """
    if lat is None or lon is None or not worker_ids:
        return {}
    origin = text("ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography")
    stmt = text(
        "SELECT id::text AS wid, "
        "ST_Distance({origin}, "
        "ST_SetSRID(ST_MakePoint(home_longitude, home_latitude), 4326)::geography) "
        "/ 1000.0 AS km "
        "FROM field_workers "
        "WHERE id::text = ANY(:ids)".format(origin=origin)
    )
    try:
        rows = await db.execute(
            stmt, {"lon": lon, "lat": lat, "ids": [str(wid) for wid in worker_ids]}
        )
    except Exception:  # PostGIS unavailable — caller falls back to haversine.
        return {}
    return {uuid.UUID(r.wid): float(r.km) for r in rows}


async def _load_complaint_location(
    db: AsyncSession, complaint_id: uuid.UUID
) -> tuple[float | None, float | None, str | None]:
    loc = await db.scalar(
        select(ComplaintLocation).where(ComplaintLocation.complaint_id == complaint_id)
    )
    if loc is None:
        return None, None, None
    return loc.latitude, loc.longitude, loc.address


def _required_from_department(department: str) -> tuple[list[str], list[str]]:
    """Default required skills + equipment for a routing department.

    A pragmatic, deterministic default; officers may override skills later. The
    canonical routing tags come first, followed by the vocabulary the real
    seeded crews (PW/SN/PR) actually carry (e.g. ``road-maintenance``,
    ``garbage-collection``), so the skill criterion connects to the 25 real
    field workers instead of scoring them ~0 on vocabulary mismatch.
    """
    mapping: dict[str, tuple[list[str], list[str]]] = {
        "WATER": (
            [
                "plumbing", "pipe-repair",
                "water-line-repair", "pipeline", "valve",
                "water-leak-repair", "shutoff-valve",
            ],
            ["pump", "excavator", "pipe-cutter", "pipe-clamp"],
        ),
        "ROADS": (
            [
                "pavement", "paving",
                "road-maintenance", "asphalt", "patching",
                "pothole-repair", "cold-mix", "paver-block",
                "footpath-repair", "road-inspection", "pavement-assessment",
            ],
            ["excavator", "compactor", "road-roller", "asphalt-paver", "paver-block-setter"],
        ),
        "ELECTRICAL": (
            [
                "electrical-line", "wiring",
                "electrical", "electrical-maintenance", "feeder", "panel",
                "streetlight-repair", "lamp",
            ],
            ["bucket-truck", "insulated-tools", "boom-truck", "voltage-tester", "insulated-gloves"],
        ),
        "WASTE": (
            [
                "waste-audit", "collections",
                "garbage-collection", "waste-management", "segregation", "landfill",
                "street-cleaning", "sweeping",
            ],
            ["garbage-truck", "broom", "compactor-truck", "street-sweeper-vehicle"],
        ),
        "DRAINAGE": (
            [
                "drainage", "jetted-outfall",
                "sewer-maintenance", "manhole", "jetting-rig",
                "drain-cleaning", "drainage-jetting",
            ],
            ["jetting-rig", "manhole-tool", "manhole-lift"],
        ),
        "PARKS": (
            [
                "landscaping", "tree-care",
                "civic-assets", "maintenance", "public-infrastructure",
            ],
            ["chainsaw", "pruner", "hand-tools", "app-phone"],
        ),
        "EMERGENCY_DISASTER": (
            ["emergency-response", "first-responder"],
            ["rescue-kit", "generator"],
        ),
    }
    return mapping.get(department.upper(), (["general-maintenance"], []))


def _explanation_for(best: CandidateScoreOut) -> str:
    """One-sentence, deterministic explanation of the recommended worker's pick.

    Built ONLY from the actual scored candidate data (never hardcoded, never raw
    model chain-of-thought): skill match, department ownership, availability,
    ward match, active-assignment count, and distance from the complaint.
    """
    skill_txt = (
        "fully covers the required skills"
        if best.skill >= 0.999
        else f"matches {best.skill * 100:.0f}% of the required skills"
    )
    dept_txt = (
        f"belongs to the {best.department_code} department that owns this work"
        if best.department_code and best.department >= 1.0
        else f"belongs to the {best.department_code or 'general'} department"
    )
    avail_txt = "is available" if best.available else "is currently unavailable"
    ward_txt = (
        f"operates in the required {best.ward_code} ward"
        if best.ward_code and best.ward >= 1.0
        else "is based outside the complaint's ward"
    )
    load_txt = (
        f"currently has {best.active_orders} active assignment(s)"
        if best.capacity is not None
        else "has a favourable current workload"
    )
    dist_txt = (
        f"is about {best.distance_km:.1f} km from the complaint"
        if best.distance_km is not None
        else f"scores {best.distance * 100:.0f}% on proximity"
    )
    return (
        f"Recommended because {best.name} {skill_txt}, {dept_txt}, {avail_txt}, "
        f"{ward_txt}, {load_txt}, and {dist_txt}."
    )


async def _compute_node(state: DispatchState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    settings: Settings = state["settings"]
    run: AgentRun = state["run"]
    complaint_id = state["complaint_id"]
    await agent_run_service._append_event(db, run, "dispatch.started", {"agent": AGENT_NAME})
    await db.flush()

    complaint = await db.scalar(select(Complaint).where(Complaint.id == complaint_id))
    if complaint is None:
        return {"fatal_error": True, "error": "Complaint no longer exists.", "output": None}

    department = await get_effective_department(db, complaint_id)
    if not department:
        # No routing decision yet — fall back to the complaint category-driven
        # department from a routing run if present, else defer.
        department = _department_from_category(complaint.category.value)

    lat, lon, address = await _load_complaint_location(db, complaint_id)
    incident = (complaint.title or "")[:200]
    priority = complaint.priority.value if complaint.priority else None
    # The complaint's ward drives the "ward match" factor; the dynamic priority
    # bucket (P1..P4, when available) drives the urgency factor.
    ward_code = await db.scalar(
        select(Ward.code)
        .join(Complaint, Complaint.ward_id == Ward.id)
        .where(Complaint.id == complaint_id)
    )
    priority_signal = await _latest_dynamic_priority(db, complaint_id) or priority

    skills, equipment = _required_from_department(department)
    candidates = await _load_workers(db)
    # Real PostGIS distances (ellipsoidal); empty when PostGIS unavailable, in
    # which case the engine falls back to in-process haversine.
    distances = await _postgis_distances(db, [c.worker_id for c in candidates], lat, lon)
    if distances:
        candidates = [
            replace(c, precomputed_distance_km=distances[c.worker_id])
            if c.worker_id in distances
            else c
            for c in candidates
        ]

    if not getattr(state, "dispatch_live", True) or not settings.DISPATCH_ENABLED:
        no_worker = "Unavailable while dispatch is disabled."
        rec = DispatchRecommendation(
            department=department,
            priority=priority,
            recommended_action=f"Address {incident or department} incident.",
            required_skills=skills,
            required_equipment=equipment,
            recommended_worker_id=None,
            candidates=[],
            no_worker_reason=no_worker,
        )
        return {
            "output": DispatchOutput(
                recommendation=rec,
                inputs=DispatchInputs(
                    complaint_id=complaint_id,
                    department=department,
                    priority=priority,
                    required_skills=skills,
                    required_equipment=equipment,
                    lat=lat,
                    lon=lon,
                    incident=incident,
                ),
            ),
            "fatal_error": False,
            "error": None,
        }

    scored = rank_candidates(
        candidates,
        required_skills=skills,
        required_equipment=equipment,
        order_lat=lat,
        order_lon=lon,
        department=department,
        order_ward=ward_code,
        priority=priority_signal,
        settings=settings,
    )

    recommended_worker_id: uuid.UUID | None = None
    recommended_worker_name: str | None = None
    no_worker_reason: str | None = None

    best = scored[0] if scored else None
    if best is not None and best.available:
        recommended_worker_id = best.worker_id
        recommended_worker_name = best.name
    else:
        recommended_worker_id = None
        recommended_worker_name = None
        no_worker_reason = (
            "No suitable workers available — every candidate is currently busy "
            "or at capacity. Review candidates or escalate."
        )

    candidate_outs = [
        CandidateScoreOut(
            worker_id=c.worker_id,
            name=c.name,
            score=c.score,
            available=c.available,
            availability=c.availability,
            skill=c.skill,
            distance=c.distance,
            workload=c.workload,
            equipment=c.equipment,
            department=c.department,
            ward=c.ward,
            priority=c.priority,
            distance_km=c.distance_km,
            department_code=c.department_code,
            ward_code=c.ward_code,
            active_orders=c.active_orders,
            capacity=c.capacity,
            reasons=list(c.reasons),
        )
        for c in scored
    ]

    # SLA deadline resolved from the runtime-configurable policy rulebook
    # (Part 20) — most specific match of (priority, department, category).
    sla_hours = await _resolve_sla_hours(
        db, priority=priority, department=department, category=complaint.category.value
    )

    rec = DispatchRecommendation(
        department=department,
        priority=priority,
        recommended_action=f"Dispatch field crew for {incident or department}.",
        required_skills=skills,
        required_equipment=equipment,
        recommended_worker_id=recommended_worker_id,
        recommended_worker_name=recommended_worker_name,
        recommended_worker_explanation=(
            _explanation_for(candidate_outs[0])
            if recommended_worker_id is not None and candidate_outs
            else None
        ),
        candidates=candidate_outs,
        sla_hours=sla_hours,
        eta_minutes=None,
        eta_source=None,
        no_worker_reason=no_worker_reason,
    )

    # Resolve the home coords of the recommended worker for an honest ETA.
    if recommended_worker_id is not None and lat is not None and lon is not None:
        for cand in candidates:
            if (
                cand.worker_id == recommended_worker_id
                and cand.home_lat is not None
                and cand.home_lon is not None
            ):
                eta = await estimate_eta(
                    origin_lat=cand.home_lat,
                    origin_lon=cand.home_lon,
                    dest_lat=lat,
                    dest_lon=lon,
                    settings=settings,
                )
                rec.eta_minutes = eta.minutes
                rec.eta_source = eta.source
                break

    output = DispatchOutput(
        recommendation=rec,
        inputs=DispatchInputs(
            complaint_id=complaint_id,
            department=department,
            priority=priority,
            required_skills=skills,
            required_equipment=equipment,
            lat=lat,
            lon=lon,
            incident=incident,
        ),
    )
    return {"output": output, "fatal_error": False, "error": None}


def _department_from_category(category: str) -> str:
    mapping = {
        "WATER": "WATER",
        "WATER_LEAK": "WATER",
        "ROAD": "ROADS",
        "ELECTRICITY": "ELECTRICAL",
        "STREET_LIGHTING": "ELECTRICAL",
        "GARBAGE": "WASTE",
        "SANITATION": "WASTE",
        "DRAINAGE": "DRAINAGE",
        "FLOODING": "DRAINAGE",
        "PARKS": "PARKS",
        "FALLEN_TREE": "PARKS",
        "PUBLIC_SAFETY": "EMERGENCY_DISASTER",
    }
    return mapping.get(category.upper(), "DRAINAGE")


async def _resolve_sla_hours(
    db: AsyncSession,
    *,
    priority: str | None,
    department: str,
    category: str | None,
) -> int | None:
    """Resolve the SLA deadline (hours) from the configurable rulebook (Part 20).

    Replaces the old hard-coded P1=24/P2=48/P3=72/P4=168 mapping. The built-in
    priority rules seeded by the ``e2e3f4a5b6c7`` migration preserve that
    behavior out-of-the-box, and officers can add more specific
    department/category rules on top.
    """
    from app.services import sla_policy_service

    policy = await sla_policy_service.resolve(
        db, priority=priority, department=department, category=category
    )
    if policy is None:
        return None
    return policy.sla_hours


async def _latest_dynamic_priority(db: AsyncSession, complaint_id: uuid.UUID) -> str | None:
    """The most recent deterministically-computed priority bucket (P1..P4)."""
    row = await db.scalar(
        select(ComplaintPriorityHistory)
        .where(ComplaintPriorityHistory.complaint_id == complaint_id)
        .order_by(ComplaintPriorityHistory.calculated_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    return row.priority.value if hasattr(row.priority, "value") else str(row.priority)


def _is_p1(priority: str | None, bucket: str | None) -> bool:
    return (bucket == DynamicPriority.P1_CRITICAL.value) or (priority or "").startswith("P1")


async def _notify_created(
    db: AsyncSession,
    complaint_id: uuid.UUID,
    order: WorkOrder,
    rec: DispatchRecommendation,
) -> None:
    """Notify the citizen a work order was created; alert staff on P1 (Part 21)."""
    link = f"/officer/work-orders/{order.id}"
    complaint = await db.scalar(select(Complaint).where(Complaint.id == complaint_id))
    owner = None
    if complaint is not None:
        owner = await db.get(User, complaint.user_id)
        inc = order.incident or "your complaint"
        if owner is not None and owner.is_active:
            await notify(
                db,
                targets=[owner],
                event=EVENT_WORK_ORDER_CREATED,
                complaint_id=complaint_id,
                work_order_id=order.id,
                body=f"A work order for '{inc}' was created and awaits approval.",
                link=link,
            )

    bucket = await _latest_dynamic_priority(db, complaint_id)
    if _is_p1(rec.priority, bucket):
        staff = await active_users_by_role(db, RoleName.OFFICER.value, RoleName.ADMIN.value)
        if staff:
            await notify(
                db,
                targets=staff,
                event=EVENT_P1_ALERT,
                complaint_id=complaint_id,
                work_order_id=order.id,
                body=(
                    f"P1 work order created for '{order.incident or complaint_id}'. "
                    "Requires immediate approval."
                ),
                link=link,
            )


async def _persist_node(state: DispatchState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    run: AgentRun = state["run"]
    complaint_id = state["complaint_id"]
    created_by = state.get("created_by")
    output: DispatchOutput = state["output"]
    events: list[tuple[str, dict | None]] = state.get("event_log", [])
    failed = bool(state.get("fatal_error"))
    status = AgentStatus.FAILED if failed else AgentStatus.SUCCEEDED

    if not failed and output is not None:
        rec = output.recommendation
        loc = await db.scalar(
            select(ComplaintLocation).where(ComplaintLocation.complaint_id == complaint_id)
        )
        address = loc.address if loc is not None else None
        order = WorkOrder(
            complaint_id=complaint_id,
            incident=output.inputs.incident,
            department=rec.department,
            priority=rec.priority,
            location_lat=output.inputs.lat,
            location_lon=output.inputs.lon,
            address=address or output.inputs.incident,
            sla_hours=rec.sla_hours,
            recommended_action=rec.recommended_action,
            status=WorkOrderStatus.PENDING_APPROVAL,
            eta_minutes=rec.eta_minutes,
            eta_source=rec.eta_source,
            worker_id=rec.recommended_worker_id,
            recommended_worker_id=rec.recommended_worker_id,
            created_by=created_by,
        )
        db.add(order)
        await db.flush()

        db.add(
            WorkOrderStatusHistory(
                work_order_id=order.id,
                action=WorkOrderAction.DISPATCH.value,
                from_status=None,
                to_status=WorkOrderStatus.PENDING_APPROVAL,
                actor_id=created_by,
                note="Draft work order created by the dispatch agent.",
            )
        )
        await _notify_created(db, complaint_id, order, rec)
        events.append(
            (
                "dispatch.created",
                {
                    "work_order_id": str(order.id),
                    "department": rec.department,
                    "worker": rec.recommended_worker_name,
                    "eta_minutes": rec.eta_minutes,
                    "eta_source": rec.eta_source,
                    "candidates": len(rec.candidates),
                    "no_worker": bool(rec.no_worker_reason),
                },
            )
        )
        await agent_run_service.finalize_run(
            db,
            run,
            status=status,
            result=output,
            error=None,
            duration_ms=state.get("duration_ms"),
            events=events,
        )
        # Return the created draft id through graph state so the runner can report it.
        return {"work_order_id": order.id, "output": output}
    else:
        await agent_run_service.finalize_run(
            db,
            run,
            status=status,
            result=output,
            error=state.get("error"),
            duration_ms=state.get("duration_ms"),
            events=events,
        )
    return {}


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #
def build_graph() -> Any:
    graph = StateGraph(DispatchState)
    graph.add_node("compute", _compute_node)
    graph.add_node("persist", _persist_node)
    graph.add_edge(START, "compute")
    graph.add_edge("compute", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
class DispatchAgent:
    """Orchestrator that runs the deterministic dispatch graph."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        graph: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._graph = graph if graph is not None else build_graph()

    async def run(self, db: AsyncSession, *, complaint_id: uuid.UUID, created_by: uuid.UUID):
        started = time.monotonic()
        run = await agent_run_service.create_run(
            db, complaint_id=complaint_id, agent=AGENT_NAME, model=None
        )
        await agent_run_service._append_event(db, run, "run.started", {"agent": AGENT_NAME})
        await db.commit()
        run_id = run.id

        state: DispatchState = {
            "complaint_id": complaint_id,
            "db": db,
            "settings": self._settings,
            "run": run,
            "created_by": created_by,
            "fatal_error": False,
            "error": None,
            "output": None,
            "duration_ms": None,
            "event_log": [],
            "work_order_id": None,
        }
        final_state = await self._graph.ainvoke(state)
        work_order_id = (final_state or {}).get("work_order_id")

        await self._log_governance(db, final_state, complaint_id)
        duration = int((time.monotonic() - started) * 1000)
        reloaded = await agent_run_service.get_run_with_events(db, run_id)
        if reloaded is not None and reloaded.duration_ms is None:
            reloaded.duration_ms = duration
            await db.commit()
        return reloaded or run, work_order_id

    async def _log_governance(
        self,
        db: AsyncSession,
        state: DispatchState,
        complaint_id: uuid.UUID,
    ) -> None:
        """Part 28 — persist the dispatch AI decision + evidence + audit."""
        output: DispatchOutput | None = state.get("output")
        if output is None or state.get("fatal_error"):
            return

        decision = await log_ai_decision(
            db,
            complaint_id=complaint_id,
            agent_name=AGENT_NAME,
            model_name="deterministic-dispatch-v1",
            prompt_version=PROMPT_VERSION_DISPATCH,
            input_summary=output.inputs.incident[:500] or None,
            output_summary=output.recommendation.recommended_action,
            confidence=1.0 if not output.recommendation.no_worker_reason else 0.0,
            result=output.model_dump(mode="json"),
            duration_ms=state.get("duration_ms"),
        )
        if state.get("work_order_id"):
            await record_audit(
                db,
                actor_id=state.get("created_by"),
                action=ACTION_WORK_ORDER_DISPATCH,
                entity_type="work_order",
                entity_id=str(state["work_order_id"]),
                after={
                    "complaint_id": str(complaint_id),
                    "department": output.recommendation.department,
                    "worker": output.recommendation.recommended_worker_name,
                },
            )

        # Evidence cross-check: routed department vs deterministic rules map.
        complaint = await db.scalar(select(Complaint).where(Complaint.id == complaint_id))
        if complaint is not None:
            claimed_dept = output.recommendation.department
            actual_dept = _rules_department(complaint.category.value)
            await validate_department_claim(
                db,
                complaint_id=complaint_id,
                decision_id=decision.id,
                claimed_department=claimed_dept.split()[0] if claimed_dept else None,
                actual_department=actual_dept.split()[0],
            )
