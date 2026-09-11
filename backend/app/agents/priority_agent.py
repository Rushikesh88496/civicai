"""Dynamic Priority & Risk Engine agent (Part 12).

A *deterministic* LangGraph agent (no LLM) that computes a 0..100 priority score
and a ``DynamicPriority`` bucket for a complaint from the seven priority inputs:

* **Severity** — the complaint's stored severity (``complaint.priority``, already
  set by the triage agent as an input; the engine never lets an LLM pick the
  numeric score).
* **Population impact** — number of residents linked to the complaint's ward
  (a deterministic population proxy).
* **Critical infrastructure proximity** — hospitals / schools / bus stops near
  the location (reused from the Part 11 context agent's infrastructure summary).
* **Weather** — current condition + rainfall from the Part 11 context agent
  (Open-Meteo), stored in the last ``agent="context"`` run.
* **Complaint count** — prior complaints near the location (context historical).
* **Historical recurrence** — prior complaints in the same ward (context).
* **Time unresolved** — age of the complaint in the pipeline (now - created_at).

Scoring is *fully deterministic* (``app.services.priority_engine``): each input
normalizes to a 0..1 unit, is weighted by a configurable weight, and the
weighted sum (re-normalized over present inputs) becomes the rounded 0..100
score. The result persists to ``agent_runs`` (``agent="priority"``) AND appends a
row to ``complaint_priority_history`` so the UI can show a score history and
detect significant re-prioritizations (a >=``PRIORITY_CHANGE_THRESHOLD`` move
flags ``changed=True``).

The graph is ``START → compute → persist → END``. A missing complaint is fatal;
every downstream signal degrades to a neutral default so the score is always
producible.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.models import (
    AgentRun,
    Complaint,
    ComplaintPriorityHistory,
    User,
)
from app.models.enums import AgentStatus, DynamicPriority
from app.schemas.context import ContextOutput
from app.schemas.priority import (
    PriorityFactor,
    PriorityOutput,
    PrioritySignalInputs,
)
from app.services import agent_run_service
from app.services.priority_engine import Weights, score_priority

logger = logging.getLogger(__name__)

AGENT_NAME = "priority"


class PriorityState(TypedDict, total=False):
    """Graph state for the priority engine agent."""

    complaint_id: uuid.UUID
    db: AsyncSession
    settings: Settings
    run: AgentRun
    output: PriorityOutput | None
    fatal_error: bool
    error: str | None
    duration_ms: int | None
    event_log: list[tuple[str, dict | None]]


def _weights(settings: Settings) -> Weights:
    return Weights(
        severity=float(settings.PRIORITY_WEIGHT_SEVERITY),
        weather=float(settings.PRIORITY_WEIGHT_WEATHER),
        location=float(settings.PRIORITY_WEIGHT_LOCATION),
        crowd=float(settings.PRIORITY_WEIGHT_CROWD),
        history=float(settings.PRIORITY_WEIGHT_HISTORY),
        time=float(settings.PRIORITY_WEIGHT_TIME),
    )


async def _load_context(db: AsyncSession, complaint_id: uuid.UUID) -> ContextOutput | None:
    """Return the latest ``context`` agent result for the complaint, if any."""
    run = await agent_run_service.get_latest_run(db, complaint_id)
    if run is None or run.agent != "context" or run.structured_result is None:
        return None
    try:
        return ContextOutput.model_validate(run.structured_result)
    except Exception as exc:  # noqa: BLE001 - malformed context degrades gracefully
        logger.warning("Could not parse context result for %s: %s", complaint_id, exc)
        return None


async def _ward_resident_count(db: AsyncSession, ward_id: uuid.UUID | None) -> int:
    """Count users linked to the complaint's ward (population proxy)."""
    if ward_id is None:
        return 0
    return int(await db.scalar(select(func.count(User.id)).where(User.ward_id == ward_id)) or 0)


async def _compute_node(state: PriorityState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    settings: Settings = state["settings"]
    run: AgentRun = state["run"]
    complaint_id = state["complaint_id"]
    await agent_run_service._append_event(db, run, "priority.started", {"agent": AGENT_NAME})
    await db.flush()

    complaint = await db.scalar(
        select(Complaint)
        .where(Complaint.id == complaint_id)
        .options(selectinload(Complaint.ward), selectinload(Complaint.complaint_location))
    )
    if complaint is None:
        return {"fatal_error": True, "error": "Complaint no longer exists.", "output": None}

    ward_id = complaint.ward_id

    # Population impact = residents in the same ward.
    population = await _ward_resident_count(db, ward_id)

    # Weather / infrastructure / historical inputs from the latest context run.
    context = await _load_context(db, complaint_id)
    hospitals = schools = bus_stops = 0
    weather_condition: str | None = None
    rain_mm: float | None = None
    weather_available = False
    complaint_count = 0
    historical_recurrence: int | None = None
    ward_resolved = False
    if context is not None:
        infra = context.infrastructure_context
        hospitals = infra.hospitals
        schools = infra.schools
        bus_stops = infra.bus_stops
        weather = context.weather_context
        weather_condition = weather.condition
        rain_mm = weather.rain_mm if weather.rain_mm is not None else weather.precipitation_mm
        weather_available = weather.available
        historical = context.historical_context
        complaint_count = historical.total_prior
        historical_recurrence = historical.same_ward_count
        ward_resolved = historical.ward_resolved or (ward_id is not None)

    # Time unresolved (hours) — deterministic age in the pipeline.
    time_hours = 0.0
    if complaint.created_at is not None:
        age = datetime.now(UTC) - complaint.created_at
        time_hours = max(0.0, age.total_seconds() / 3600.0)

    severity = complaint.priority.value if complaint.priority is not None else "LOW"

    inputs = PrioritySignalInputs(
        severity=severity,
        population=population,
        hospitals=hospitals,
        schools=schools,
        bus_stops=bus_stops,
        weather_condition=weather_condition,
        rain_mm=rain_mm,
        weather_available=weather_available,
        complaint_count=complaint_count,
        historical_recurrence=historical_recurrence if historical_recurrence is not None else 0,
        ward_resolved=ward_resolved,
        time_unresolved_hours=time_hours,
    )

    score, bucket, factor_dicts = score_priority(
        severity=severity,
        population=population,
        hospitals=hospitals,
        schools=schools,
        bus_stops=bus_stops,
        weather_condition=weather_condition,
        rain_mm=rain_mm,
        weather_available=weather_available,
        complaint_count=complaint_count,
        historical_recurrence=historical_recurrence,
        ward_resolved=ward_resolved,
        time_unresolved_hours=time_hours,
        weights=_weights(settings),
        threshold_p1=float(settings.PRIORITY_THRESHOLD_P1),
        threshold_p2=float(settings.PRIORITY_THRESHOLD_P2),
        threshold_p3=float(settings.PRIORITY_THRESHOLD_P3),
        weather_rain_mm=float(settings.PRIORITY_WEATHER_RAIN_MM),
        population_band=float(settings.PRIORITY_POPULATION_BAND),
        complaint_band=float(settings.PRIORITY_COMPLAINT_BAND),
        history_band=float(settings.PRIORITY_HISTORY_BAND),
        time_band_hours=float(settings.PRIORITY_TIME_BAND_HOURS),
    )

    factors = [PriorityFactor(**f) for f in factor_dicts]

    # Change detection vs the previous computation.
    previous = await _latest_history_entry(db, complaint_id)
    prev_score = previous.score if previous is not None else None
    prev_priority = DynamicPriority(previous.priority.value) if previous is not None else None
    changed_base = float(settings.PRIORITY_CHANGE_THRESHOLD)
    changed = prev_score is None or abs(score - prev_score) >= changed_base

    summary = (
        f"Priority {bucket.value} score {score}/100 — biggest driver: "
        f"{(factors[0].factor if factors else 'none')}."
    )

    output = PriorityOutput(
        score=score,
        priority=bucket,
        factors=factors,
        inputs=inputs,
        previous_score=prev_score,
        previous_priority=prev_priority,
        changed=changed,
        summary=summary,
    )
    return {"output": output, "fatal_error": False, "error": None}


async def _latest_history_entry(
    db: AsyncSession, complaint_id: uuid.UUID
) -> ComplaintPriorityHistory | None:
    return await db.scalar(
        select(ComplaintPriorityHistory)
        .where(ComplaintPriorityHistory.complaint_id == complaint_id)
        .order_by(ComplaintPriorityHistory.calculated_at.desc())
        .limit(1)
    )


async def _persist_node(state: PriorityState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    run: AgentRun = state["run"]
    complaint_id = state["complaint_id"]
    output: PriorityOutput = state["output"]
    events: list[tuple[str, dict | None]] = state.get("event_log", [])
    failed = bool(state.get("fatal_error"))
    status = AgentStatus.FAILED if failed else AgentStatus.SUCCEEDED

    if not failed:
        db.add(
            ComplaintPriorityHistory(
                complaint_id=complaint_id,
                score=output.score,
                priority=output.priority,
                previous_score=output.previous_score,
                changed=output.changed,
                inputs=output.inputs.model_dump(mode="json"),
                factors={
                    "score": output.score,
                    "priority": output.priority.value,
                    "summarized": [f.model_dump(mode="json") for f in output.factors],
                },
                summary=output.summary,
            )
        )
        events.append(
            (
                "priority.computed",
                {
                    "score": output.score,
                    "priority": output.priority.value,
                    "changed": output.changed,
                    "previous_score": output.previous_score,
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
    graph = StateGraph(PriorityState)
    graph.add_node("compute", _compute_node)
    graph.add_node("persist", _persist_node)
    graph.add_edge(START, "compute")
    graph.add_edge("compute", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
class PriorityAgent:
    """Orchestrator that runs the deterministic priority-score graph."""

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

        state: PriorityState = {
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
