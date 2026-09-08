"""Tests for the Context Enrichment Agent (Part 11).

Covers the deterministic ``START → enrich → persist → END`` flow against the
live (dev) database:

* **Weather** — Open-Meteo is injected via ``httpx.MockTransport`` (no real
  network): success mapping, unavailable degradation (5xx), Redis cache
  hit (``cached=True``, no network) and cache miss→store are covered.
* **GIS / infrastructure** — the agent's ``GeoService.geo_lookup`` is replaced
  by a stub so ward / reverse-geocoded address / infrastructure are
  deterministic (the real PostGIS queries are already covered by Part 10).
* **Historical** — real PostGIS count of prior complaints in the same ward and
  within a radius over the configured window.
* **API + RBAC** — 401 unauthenticated, 403 cross-owner access, 404 unknown
  complaint, a full run + ``context-result`` retrieval, and graceful behaviour
  when external config (weather base URL) is missing / Redis is unreachable.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.agents.context_agent import ContextAgent, _parse_weather_payload
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import AgentRun, Complaint, User
from app.models.enums import AgentStatus, CriticalLocationCategory
from app.schemas.auth import RegisterIn
from app.schemas.geo import (
    GeoLookupOut,
    GeoPlace,
    ReverseGeocodeOut,
    WardDetected,
)
from app.services import auth_service

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"
_SETTINGS = get_settings()

# Hyderabad seed area (inside the DEMO Riverside W-002 polygon).
_SEED_LAT = 17.4327
_SEED_LON = 78.3885

_SAMPLE_WEATHER = {
    "current": {
        "temperature_2m": 28.4,
        "precipitation": 0.0,
        "rain": 0.0,
        "weather_code": 3,
        "wind_speed_10m": 12.3,
    },
    "daily": {
        "time": ["2026-09-04", "2026-09-05", "2026-09-06"],
        "temperature_2m_max": [30.0, 31.0, 29.0],
        "temperature_2m_min": [22.0, 23.0, 21.0],
        "precipitation_sum": [0.0, 0.0, 0.5],
    },
}


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db, RegisterIn(email=email, password=_PASSWORD, full_name="Context Citizen")
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _create_complaint(
    client, token: str, *, desc: str, category: str, lat: float, lon: float
) -> str:
    body = {
        "description": desc,
        "category": category,
        "media_ids": [],
        "location": {
            "latitude": lat,
            "longitude": lon,
            "address": "Context test location",
            "source": "gps",
            "geopoint_denied": False,
        },
    }
    r = await client.post(_BASE, json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


# --------------------------------------------------------------------------- #
# Deterministic GIS stub (avoids live Nominatim, guarantees seed shapes)
# --------------------------------------------------------------------------- #
class StubGeo:
    """Replaces GeoService.geo_lookup so context tests are fully deterministic."""

    def __init__(self, lookup: GeoLookupOut) -> None:
        self._lookup = lookup

    async def geo_lookup(self, db, latitude, longitude, radius_m=None) -> GeoLookupOut:
        return self._lookup


def _seed_lookup() -> GeoLookupOut:
    return GeoLookupOut(
        latitude=_SEED_LAT,
        longitude=_SEED_LON,
        address=ReverseGeocodeOut(
            address="Durgam Cheruvu Road, Madhapur, Hyderabad",
            display_name="Durgam Cheruvu Road, Madhapur, Hyderabad",
            source="nominatim",
        ),
        ward=WardDetected(
            ward_id=uuid.uuid4(),
            name="Riverside",
            code="W-002",
            description="Riverside demo ward",
            is_demo=True,
        ),
        nearby_roads=[],
        hospitals=[
            _place("City Central Hospital", CriticalLocationCategory.HOSPITAL, 400.0),
        ],
        schools=[
            _place("Riverside Primary School", CriticalLocationCategory.SCHOOL, 300.0),
        ],
        bus_stops=[
            _place("Market Street Bus Stop", CriticalLocationCategory.BUS_STOP, 200.0),
        ],
        critical_infrastructure=[],
        radius_m=_SETTINGS.GIS_CRITICAL_RADIUS_M,
        demo_label=_SETTINGS.GIS_DEMO_LABEL,
        calculated_at=datetime.now(UTC),
    )


def _place(name: str, category: CriticalLocationCategory, distance_m: float) -> GeoPlace:
    return GeoPlace(
        id=uuid.uuid4(),
        name=name,
        category=category,
        latitude=_SEED_LAT + 0.001,
        longitude=_SEED_LON + 0.001,
        distance_m=distance_m,
        is_demo=True,
    )


def _weather_client(payload: dict | None = None) -> httpx.AsyncClient:
    body = payload if payload is not None else _SAMPLE_WEATHER

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _failing_weather_client() -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _agent(weather_client=None, geo=None, settings=None):
    return ContextAgent(
        settings=settings or _SETTINGS,
        geo_service=geo or StubGeo(_seed_lookup()),
        weather_client=weather_client,
    )


# --------------------------------------------------------------------------- #
# Unit tests: weather payload parsing
# --------------------------------------------------------------------------- #
def test_parse_weather_payload_maps_current_and_daily():
    ctx = _parse_weather_payload(_SAMPLE_WEATHER, cached=False)
    assert ctx.available is True
    assert ctx.temperature_c == 28.4
    assert ctx.precipitation_mm == 0.0
    assert ctx.wind_speed_kmh == 12.3
    assert ctx.weather_code == 3
    assert ctx.condition == "Overcast"
    assert len(ctx.forecast) == 3
    assert ctx.forecast[0].date == "2026-09-04"
    assert ctx.forecast[0].temperature_max == 30.0
    assert ctx.cached is False


def test_parse_weather_payload_empty_is_unavailable():
    ctx = _parse_weather_payload({}, cached=False)
    assert ctx.available is False
    assert ctx.temperature_c is None
    assert ctx.condition is None
    assert ctx.forecast == []


# --------------------------------------------------------------------------- #
# Agent-level: full enrichment (weather mocked, GIS stubbed, historical real)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_context_full_enrichment(client):
    email = _unique_email("ctx-full")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client,
        token,
        desc="Waterlogging after overnight rain in Madhapur.",
        category="WATER",
        lat=_SEED_LAT,
        lon=_SEED_LON,
    )

    async with async_session_factory() as db:
        run: AgentRun = await _agent(weather_client=_weather_client()).run(
            db, complaint_id=uuid.UUID(complaint_id)
        )

    assert run.status == AgentStatus.SUCCEEDED
    assert run.agent == "context"
    result = run.structured_result
    assert result is not None
    assert result["weather_context"]["available"] is True
    assert result["weather_context"]["cached"] is False
    assert result["weather_context"]["temperature_c"] == 28.4
    assert result["gis_context"]["ward_code"] == "W-002"
    assert result["gis_context"]["available"] is True
    assert result["infrastructure_context"]["hospitals"] == 1
    assert result["infrastructure_context"]["bus_stops"] == 1
    assert isinstance(result["historical_context"]["total_prior"], int)
    names = {s["name"] for s in result["sources"]}
    assert {"open-meteo", "nominatim", "postgis-historical", "postgis-critical-locations"} <= names
    assert result["summary"]
    await _delete_user(email)


@pytest.mark.asyncio
async def test_run_context_weather_unavailable_degrades(client):
    email = _unique_email("ctx-down")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client,
        token,
        desc="Litter in the park.",
        category="SANITATION",
        lat=_SEED_LAT,
        lon=_SEED_LON,
    )

    async with async_session_factory() as db:
        run = await _agent(weather_client=_failing_weather_client()).run(
            db, complaint_id=uuid.UUID(complaint_id)
        )

    assert run.status == AgentStatus.SUCCEEDED  # never fails the run
    result = run.structured_result
    assert result["weather_context"]["available"] is False
    # Other contexts still resolved.
    assert result["gis_context"]["available"] is True
    assert result["infrastructure_context"]["hospitals"] == 1
    await _delete_user(email)


@pytest.mark.asyncio
async def test_run_context_without_coordinates_uses_ward_only(client):
    email = _unique_email("ctx-no-coord")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client,
        token,
        desc="Silt blocking the storm drain.",
        category="DRAINAGE",
        lat=_SEED_LAT,
        lon=_SEED_LON,
    )

    # Remove the complaint's location so there are no coordinates.
    from sqlalchemy.orm import selectinload

    async with async_session_factory() as db:
        complaint = await db.scalar(
            select(Complaint)
            .where(Complaint.id == uuid.UUID(complaint_id))
            .options(selectinload(Complaint.complaint_location))
        )
        assert complaint.complaint_location is not None
        await db.delete(complaint.complaint_location)
        await db.commit()

    async with async_session_factory() as db:
        run = await _agent(weather_client=_weather_client()).run(
            db, complaint_id=uuid.UUID(complaint_id)
        )

    assert run.status == AgentStatus.SUCCEEDED
    result = run.structured_result
    # No coords → weather/GIS locations unavailable, but the complaint's ward
    # may still be surfaced and historical context is still computed.
    assert result["weather_context"]["available"] is False
    assert result["gis_context"]["latitude"] is None
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Agent-level: cache semantics (Redis is down → exercised via the cache layer)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_context_cache_miss_does_live_fetch_and_stores(client, monkeypatch):
    email = _unique_email("ctx-cachemiss")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client,
        token,
        desc="Pothole on the ring road.",
        category="ROAD",
        lat=_SEED_LAT,
        lon=_SEED_LON,
    )

    stored: list[tuple[str, object, int]] = []

    async def fake_get(*_a, **_k):
        return None, False  # always a miss

    async def fake_set(settings, key, value, ttl):
        stored.append((key, value, ttl))

    monkeypatch.setattr("app.agents.context_agent.cache_get_json", fake_get)
    monkeypatch.setattr("app.agents.context_agent.cache_set_json", fake_set)

    async with async_session_factory() as db:
        run = await _agent(weather_client=_weather_client()).run(
            db, complaint_id=uuid.UUID(complaint_id)
        )

    assert run.status == AgentStatus.SUCCEEDED
    result = run.structured_result
    assert result["weather_context"]["cached"] is False
    # A fresh fetch must have been cached with the configured TTL.
    assert len(stored) == 1
    key, payload, ttl = stored[0]
    assert _SETTINGS.WEATHER_CACHE_TTL_SECONDS == ttl
    assert payload["_retrieved_at"]
    assert "weather" in key
    await _delete_user(email)


@pytest.mark.asyncio
async def test_run_context_cache_hit_skips_network(client, monkeypatch):
    email = _unique_email("ctx-cachehit")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client,
        token,
        desc="Falling tree branch near the road.",
        category="ROAD",
        lat=_SEED_LAT,
        lon=_SEED_LON,
    )

    calls: list = []

    async def fake_get(*_a, **_k):
        return {"_payload": _SAMPLE_WEATHER, "_retrieved_at": "2026-09-04T00:00:00Z"}, True

    async def fake_getter(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json=_SAMPLE_WEATHER)

    monkeypatch.setattr("app.agents.context_agent.cache_get_json", fake_get)

    weather_client = httpx.AsyncClient(transport=httpx.MockTransport(fake_getter))
    async with async_session_factory() as db:
        run = await _agent(weather_client=weather_client).run(
            db, complaint_id=uuid.UUID(complaint_id)
        )

    assert run.status == AgentStatus.SUCCEEDED
    result = run.structured_result
    # Cache hit → weather served from cache, no network request performed.
    assert result["weather_context"]["cached"] is True
    assert result["weather_context"]["temperature_c"] == 28.4
    assert calls == []
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Cache helper graceful degradation (Redis unreachable)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cache_helper_degrades_when_redis_down(monkeypatch):
    async def boom(*_a, **_k):
        raise ConnectionError("no redis")

    monkeypatch.setattr("app.core.cache.get_redis", boom)

    from app.core.cache import cache_get_json, cache_set_json

    value, hit = await cache_get_json(_SETTINGS, "some:key")
    assert value is None and hit is False  # graceful miss fallback
    await cache_set_json(_SETTINGS, "some:key", {"a": 1}, 60)  # never raises


# --------------------------------------------------------------------------- #
# API + RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_context_requires_auth(client):
    r = await client.post(f"{_BASE}/{uuid.uuid4()}/context")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_context_requires_access(client):
    owner_email = _unique_email("ctx-ow")
    other_email = _unique_email("ctx-oth")
    owner_token = await _citizen_token(owner_email)
    other_token = await _citizen_token(other_email)
    complaint_id = await _create_complaint(
        client,
        owner_token,
        desc="Some issue.",
        category="ROAD",
        lat=_SEED_LAT,
        lon=_SEED_LON,
    )
    r = await client.post(
        f"{_BASE}/{complaint_id}/context", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert r.status_code == 403, r.text
    await _delete_user(owner_email)
    await _delete_user(other_email)


@pytest.mark.asyncio
async def test_api_context_404_unknown_complaint(client):
    email = _unique_email("ctx-404")
    token = await _citizen_token(email)
    r = await client.post(
        f"{_BASE}/{uuid.uuid4()}/context", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 404, r.text
    await _delete_user(email)


@pytest.mark.asyncio
async def test_api_context_full_run_and_result(client, monkeypatch):
    email = _unique_email("ctx-api")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client,
        token,
        desc="Mosquito breeding in standing water.",
        category="SANITATION",
        lat=_SEED_LAT,
        lon=_SEED_LON,
    )

    monkeypatch.setattr(
        "app.services.context_service._agent",
        lambda: _agent(weather_client=_weather_client()),
    )

    resp = await client.post(
        f"{_BASE}/{complaint_id}/context", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "SUCCEEDED"
    result = body["result"]
    assert result["weather_context"]["available"] is True
    assert result["gis_context"]["ward_code"] == "W-002"
    assert result["infrastructure_context"]["hospitals"] == 1

    getr = await client.get(
        f"{_BASE}/{complaint_id}/context-result", headers={"Authorization": f"Bearer {token}"}
    )
    assert getr.status_code == 200, getr.text
    out = getr.json()
    assert out["agent"] == "context"
    assert out["status"] == "SUCCEEDED"
    assert out["structured_result"]["summary"]
    await _delete_user(email)


@pytest.mark.asyncio
async def test_api_context_result_none_before_run(client):
    email = _unique_email("ctx-null")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client,
        token,
        desc="Nothing has context yet.",
        category="ROAD",
        lat=_SEED_LAT,
        lon=_SEED_LON,
    )
    getr = await client.get(
        f"{_BASE}/{complaint_id}/context-result", headers={"Authorization": f"Bearer {token}"}
    )
    assert getr.status_code == 200, getr.text
    assert getr.json() is None
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Missing external config resilience
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_context_missing_weather_config_degrades(client):
    email = _unique_email("ctx-noconfig")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client,
        token,
        desc="Overflowing garbage bin.",
        category="SANITATION",
        lat=_SEED_LAT,
        lon=_SEED_LON,
    )

    # A settings copy with the weather base URL blanked out.
    blanked = _SETTINGS.model_copy(update={"WEATHER_BASE_URL": ""})

    async with async_session_factory() as db:
        run = await _agent(settings=blanked, weather_client=None).run(
            db, complaint_id=uuid.UUID(complaint_id)
        )

    assert run.status == AgentStatus.SUCCEEDED  # missing config never fails run
    result = run.structured_result
    assert result["weather_context"]["available"] is False
    assert result["gis_context"]["ward_code"] == "W-002"
    await _delete_user(email)
