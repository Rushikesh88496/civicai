"""Schemas for the Context Enrichment Agent (Part 11).

The Context Enrichment Agent is a *deterministic* agent (no LLM) that augments a
complaint with situational intelligence before a triage officer reviews it. It
fuses four sources into a single structured result that is persisted to
``agent_runs`` (``agent="context"``):

* **Weather** — current conditions and a short daily forecast from Open-Meteo's
  free forecast API (no API key required). Responses are cached in Redis with a
  TTL; when Redis is unreachable the agent falls back to a live call.
* **GIS** — ward membership, reverse-geocoded address (reusing Part 10's
  ``GeoService.geo_lookup``).
* **Historical** — count of previously reported complaints in the same ward and
  within a radius of the complaint's location over a configurable time window.
* **Infrastructure** — count and highlights of nearby critical locations
  (hospitals, schools, bus stops) from Part 10's seeded critical-locations.

Every external datum also carries provenance in ``sources`` (name, source type,
retrieval time, request parameters) so the UI can show origin and freshness.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentStatus


class WeatherForecastDay(BaseModel):
    """One day of the short-range daily forecast for the complaint location."""

    date: str
    temperature_max: float | None = None
    temperature_min: float | None = None
    precipitation_sum: float | None = None


class WeatherContext(BaseModel):
    """Current + short forecast weather for the complaint location."""

    temperature_c: float | None = None
    precipitation_mm: float | None = None
    rain_mm: float | None = None
    wind_speed_kmh: float | None = None
    weather_code: int | None = None
    condition: str | None = None
    # True when the response came from the Redis cache (freshness indicator).
    cached: bool = False
    retrieved_at: datetime | None = None
    # Whether weather could be resolved at all for this run (false when the
    # complaint has no coordinates or the upstream service was unavailable).
    available: bool = False
    forecast: list[WeatherForecastDay] = Field(default_factory=list)


class GisContext(BaseModel):
    """Spatial intelligence for the complaint location (Part 10 reuse)."""

    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None
    address_source: str = "nominatim"
    address_degraded: bool = False
    ward_id: uuid.UUID | None = None
    ward_name: str | None = None
    ward_code: str | None = None
    ward_description: str | None = None
    ward_is_demo: bool = True
    radius_m: float | None = None
    demo_label: str = "DEMO DATA"
    available: bool = False


class HistoricalContext(BaseModel):
    """Volume of prior complaints near the current location."""

    total_prior: int = 0
    same_ward_count: int | None = None
    window_hours: float | None = None
    radius_m: float | None = None
    # True when the complaint's ward could be resolved for the ward-scoped count.
    ward_resolved: bool = False
    # Basic risk phrasing derived deterministically from the counts.
    summary: str = "No prior complaints in range."


class InfrastructureEntry(BaseModel):
    """A single nearby critical-location highlight for the card."""

    name: str
    category: str
    distance_m: float | None = None


class InfrastructureContext(BaseModel):
    """Nearby critical infrastructure summary (Part 10 critical locations)."""

    radius_m: float | None = None
    total_nearby: int = 0
    hospitals: int = 0
    schools: int = 0
    bus_stops: int = 0
    highlights: list[InfrastructureEntry] = Field(default_factory=list)
    available: bool = False


class ContextSource(BaseModel):
    """Provenance for a single external fact collected by the agent."""

    # e.g. "open-meteo", "nominatim", "postgis-ward", "postgis-historical".
    name: str
    source_type: str
    # ISO-8601 time the fact was retrieved.
    retrieved_at: datetime
    # The exact request parameters used (coords, ward id, radius, window, etc.).
    params: dict[str, object] = Field(default_factory=dict)


class ContextOutput(BaseModel):
    """Validated structured result produced by the Context Enrichment Agent."""

    weather_context: WeatherContext = Field(default_factory=WeatherContext)
    gis_context: GisContext = Field(default_factory=GisContext)
    historical_context: HistoricalContext = Field(default_factory=HistoricalContext)
    infrastructure_context: InfrastructureContext = Field(default_factory=InfrastructureContext)
    # Provenance of every external fact (name + params + retrieval time).
    sources: list[ContextSource] = Field(default_factory=list)
    # One-line human summary for the timeline / UI.
    summary: str = Field(default="", max_length=500)


class ContextRunOut(BaseModel):
    """Serialized context agent run persisted to ``agent_runs``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    complaint_id: uuid.UUID | None = None
    agent: str
    model: str | None = None
    status: AgentStatus
    duration_ms: int | None = None
    structured_result: ContextOutput | None = None
    error: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class ContextRunResponse(BaseModel):
    """Response envelope for running context enrichment on a complaint."""

    run_id: uuid.UUID
    status: AgentStatus
    result: ContextOutput | None = None
    error: str | None = None
    retry_allowed: bool = True


class ContextRunIn(BaseModel):
    """Optional body for triggering context enrichment (reserved for future
    input hints); no fields are currently required by the caller."""

    pass


__all__ = [
    "ContextOutput",
    "ContextRunIn",
    "ContextRunOut",
    "ContextRunResponse",
    "ContextSource",
    "GisContext",
    "HistoricalContext",
    "InfrastructureContext",
    "InfrastructureEntry",
    "WeatherContext",
    "WeatherForecastDay",
]
