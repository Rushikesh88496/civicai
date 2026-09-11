"""Department Routing Agent (Part 13).

A *deterministic* LangGraph agent (no LLM) that assigns a complaint to one of the
seven fixed departments (WATER, ROADS, ELECTRICAL, WASTE, DRAINAGE, PARKS,
EMERGENCY_DISASTER) by fusing the complaint's category with the latest upstream
agent signals:

* **Triage** (``agent="triage"``) — severity + confidence.
* **Vision** (``agent="vision"``) — detected severity + confidence.
* **Priority** (``agent="priority"``) — score + bucket.
* **Context** (``agent="context"``) — weather + nearby infrastructure.

Routing is fully deterministic (``app.services.routing_engine``): category maps to
a primary department, multi-department issues (Flooding → Drainage + Roads; fallen
electrical infrastructure → Electrical + Emergency) attach secondary departments,
and confidence is derived from category clarity + corroborating signals.
Unrecognized / ambiguous categories are flagged for human review rather than being
silently mis-routed.

The graph is ``START → compute → persist → END``. A missing complaint is fatal;
every upstream signal degrades to neutral so a decision is always producible. Each
decision persists to ``agent_runs`` (``agent="routing"``) AND appends a row to
``complaint_department_history``, with ``changed`` set when the primary department
moves vs the previous effective decision (including any officer override).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.models import (
    AgentRun,
    Complaint,
    ComplaintDepartmentHistory,
    DepartmentOverride,
)
from app.models.enums import AgentStatus
from app.schemas.context import ContextOutput
from app.schemas.priority import PriorityOutput
from app.schemas.routing import RoutingInputs, RoutingOutput
from app.schemas.triage import TriageOutput
from app.schemas.vision import VisionOutput
from app.services import agent_run_service
from app.services.routing_engine import RoutingSignals, route_complaint

logger = logging.getLogger(__name__)

AGENT_NAME = "routing"


class RoutingState(TypedDict, total=False):
    """Graph state for the routing agent."""

    complaint_id: uuid.UUID
    db: AsyncSession
    settings: Settings
    run: AgentRun
    output: RoutingOutput | None
    fatal_error: bool
    error: str | None
    duration_ms: int | None
    event_log: list[tuple[str, dict | None]]


async def _latest_output(db, complaint_id, agent, model) -> Any | None:
    """Return the latest structured result of a specific upstream agent, if any."""
    run = await agent_run_service.get_latest_run_for_agent(db, complaint_id, agent)
    if run is None or run.structured_result is None:
        return None
    try:
        return model.model_validate(run.structured_result)
    except Exception as exc:  # noqa: BLE001 - malformed upstream degrades gracefully
        logger.warning("Could not parse %s result for %s: %s", agent, complaint_id, exc)
        return None


async def _current_effective_department(db: AsyncSession, complaint_id: uuid.UUID) -> str | None:
    """The department currently in effect for a complaint.

    The latest officer override (if any) wins; otherwise the most recent routing
    decision is used. Returns ``None`` when no routing or override exists yet.
    """
    override = await db.scalar(
        select(DepartmentOverride)
        .where(DepartmentOverride.complaint_id == complaint_id)
        .order_by(DepartmentOverride.overridden_at.desc())
        .limit(1)
    )
    if override is not None:
        return override.new_department
    routing = await db.scalar(
        select(ComplaintDepartmentHistory)
        .where(ComplaintDepartmentHistory.complaint_id == complaint_id)
        .order_by(ComplaintDepartmentHistory.calculated_at.desc())
        .limit(1)
    )
    return routing.primary_department if routing is not None else None


async def _compute_node(state: RoutingState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    settings: Settings = state["settings"]
    run: AgentRun = state["run"]
    complaint_id = state["complaint_id"]
    await agent_run_service._append_event(db, run, "routing.started", {"agent": AGENT_NAME})
    await db.flush()

    complaint = await db.scalar(
        select(Complaint).where(Complaint.id == complaint_id).options(selectinload(Complaint.ward))
    )
    if complaint is None:
        return {"fatal_error": True, "error": "Complaint no longer exists.", "output": None}

    category = complaint.category
    description = complaint.description or ""

    # Absorb the latest upstream signal runs (all degrade gracefully to neutral).
    triage = await _latest_output(db, complaint_id, "triage", TriageOutput)
    vision = await _latest_output(db, complaint_id, "vision", VisionOutput)
    priority = await _latest_output(db, complaint_id, "priority", PriorityOutput)
    context = await _latest_output(db, complaint_id, "context", ContextOutput)

    weather_condition: str | None = None
    infra_hospitals = infra_schools = infra_bus = 0
    if context is not None:
        weather_condition = context.weather_context.condition
        infra_hospitals = context.infrastructure_context.hospitals
        infra_schools = context.infrastructure_context.schools
        infra_bus = context.infrastructure_context.bus_stops

    signals = RoutingSignals(
        triage_severity=triage.severity.value if triage else None,
        triage_confidence=triage.confidence if triage else None,
        vision_severity=vision.severity.value if vision else None,
        vision_confidence=vision.confidence if vision else None,
        priority_score=priority.score if priority else None,
        priority_bucket=priority.priority.value if priority else None,
        weather_condition=weather_condition,
        infrastructure_hospitals=infra_hospitals,
        infrastructure_schools=infra_schools,
        infrastructure_bus_stops=infra_bus,
    )

    decision = route_complaint(
        category,
        description=description,
        signals=signals,
        settings=settings,
    )

    inputs = RoutingInputs(
        category=category.value,
        description_preview=(description[:80] + "…") if len(description) > 80 else description,
        triage_severity=signals.triage_severity,
        triage_confidence=signals.triage_confidence,
        vision_severity=signals.vision_severity,
        vision_confidence=signals.vision_confidence,
        priority_score=signals.priority_score,
        priority_bucket=signals.priority_bucket,
        weather_condition=signals.weather_condition,
        infrastructure_hospitals=signals.infrastructure_hospitals,
        infrastructure_schools=signals.infrastructure_schools,
        infrastructure_bus_stops=signals.infrastructure_bus_stops,
    )

    previous_dept = await _current_effective_department(db, complaint_id)
    changed = previous_dept is not None and previous_dept != decision.primary_department.value
    multi_note = (
        f" Collaboration: {', '.join(decision.secondary_values)}."
        if decision.secondary_values
        else ""
    )
    summary = (
        f"RN → {decision.primary_department.value} (confidence "
        f"{decision.confidence:.2f}).{multi_note}"
    )

    output = RoutingOutput(
        primary_department=decision.primary_department.value,
        secondary_departments=decision.secondary_values,
        routing_reason=decision.routing_reason,
        confidence=decision.confidence,
        ambiguous=decision.ambiguous,
        inputs=inputs,
        previous_department=previous_dept,
        changed=changed,
        summary=summary,
    )
    return {"output": output, "fatal_error": False, "error": None}


async def _persist_node(state: RoutingState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    run: AgentRun = state["run"]
    complaint_id = state["complaint_id"]
    output: RoutingOutput = state["output"]
    events: list[tuple[str, dict | None]] = state.get("event_log", [])
    failed = bool(state.get("fatal_error"))
    status = AgentStatus.FAILED if failed else AgentStatus.SUCCEEDED

    if not failed:
        db.add(
            ComplaintDepartmentHistory(
                complaint_id=complaint_id,
                primary_department=output.primary_department,
                secondary_departments=output.secondary_departments,
                routing_reason=output.routing_reason,
                confidence=output.confidence,
                ambiguous=output.ambiguous,
                inputs={
                    "category": output.inputs.category,
                    "prev_department": output.previous_department,
                    "changed": output.changed,
                    "signals": {
                        "triage_severity": output.inputs.triage_severity,
                        "vision_severity": output.inputs.vision_severity,
                        "priority_bucket": output.inputs.priority_bucket,
                        "priority_score": output.inputs.priority_score,
                        "weather_condition": output.inputs.weather_condition,
                        "hospitals": output.inputs.infrastructure_hospitals,
                        "schools": output.inputs.infrastructure_schools,
                        "bus_stops": output.inputs.infrastructure_bus_stops,
                    },
                },
            )
        )
        events.append(
            (
                "routing.computed",
                {
                    "primary": output.primary_department,
                    "secondary": output.secondary_departments,
                    "confidence": output.confidence,
                    "ambiguous": output.ambiguous,
                    "changed": output.changed,
                    "previous": output.previous_department,
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
    else:
        await agent_run_service.finalize_run(
            db,
            run,
            status=status,
            result=None,
            error=state.get("error"),
            duration_ms=state.get("duration_ms"),
            events=events,
        )
    return {}


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #
def build_graph() -> Any:
    graph = StateGraph(RoutingState)
    graph.add_node("compute", _compute_node)
    graph.add_node("persist", _persist_node)
    graph.add_edge(START, "compute")
    graph.add_edge("compute", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
class RoutingAgent:
    """Orchestrator that runs the deterministic department-routing graph."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        graph: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._graph = graph if graph is not None else build_graph()

    async def run(self, db: AsyncSession, *, complaint_id: uuid.UUID) -> AgentRun:
        started = time.monotonic()
        run = await agent_run_service.create_run(
            db, complaint_id=complaint_id, agent=AGENT_NAME, model=None
        )
        await agent_run_service._append_event(db, run, "run.started", {"agent": AGENT_NAME})
        await db.commit()
        run_id = run.id

        state: RoutingState = {
            "complaint_id": complaint_id,
            "db": db,
            "settings": self._settings,
            "run": run,
            "fatal_error": False,
            "error": None,
            "output": None,
            "duration_ms": None,
            "event_log": [],
        }
        await self._graph.ainvoke(state)

        duration = int((time.monotonic() - started) * 1000)
        reloaded = await agent_run_service.get_run_with_events(db, run_id)
        if reloaded is not None and reloaded.duration_ms is None:
            reloaded.duration_ms = duration
            await db.commit()
        return reloaded or run
