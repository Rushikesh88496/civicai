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

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

import httpx
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_DWithin, ST_MakePoint, ST_SetSRID
from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import cache_get_json, cache_key, cache_set_json
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
    WeatherForecastDay,
)
from app.services import agent_run_service
from app.services.geo_service import GeoService

logger = logging.getLogger(__name__)

AGENT_NAME = "context"

# Range of coordinates validated before calling Open-Meteo.
_MIN_LAT, _MAX_LAT = -90.0, 90.0
_MIN_LNG, _MAX_LNG = -180.0, 180.0

# Open-Meteo returns JSON arrays in the same order as the requested variables.
_CURRENT_FIELDS = [
    "temperature_2m",
    "precipitation",
    "rain",
    "weather_code",
    "wind_speed_10m",
]
_DAILY_FIELDS = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum"]

# Rough WMO weather-code → human label (subset adequate for the UI card).
_WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Light rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class ContextState(TypedDict, total=False):
    """Graph state for the context enrichment agent."""

    complaint_id: uuid.UUID
    db: AsyncSession
    geo: GeoService
    settings: Settings
    run: AgentRun
    weather_client: httpx.AsyncClient | None
    output: ContextOutput | None
    fatal_error: bool
    error: str | None
    duration_ms: int | None
    event_log: list[tuple[str, dict | None]]


# --------------------------------------------------------------------------- #
# Weather (Open-Meteo, Redis-cached, no API key)
# --------------------------------------------------------------------------- #
async def _fetch_weather(
    *,
    settings: Settings,
    latitude: float,
    longitude: float,
    client: httpx.AsyncClient | None = None,
) -> tuple[WeatherContext, ContextSource | None]:
    """Fetch current + short forecast weather for a coordinate.

    Chained fallback, newest first:
    1. Redis cache hit (``cached=True``) — TTL enforced by Redis.
    2. Live Open-Meteo call — stored into Redis for future hits.
    3. Open-Meteo unreachable → ``available=False``, graceful.
    """
    retrieved = datetime.now(UTC)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join(_CURRENT_FIELDS),
        "daily": ",".join(_DAILY_FIELDS),
        "forecast_days": settings.WEATHER_FORECAST_DAYS,
        "timezone": "auto",
    }
    key = cache_key(settings, "weather", f"{latitude:.5f},{longitude:.5f}")

    # 1) Cache hit.
    cached_payload, is_hit = await cache_get_json(settings, key)
    if is_hit and isinstance(cached_payload, dict) and cached_payload.get("_payload"):
        return _parse_weather_payload(cached_payload["_payload"], cached=True), None

    # 2) Live call, retried up to the configured budget (mirrors geo discipline).
    retries = max(0, int(settings.WEATHER_MAX_RETRIES))
    try:
        url = f"{settings.WEATHER_BASE_URL.rstrip('/')}"
        timeout = settings.WEATHER_TIMEOUT_SECONDS

        async def _get() -> dict[str, Any]:
            if client is None:
                async with httpx.AsyncClient(timeout=timeout) as ac:
                    resp = await ac.get(url, params=params)
            else:
                resp = await client.get(url, params=params)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Open-Meteo HTTP {resp.status_code} for {params.get('latitude')},"
                    f"{params.get('longitude')}"
                )
            return resp.json()

        payload: dict[str, Any] = {}
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                payload = await _get()
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 - retried, then degrades
                last_exc = exc
                if attempt == retries:
                    break
                await asyncio.sleep(0.2 * (attempt + 1))
        if last_exc is not None:
            raise last_exc

        weather = _parse_weather_payload(payload, cached=False)
        if weather.available:
            # Store alongside the retrieval time for freshness provenance.
            await cache_set_json(
                settings,
                key,
                {"_payload": payload, "_retrieved_at": retrieved.isoformat()},
                int(settings.WEATHER_CACHE_TTL_SECONDS),
            )
        source = ContextSource(
            name="open-meteo",
            source_type="http",
            retrieved_at=retrieved,
            params=_coerce_params(params),
        )
        return weather, source
    except Exception as exc:  # noqa: BLE001 - weather failure never fails the run
        logger.warning("Open-Meteo unavailable for (%s, %s): %s", latitude, longitude, exc)
        return WeatherContext(available=False), None


def _parse_weather_payload(payload: dict[str, Any], *, cached: bool) -> WeatherContext:
    """Map an Open-Meteo JSON payload onto a ``WeatherContext``."""
    current = payload.get("current", {}) or {}
    daily = payload.get("daily", {}) or {}
    values = {k: current.get(k) for k in _CURRENT_FIELDS}
    temperature = _num(values.get("temperature_2m"))
    precipitation = _num(values.get("precipitation"))
    rain = _num(values.get("rain"))
    wind = _num(values.get("wind_speed_10m"))
    wcode = values.get("weather_code")
    code = int(wcode) if isinstance(wcode, (int, float)) else None

    forecast: list[WeatherForecastDay] = []
    dates = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    psum = daily.get("precipitation_sum") or []
    for i, d in enumerate(dates):
        forecast.append(
            WeatherForecastDay(
                date=str(d),
                temperature_max=_num(tmax[i]) if i < len(tmax) else None,
                temperature_min=_num(tmin[i]) if i < len(tmin) else None,
                precipitation_sum=_num(psum[i]) if i < len(psum) else None,
            )
        )

    provided = any(v is not None for v in (temperature, precipitation, rain, wind, code))
    return WeatherContext(
        temperature_c=temperature,
        precipitation_mm=precipitation,
        rain_mm=rain,
        wind_speed_kmh=wind,
        weather_code=code,
        condition=_WMO_CODES.get(code) if code is not None else None,
        cached=cached,
        retrieved_at=datetime.now(UTC),
        available=provided,
        forecast=forecast,
    )


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_params(params: dict[str, object]) -> dict[str, object]:
    """Ensure params are JSON-serializable for the provenance record."""
    return {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in params.items()}


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
        weather, weather_source = await _fetch_weather(
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
        weather_client: httpx.AsyncClient | None = None,
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
