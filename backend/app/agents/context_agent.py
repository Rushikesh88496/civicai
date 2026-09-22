"""Context Enrichment Agent (Part 11).

A *deterministic* LangGraph agent (no LLM) that augments a complaint with
situational intelligence before a triage officer reviews it. It fuses four
sources into a single structured ``ContextOutput`` that persists to
``agent_runs`` (``agent="context"``):

* **Weather** — current conditions + a short daily forecast from Open-Meteo's
  free forecast API (no API key needed). Responses are cached in Redis with a
  TTL: a cache hit skips the upstream call and marks ``cached=True``; a miss
  fetches live then stores; when Redis is unreachable we degrade to a live call.
* **GIS** — ward membership + reverse-geocoded address, reusing Part 10's
  ``GeoService.geo_lookup`` (itself gracefully degrading on Nominatim failures).
* **Historical** — volume of prior complaints in the same ward and within a
  radius of the location over a configurable time window (PostGIS ``ST_DWithin``).
* **Infrastructure** — count and highlights of nearby critical locations
  (hospitals, schools, bus stops) from Part 10's seeded critical-locations.

Unlike some deterministic peers, the agent is deliberately *resilient*: a single
downstream failure never fails the whole run. A missing complaint is fatal; every
external lookup otherwise degrades to ``None``/empty context so the officer still
gets the intelligently populated fields that are available.

The graph is ``START → enrich → persist → END``.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from geoalchemy2 import Geography
from geoalchemy2.functions import ST_DWithin, ST_MakePoint, ST_SetSRID
from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.models import AgentRun, Complaint, ComplaintLocation
from app.models.enums import AgentStatus
from app.schemas.context import (
    ContextOutput,
    ContextSource,
    GisContext,
    HistoricalContext,
    InfrastructureContext,
    InfrastructureEntry,
    WeatherContext,
)
from app.services import agent_run_service
from app.services.geo_service import GeoService
from app.services.weather_service import fetch_weather

logger = logging.getLogger(__name__)

AGENT_NAME = "context"

# Range of coordinates validated before calling Open-Meteo.
_MIN_LAT, _MAX_LAT = -90.0, 90.0
_MIN_LNG, _MAX_LNG = -180.0, 180.0


class ContextState(TypedDict, total=False):
    """Graph state for the context enrichment agent."""

    complaint_id: uuid.UUID
    db: AsyncSession
    geo: GeoService
    settings: Settings
    run: AgentRun
    weather_client: Any | None
    output: ContextOutput | None
    fatal_error: bool
    error: str | None
    duration_ms: int | None
    event_log: list[tuple[str, dict | None]]


# --------------------------------------------------------------------------- #
# Historical + infrastructure enrichment helpers
# --------------------------------------------------------------------------- #
async def _collect_historical(
    db: AsyncSession,
    *,
    settings: Settings,
    complaint_id: uuid.UUID,
    ward_id: uuid.UUID | None,
    location: ComplaintLocation | None,
) -> HistoricalContext:
    """Count prior complaints in the same ward and within a radius."""
    window_hours = float(settings.CONTEXT_HISTORICAL_WINDOW_HOURS)
    window_start = datetime.now(UTC) - timedelta(hours=window_hours)
    radius = float(settings.CONTEXT_HISTORICAL_RADIUS_M)

    same_ward_count: int | None = None
    if ward_id is not None:
        same_ward_count = int(
            await db.scalar(
                select(func.count(Complaint.id)).where(
                    Complaint.ward_id == ward_id,
                    Complaint.id != complaint_id,
                    Complaint.created_at >= window_start,
                )
            )
            or 0
        )

    total_prior = 0
    if location is not None:
        gh = Geography(geometry_type="POINT", srid=4326)
        point = ST_SetSRID(ST_MakePoint(location.longitude, location.latitude), 4326)
        nearby_ids = (
            select(Complaint.id)
            .join(ComplaintLocation, ComplaintLocation.complaint_id == Complaint.id)
            .where(
                ComplaintLocation.complaint_id != complaint_id,
                ST_DWithin(ComplaintLocation.geom.cast(gh), point.cast(gh), radius),
            )
        )
        prior = (
            await db.execute(
                select(func.count(Complaint.id)).where(
                    Complaint.id.in_(nearby_ids),
                    Complaint.created_at >= window_start,
                )
            )
        ).scalar()
        total_prior = int(prior or 0)

    summary = _historical_summary(total_prior, same_ward_count)
    return HistoricalContext(
        total_prior=total_prior,
        same_ward_count=same_ward_count,
        window_hours=float(settings.CONTEXT_HISTORICAL_WINDOW_HOURS),
        radius_m=radius,
        ward_resolved=ward_id is not None,
        summary=summary,
    )


def _historical_summary(total_prior: int, same_ward_count: int | None) -> str:
    cue = max(total_prior, same_ward_count or 0)
    base = f"{total_prior} prior complaint(s) within range"
    if same_ward_count is not None and same_ward_count:
        base = base + f", {same_ward_count} in the same ward"
    if cue >= 10:
        return base + " — high volume: review urgently."
    if cue >= 3:
        return base + " — elevated local activity."
    return base + "."


def _collect_infrastructure(lookup: Any) -> InfrastructureContext:
    """Derive counts/highlights from the attended critical-location lists."""
    hospitals = list(lookup.hospitals)
    schools = list(lookup.schools)
    bus_stops = list(lookup.bus_stops)
    police = list(getattr(lookup, "police_stations", []))
    fire = list(getattr(lookup, "fire_stations", []))
    public = list(getattr(lookup, "public_facilities", []))
    government = list(getattr(lookup, "government_buildings", []))
    roads = list(lookup.nearby_roads)
    poi = [*hospitals, *schools, *bus_stops, *police, *fire, *public, *government]
    poi.sort(key=lambda p: (p.distance_m is None, p.distance_m or 0))

    def to_entry(p) -> InfrastructureEntry:
        cat = getattr(p, "category", "infrastructure")
        return InfrastructureEntry(
            name=p.name,
            category=(cat.value if isinstance(cat, str) and hasattr(cat, "value") else str(cat)),
            distance_m=float(p.distance_m) if p.distance_m is not None else None,
        )

    status = str(getattr(lookup, "nearby_status", "available"))
    if status == "unavailable":
        available = False
    else:
        available = bool(poi)

    highlights = [to_entry(p) for p in poi[:5]]
    return InfrastructureContext(
        radius_m=lookup.radius_m,
        total_nearby=len(poi),
        hospitals=len(hospitals),
        schools=len(schools),
        bus_stops=len(bus_stops),
        police_stations=len(police),
        fire_stations=len(fire),
        public_facilities=len(public),
        government_buildings=len(government),
        major_roads=len(roads),
        status=status,
        highlights=highlights,
        places=[to_entry(p) for p in poi[:25]],
        available=available,
    )


# --------------------------------------------------------------------------- #
# Graph nodes
# --------------------------------------------------------------------------- #
async def _enrich_node(state: ContextState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    geo: GeoService = state["geo"]
    settings: Settings = state["settings"]
    run: AgentRun = state["run"]
    complaint_id = state["complaint_id"]
    await agent_run_service._append_event(db, run, "context.started", {"agent": AGENT_NAME})
    await db.flush()

    complaint = await db.scalar(
        select(Complaint)
        .where(Complaint.id == complaint_id)
        .options(selectinload(Complaint.ward), selectinload(Complaint.complaint_location))
    )
    if complaint is None:
        return {"fatal_error": True, "error": "Complaint no longer exists.", "output": None}

    location = complaint.complaint_location
    ward_id = complaint.ward_id

    latitude = location.latitude if location else None
    longitude = location.longitude if location else None

    sources: list[ContextSource] = []
    weather: WeatherContext = WeatherContext(available=False)
    gis: GisContext = GisContext(available=False)
    infrastructure: InfrastructureContext = InfrastructureContext(available=False)

    # --- GIS + infrastructure (Part 10 reuse) ---
    if latitude is not None and longitude is not None:
        try:
            lookup = await geo.geo_lookup(db, latitude, longitude, settings.GIS_CRITICAL_RADIUS_M)
            ward = lookup.ward
            gis = GisContext(
                latitude=latitude,
                longitude=longitude,
                address=lookup.address.address if lookup.address else None,
                address_source=lookup.address.source if lookup.address else "nominatim",
                address_degraded=lookup.address.degraded if lookup.address else False,
                ward_id=ward.ward_id if ward else ward_id,
                ward_name=ward.name if ward else (complaint.ward.name if complaint.ward else None),
                ward_code=ward.code if ward else (complaint.ward.code if complaint.ward else None),
                ward_description=ward.description if ward else None,
                ward_is_demo=ward.is_demo if ward else False,
                radius_m=lookup.radius_m,
                demo_label=lookup.demo_label,
                available=True,
            )
            infrastructure = _collect_infrastructure(lookup)
            sources.append(
                ContextSource(
                    name="nominatim",
                    source_type="http",
                    retrieved_at=datetime.now(UTC),
                    params={"latitude": latitude, "longitude": longitude},
                )
            )
            sources.append(
                ContextSource(
                    name="postgis-critical-locations",
                    source_type="db",
                    retrieved_at=datetime.now(UTC),
                    params={
                        "radius_m": lookup.radius_m,
                        "categories": ["hospital", "school", "bus_stop"],
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 - GIS failure degrades, never fails
            logger.warning("GIS enrichment failed for %s: %s", complaint_id, exc)
    else:
        # No coordinates: still report the ward we already have stored on the complaint.
        gis = GisContext(
            ward_id=ward_id,
            ward_name=complaint.ward.name if complaint.ward else None,
            ward_code=complaint.ward.code if complaint.ward else None,
            ward_is_demo=True,
            available=ward_id is not None,
        )

    # --- Weather (independent, may run in parallel with GIS in principle) ---
    if latitude is not None and longitude is not None:
        weather, weather_source = await fetch_weather(
            settings=settings,
            latitude=latitude,
            longitude=longitude,
            client=state.get("weather_client"),
        )
        if weather_source is not None:
            sources.append(weather_source)
    if weather.available and weather.cached:
        # Keep provenance for a cache-served response without re-adding a source.
        warmer = ContextSource(
            name="open-meteo",
            source_type="cache",
            retrieved_at=datetime.now(UTC),
            params={"latitude": latitude, "longitude": longitude, "cached": True},
        )
        if not any(s.name == "open-meteo" for s in sources):
            sources.append(warmer)

    # --- Historical volume (DB, local) ---
    historical = await _collect_historical(
        db, settings=settings, complaint_id=complaint_id, ward_id=ward_id, location=location
    )
    sources.append(
        ContextSource(
            name="postgis-historical",
            source_type="db",
            retrieved_at=datetime.now(UTC),
            params={
                "window_hours": settings.CONTEXT_HISTORICAL_WINDOW_HOURS,
                "radius_m": settings.CONTEXT_HISTORICAL_RADIUS_M,
            },
        )
    )

    output = ContextOutput(
        weather_context=weather,
        gis_context=gis,
        historical_context=historical,
        infrastructure_context=infrastructure,
        sources=sources,
        summary=_summary(weather, gis, historical, infrastructure),
    )
    return {"output": output, "fatal_error": False, "error": None}


def _summary(
    weather: WeatherContext,
    gis: GisContext,
    historical: HistoricalContext,
    infra: InfrastructureContext,
) -> str:
    parts: list[str] = []
    if gis.ward_name:
        parts.append(f"ward {gis.ward_name}")
    if weather.available and weather.temperature_c is not None:
        cond = weather.condition or "conditions"
        parts.append(f"{weather.temperature_c:.0f}°C, {cond.lower()}")
    if historical.total_prior:
        label = "complaint" if historical.total_prior == 1 else "complaints"
        parts.append(f"{historical.total_prior} prior {label}")
    if infra.total_nearby:
        label = "facility" if infra.total_nearby == 1 else "facilities"
        parts.append(f"{infra.total_nearby} nearby critical {label}")
    if parts:
        return "Context: " + "; ".join(parts) + "."
    return "Context enrichment completed with no locatable signals."


async def _persist_node(state: ContextState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    run: AgentRun = state["run"]
    output: ContextOutput = state["output"]
    events: list[tuple[str, dict | None]] = state.get("event_log", [])
    failed = bool(state.get("fatal_error"))
    status = AgentStatus.FAILED if failed else AgentStatus.SUCCEEDED

    if not failed:
        events.append(
            (
                "context.ready",
                {
                    "weather": output.weather_context.available,
                    "gis": output.gis_context.available,
                    "historical": output.historical_context.total_prior,
                    "infrastructure": output.infrastructure_context.total_nearby,
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
def _next(state: ContextState) -> str:
    return "persist"


def build_graph() -> Any:
    graph = StateGraph(ContextState)
    graph.add_node("enrich", _enrich_node)
    graph.add_node("persist", _persist_node)
    graph.add_edge(START, "enrich")
    graph.add_edge("enrich", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
class ContextAgent:
    """Orchestrator that runs the situation-context enrichment graph."""

    def __init__(
        self,
        *,
        geo_service: GeoService | None = None,
        settings: Settings | None = None,
        weather_client: Any | None = None,
        graph: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._geo = geo_service or GeoService(settings=self._settings)
        self._weather_client = weather_client
        self._graph = graph if graph is not None else build_graph()

    async def run(self, db: AsyncSession, *, complaint_id: uuid.UUID) -> AgentRun:
        started = time.monotonic()
        run = await agent_run_service.create_run(
            db, complaint_id=complaint_id, agent=AGENT_NAME, model=None
        )
        await agent_run_service._append_event(db, run, "run.started", {"agent": AGENT_NAME})
        await db.commit()
        run_id = run.id

        state: ContextState = {
            "complaint_id": complaint_id,
            "db": db,
            "geo": self._geo,
            "settings": self._settings,
            "run": run,
            "weather_client": self._weather_client,
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
