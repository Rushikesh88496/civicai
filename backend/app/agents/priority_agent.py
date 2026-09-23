"""Dynamic Priority & Risk Engine agent (Part 12, rebuilt).

A *deterministic* LangGraph agent (no LLM) that computes a 0..100 priority score
and a ``DynamicPriority`` bucket for a complaint from six real-data components:

* **Severity / potential harm** — the complaint's stored severity
  (``complaint.priority``, already set by the triage agent as an input; the
  engine never lets an LLM pick the numeric score).
* **Infrastructure exposure** — real nearby verified facilities (hospital /
  school / fire / police / transit) resolved from the PostGIS registry with
  metre-exact distances, decayed by distance bands (TYPE x DISTANCE x RELEVANCE).
* **Affected population & report pressure** — real complaint density at
  250/500/1000 m over 7 d/30 d, unique reporters, unresolved nearby, geographic
  spread and sensitive-facility adjacency. Population is never fabricated.
* **Recurrence / incident pattern** — same-category recurrence near the location
  over 7 d/30 d (confirmed duplicates excluded).
* **Weather / environmental risk** — real Open-Meteo current + next-days forecast
  precipitation, weighted by complaint category.
* **Evidence confidence** — verified GPS, description substance, photos, AI
  triage/vision agreement, structured category, corroborating reports.

Deterministic **risk amplifiers** (flooding, emergency access, public safety,
recurring hotspot) add capped points ONLY when real evidence triggers them. Time
is NOT a component: the SLA/Escalation state (submitted → due deadline from the
``sla_policies`` rulebook) is computed separately and reported alongside — a
breached SLA never raises the score.

Scoring is *fully deterministic* (``app.services.priority_engine``): each
component normalizes to a 0..1 unit, is capped at its configurable max points,
and the plain sum (clamped 0..100, NEVER re-normalized) receives any real
amplifier bonus. When a signal cannot be resolved, its component reports
``score=None`` + an honest ``status`` (``DATA_UNAVAILABLE`` /
``INSUFFICIENT_DATA``) instead of a guessed number. The result persists to
``agent_runs`` (``agent="priority"``) AND appends a row to
``complaint_priority_history`` (with rich provenance) so the UI can show a score
history and detect significant re-prioritizations (a
>=``PRIORITY_CHANGE_THRESHOLD`` move flags ``changed=True``).

The graph is ``START → compute → persist → END``. A missing complaint is fatal;
every downstream signal degrades to a neutral, honestly-reported status so the
score is always producible.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
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
    ComplaintPriorityHistory,
)
from app.models.enums import AgentStatus, DynamicPriority
from app.schemas.priority import (
    ComplaintSlaStatus,
    DataSource,
    PriorityComponent,
    PriorityFactor,
    PriorityOutput,
    PrioritySignalInputs,
    RiskAmplifier,
)
from app.services import agent_run_service, sla_policy_service
from app.services.priority_data_service import PriorityDataService
from app.services.priority_engine import Weights, score_priority
from app.services.sla_service import complaint_sla_status

logger = logging.getLogger(__name__)

AGENT_NAME = "priority"

# Maps each engine component source to its human + type provenance for the API.
_SOURCE_META: dict[str, tuple[str, str]] = {
    "complaint.priority": ("Complaint severity (stored)", "db"),
    "postgis-infrastructure": ("Infrastructure registry (PostGIS)", "db"),
    "open-meteo": ("Open-Meteo (live HTTP)", "http"),
    "postgis-historical": ("Recurrence counts (PostGIS)", "db"),
    "postgis-reports": ("Affected population & report pressure (PostGIS)", "db"),
    "complaint-evidence": ("Complaint evidence signals (GPS/media/AI)", "db"),
    "sla-policy": ("SLA policy rulebook (sla_policies)", "db"),
    "agent-triage": ("Triage agent agreement", "ai-run"),
    "agent-vision": ("Vision agent agreement", "ai-run"),
    "complaint.timestamps": ("Complaint timestamps / status history", "db"),
}


class PriorityState(TypedDict, total=False):
    """Graph state for the priority engine agent."""

    complaint_id: uuid.UUID
    db: AsyncSession
    settings: Settings
    run: AgentRun
    output: PriorityOutput | None
    reason: str
    fatal_error: bool
    error: str | None
    duration_ms: int | None
    event_log: list[tuple[str, dict | None]]


def _weights(settings: Settings) -> Weights:
    return Weights(
        severity=float(settings.PRIORITY_WEIGHT_SEVERITY),
        infrastructure=float(settings.PRIORITY_WEIGHT_INFRASTRUCTURE),
        population=float(settings.PRIORITY_WEIGHT_POPULATION),
        history=float(settings.PRIORITY_WEIGHT_HISTORY),
        weather=float(settings.PRIORITY_WEIGHT_WEATHER),
        evidence=float(settings.PRIORITY_WEIGHT_EVIDENCE),
    )


def _amplifier_points(settings: Settings) -> dict[str, float]:
    return {
        "FLOODING_RISK": float(settings.PRIORITY_AMPLIFIER_FLOODING_POINTS),
        "EMERGENCY_ACCESS_RISK": float(settings.PRIORITY_AMPLIFIER_EMERGENCY_ACCESS_POINTS),
        "PUBLIC_SAFETY_RISK": float(settings.PRIORITY_AMPLIFIER_PUBLIC_SAFETY_POINTS),
        "RECURRING_HOTSPOT": float(settings.PRIORITY_AMPLIFIER_RECURRING_HOTSPOT_POINTS),
    }


def _build_sources(components: list[PriorityComponent]) -> list[DataSource]:
    """Derive distinct data-source provenance from the resolved components."""
    seen: set[tuple[str, str]] = set()
    sources: list[DataSource] = []
    for comp in components:
        name, stype = _SOURCE_META.get(comp.source, (comp.source, "db"))
        retrieved_at = comp.calculated_at or datetime.now(UTC)
        key = (comp.source, retrieved_at.isoformat())
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            DataSource(
                name=name,
                source_type=stype,
                retrieved_at=retrieved_at,
                params={"component": comp.key, "status": comp.status},
            )
        )
    return sources


def _build_legacy_factors(
    components: list[PriorityComponent],
) -> list[PriorityFactor]:
    """Backward-compatible flat factor list derived from the rich components."""
    factors: list[PriorityFactor] = []
    for comp in components:
        present = comp.score is not None
        factors.append(
            PriorityFactor(
                factor=comp.label,
                input_value=comp.input_value or "n/a",
                present=present,
                weight=round(comp.max_score / 100.0, 3) if comp.max_score else 0.0,
                unit=comp.unit,
                contribution=float(comp.score or 0),
                description=(
                    f"+{comp.score} {comp.label}"
                    if present
                    else f"{comp.label}: {comp.status} — data unavailable"
                ),
            )
        )
    return factors


def _build_legacy_inputs(
    complaint: Complaint,
    bundle,
    now: datetime,
) -> PrioritySignalInputs:
    """Populate the flat legacy inputs from the real collected bundle."""
    infra = bundle.infrastructure
    weather = bundle.weather
    historical = bundle.historical
    population = bundle.population

    counts: dict[str, int] = {}
    if infra is not None and infra.facilities:
        for f in infra.facilities:
            cat = str(f.category).upper()
            counts[cat] = counts.get(cat, 0) + 1

    nearby = (
        historical.same_category_nearby_7d if historical is not None else 0
    )
    nearby_30d = historical.same_category_nearby_30d if historical is not None else 0
    return PrioritySignalInputs(
        severity=bundle.severity.severity or "LOW",
        population=(
            population.population
            if population is not None and population.population_status == "AVAILABLE"
            else 0
        ),
        hospitals=int(counts.get("HOSPITAL", 0)),
        schools=int(counts.get("SCHOOL", 0)),
        bus_stops=int(counts.get("BUS_STOP", 0)),
        location_available=(
            infra.status not in {"DATA_UNAVAILABLE", "INSUFFICIENT_DATA"}
            if infra is not None
            else False
        ),
        weather_condition=weather.condition if weather is not None else None,
        rain_mm=weather.rain_mm if weather is not None else None,
        weather_available=bool(weather is not None and weather.status == "AVAILABLE"),
        complaint_count=nearby,
        historical_recurrence=nearby_30d,
        ward_resolved=complaint.ward_id is not None,
        time_unresolved_hours=round(
            (now - (complaint.created_at or now)).total_seconds() / 3600.0, 1
        ),
    )


async def _compute_node(state: PriorityState) -> dict[str, object]:
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

    # Real data collected at scoring time (never re-read from a stale context run).
    try:
        bundle = await PriorityDataService(settings=settings).collect(db, complaint)
    except Exception as exc:  # noqa: BLE001 - degrade, keep scoring possible
        logger.exception("Priority data collection failed for %s: %s", complaint_id, exc)
        return {
            "fatal_error": True,
            "error": "Priority data collection failed; see server logs.",
            "output": None,
        }

    score, bucket, comp_dicts, readiness, amp_dicts = score_priority(
        category=bundle.category,
        severity=bundle.severity,
        complaint_description=complaint.description,
        infrastructure=bundle.infrastructure,
        weather=bundle.weather,
        historical=bundle.historical,
        population=bundle.population,
        evidence=bundle.evidence,
        weights=_weights(settings),
        threshold_p1=float(settings.PRIORITY_THRESHOLD_P1),
        threshold_p2=float(settings.PRIORITY_THRESHOLD_P2),
        threshold_p3=float(settings.PRIORITY_THRESHOLD_P3),
        infra_decay_bands=tuple(
            float(v) for v in settings.PRIORITY_INFRA_DECAY_BANDS_M
        ),
        infra_band_factors=tuple(
            float(v) for v in settings.PRIORITY_INFRA_DISTANCE_FACTORS
        ),
        infra_saturation=float(settings.PRIORITY_INFRA_SATURATION),
        infra_peak_weight=float(settings.PRIORITY_INFRA_PEAK_WEIGHT),
        infra_cluster_weight=float(settings.PRIORITY_INFRA_CLUSTER_WEIGHT),
        infra_access_bonus_50m=float(settings.PRIORITY_INFRA_ACCESS_BONUS_50_M),
        infra_access_bonus_100m=float(settings.PRIORITY_INFRA_ACCESS_BONUS_100_M),
        weather_probability_threshold_pct=float(
            settings.PRIORITY_WEATHER_PROBABILITY_PCT
        ),
        facility_base_relevance=settings.PRIORITY_FACILITY_BASE_RELEVANCE,
        category_facility_factors=settings.PRIORITY_CATEGORY_FACILITY_FACTORS,
        population_subweights=settings.PRIORITY_POPULATION_SUBWEIGHTS,
        emergency_access_band_m=float(
            settings.PRIORITY_AMPLIFIER_EMERGENCY_ACCESS_BAND_M
        ),
        amplifier_points=_amplifier_points(settings),
        hotspot_repeat_count=int(settings.PRIORITY_HOTSPOT_REPEAT_COUNT),
    )

    components = [PriorityComponent(**c) for c in comp_dicts]
    risk_amplifiers = [RiskAmplifier(**a) for a in amp_dicts]
    sources = _build_sources(components)
    calculated_at = components[0].calculated_at if components else datetime.now(UTC)
    inputs = _build_legacy_inputs(complaint, bundle, calculated_at)

    # Change detection vs the previous computation.
    previous = await _latest_history_entry(db, complaint_id)
    prev_score = previous.score if previous is not None else None
    prev_priority = DynamicPriority(previous.priority.value) if previous is not None else None
    changed_base = float(settings.PRIORITY_CHANGE_THRESHOLD)
    changed = prev_score is None or abs(score - prev_score) >= changed_base

    driver = next((c for c in components if c.score is not None), None)
    driver_name = driver.label if driver is not None else "severity"
    summary = f"Priority {bucket.value} score {score}/100 — biggest driver: {driver_name}."

    # Separate SLA/Escalation snapshot (score-independent; never raises the score).
    sla = await _resolve_complaint_sla(
        db, complaint=complaint, bucket=bucket, category=bundle.category
    )

    output = PriorityOutput(
        score=score,
        priority=bucket,
        factors=_build_legacy_factors(components),
        components=components,
        sources=sources,
        risk_amplifiers=risk_amplifiers,
        sla=sla,
        data_status=readiness,
        calculated_at=calculated_at,
        reason=state.get("reason") or "manual",
        inputs=inputs,
        previous_score=prev_score,
        previous_priority=prev_priority,
        changed=changed,
        summary=summary,
    )
    return {"output": output, "fatal_error": False, "error": None}


async def _resolve_complaint_sla(
    db: AsyncSession,
    *,
    complaint: Complaint,
    bucket: DynamicPriority,
    category: str | None,
) -> ComplaintSlaStatus:
    """Complaint-level SLA snapshot from the ``sla_policies`` rulebook.

    Department is the most recent primary_department from the complaint's
    department history (if any); the resolve is non-fatal — without a matching
    rule the status reports ``NO_POLICY`` (SLA never blocks scoring).
    """
    department: str | None = None
    dept_row = await db.scalar(
        select(ComplaintDepartmentHistory)
        .where(ComplaintDepartmentHistory.complaint_id == complaint.id)
        .order_by(ComplaintDepartmentHistory.calculated_at.desc())
        .limit(1)
    )
    if dept_row is not None:
        department = (
            dept_row.primary_department.value
            if hasattr(dept_row.primary_department, "value")
            else str(dept_row.primary_department)
        )
    policy = None
    try:
        policy = await sla_policy_service.resolve(
            db,
            priority=bucket.value,
            department=department,
            category=category,
        )
    except Exception as exc:  # noqa: BLE001 - SLA must never block scoring
        logger.warning("SLA resolve failed for %s: %s", complaint.id, exc)
    submitted_at = complaint.created_at or complaint.updated_at
    if submitted_at is None:
        return ComplaintSlaStatus(state="NO_POLICY")
    sla_dict = complaint_sla_status(
        priority=bucket.value,
        department=department,
        category=category,
        submitted_at=submitted_at,
        now=datetime.now(UTC),
        policy=policy,
    )
    sla_dict.pop("progress", None)
    return ComplaintSlaStatus(**sla_dict)


async def _latest_history_entry(
    db: AsyncSession, complaint_id: uuid.UUID
) -> ComplaintPriorityHistory | None:
    return await db.scalar(
        select(ComplaintPriorityHistory)
        .where(ComplaintPriorityHistory.complaint_id == complaint_id)
        .order_by(ComplaintPriorityHistory.calculated_at.desc())
        .limit(1)
    )


async def _persist_node(state: PriorityState) -> dict[str, object]:
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
                data_status=output.data_status.value,
                components=[c.model_dump(mode="json") for c in output.components],
                sources=[s.model_dump(mode="json") for s in output.sources],
                risk_amplifiers=[
                    r.model_dump(mode="json") for r in output.risk_amplifiers
                ],
                sla=(
                    output.sla.model_dump(mode="json") if output.sla is not None else None
                ),
                reason=output.reason,
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
                    "data_status": output.data_status.value,
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
        graph: object | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._graph = graph if graph is not None else build_graph()

    async def run(
        self,
        db: AsyncSession,
        *,
        complaint_id: uuid.UUID,
        reason: str = "manual",
    ) -> AgentRun:
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
            "reason": reason,
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
