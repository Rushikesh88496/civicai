"""Tests for the Automatic Intelligence Pipeline (INTELLIGENCE PIPELINE).

The context-enrichment agent and the deterministic priority engine already
persist structured results to ``agent_runs`` (and priority history), but nothing
ran them automatically. These tests prove the auto-pipeline now wires itself
into the officer complaint detail view:

* **Auto-run** — an officer GET on the detail endpoint enriches context AND
  computes a deterministic priority score for a complaint that has neither,
  persisting both.
* **Idempotency** — a second detail view does not create new runs.
* **Role gate** — a citizen viewing their own complaint never triggers runs.
* **FAILED retry** — a FAILED context run is replaced by a fresh SUCCEEDED run
  on the next detail view.
* **Freshness** — when a newer validated upstream signal (triage) arrives after
  the last score, the next detail view recomputes the deterministic score.
* **Governance flag** — ``COMPLAINTS_AUTO_INTELLIGENCE=false`` (the suite
  default) leaves behaviour exactly as before: detail reads do not trigger runs.
* **Determinism** — the pure scoring engine returns identical scores/buckets for
  identical inputs (no randomness).

External HTTP is stubbed the same way ``test_context.py`` does: Open-Meteo goes
through ``httpx.MockTransport`` and the GIS lookup uses a deterministic stub, so
the auto-pipeline is fast and hermetic. The priority engine itself makes no
external calls (it reads the fresh context rows out of the database).
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from app.agents.context_agent import ContextAgent
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import AgentRun, User
from app.models.enums import AgentStatus, CriticalLocationCategory
from app.schemas.auth import RegisterIn
from app.schemas.geo import (
    GeoLookupOut,
    GeoPlace,
    ReverseGeocodeOut,
    WardDetected,
)
from app.services import auth_service
from tests.helpers import any_active_ward_id, any_officer_token

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"

# Deterministic seed point inside a reference ward — used only for the GIS stub.
_SEED_LAT = 18.4634
_SEED_LON = 73.8912

_SAMPLE_WEATHER = {
    "current": {
        "temperature_2m": 18.4,
        "precipitation": 3.2,
        "rain": 3.2,
        "weather_code": 63,
        "wind_speed_10m": 9.1,
    },
    "daily": {
        "time": ["2026-09-12", "2026-09-13"],
        "temperature_2m_max": [20.0, 21.0],
        "temperature_2m_min": [16.0, 15.0],
        "precipitation_sum": [3.5, 0.0],
    },
}


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Pipeline Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _create_complaint(client, token: str, *, desc: str, category: str) -> str:
    body = {
        "description": desc,
        "category": category,
        "media_ids": [],
        "location": {
            "latitude": _SEED_LAT,
            "longitude": _SEED_LON,
            "address": "Pipeline test location",
            "source": "gps",
            "geopoint_denied": False,
        },
    }
    r = await client.post(_BASE, json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _count_runs(complaint_id: str, agent: str) -> int:
    async with async_session_factory() as db:
        return int(
            await db.scalar(
                select(func.count(AgentRun.id)).where(
                    AgentRun.complaint_id == uuid.UUID(complaint_id),
                    AgentRun.agent == agent,
                )
            )
            or 0
        )


async def _latest_run(complaint_id: str, agent: str) -> AgentRun | None:
    async with async_session_factory() as db:
        return await db.scalar(
            select(AgentRun)
            .where(AgentRun.complaint_id == uuid.UUID(complaint_id), AgentRun.agent == agent)
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )


async def _insert_run(complaint_id: str, *, agent: str, status: AgentStatus) -> None:
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        db.add(
            AgentRun(
                complaint_id=uuid.UUID(complaint_id),
                agent=agent,
                model="test",
                status=status,
                structured_result=(
                    None
                    if status == AgentStatus.FAILED
                    else {"severity": "HIGH", "category": "ROAD"}
                ),
                started_at=now,
                ended_at=now,
            )
        )
        await db.commit()


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


# --------------------------------------------------------------------------- #
# Deterministic GIS stub + weather mock (reused from the test_context suite)
# --------------------------------------------------------------------------- #
class StubGeo:
    def __init__(self, lookup: GeoLookupOut) -> None:
        self._lookup = lookup

    async def geo_lookup(self, db, latitude, longitude, radius_m=None) -> GeoLookupOut:
        return self._lookup


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
        hospitals=[_place("City Central Hospital", CriticalLocationCategory.HOSPITAL, 400.0)],
        schools=[_place("Riverside Primary School", CriticalLocationCategory.SCHOOL, 300.0)],
        bus_stops=[_place("Market Street Bus Stop", CriticalLocationCategory.BUS_STOP, 200.0)],
        critical_infrastructure=[],
        radius_m=get_settings().GIS_CRITICAL_RADIUS_M,
        demo_label=get_settings().GIS_DEMO_LABEL,
        calculated_at=datetime.now(UTC),
    )


def _weather_client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SAMPLE_WEATHER)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def auto_intelligence(monkeypatch):
    """Force COMPLAINTS_AUTO_INTELLIGENCE on for the pipeline tests."""
    monkeypatch.setenv("COMPLAINTS_AUTO_INTELLIGENCE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def stub_agents(monkeypatch, auto_intelligence):
    """Replace the context agent factory with a hermetic (mocked) instance."""
    from app.services import context_service

    def _make(settings=None, **kwargs):
        return ContextAgent(
            settings=settings or get_settings(),
            geo_service=StubGeo(_seed_lookup()),
            weather_client=_weather_client(),
            **kwargs,
        )

    monkeypatch.setattr(context_service, "_agent", _make)
    return _make


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_auto_intelligence_runs_on_officer_detail_view(client, stub_agents):
    email = _unique_email("ip-auto")
    citizen_token = await _citizen_token(email)
    officer_email = _unique_email("ip-officer")
    officer_token = await any_officer_token(officer_email)
    complaint_id = await _create_complaint(
        client, citizen_token, desc="Sewage overflow on the main road.", category="DRAINAGE"
    )

    # A fresh complaint has no intelligence runs yet.
    assert await _count_runs(complaint_id, "context") == 0
    assert await _count_runs(complaint_id, "priority") == 0

    # Officer opens the detail page → the pipeline should auto-run and persist.
    detail = await client.get(
        f"{_BASE}/{complaint_id}", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert detail.status_code == 200, detail.text

    ctx = await client.get(
        f"{_BASE}/{complaint_id}/context-result",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert ctx.status_code == 200, ctx.text
    ctx_run = ctx.json()
    assert ctx_run["status"] == AgentStatus.SUCCEEDED.value
    result = ctx_run["structured_result"]
    assert result is not None
    assert result["weather_context"]["available"] is True
    assert result["weather_context"]["rain_mm"] == 3.2
    assert result["gis_context"]["ward_code"] == "W-002"

    prio = await client.get(
        f"{_BASE}/{complaint_id}/priority-result",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert prio.status_code == 200, prio.text
    prio_run = prio.json()
    assert prio_run["status"] == AgentStatus.SUCCEEDED.value
    assert prio_run["structured_result"] is not None
    score = prio_run["structured_result"]["score"]
    assert isinstance(score, int) and 0 <= score <= 100
    # Severity read off the stored complaint (MEDIUM default here — no triage yet).
    assert prio_run["structured_result"]["inputs"]["severity"] == "MEDIUM"

    ph = await client.get(
        f"{_BASE}/{complaint_id}/priority-history",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert ph.status_code == 200
    assert len(ph.json()["entries"]) >= 1

    await _delete_user(email)
    await _delete_user(officer_email)


@pytest.mark.asyncio
async def test_auto_intelligence_is_idempotent(client, stub_agents):
    email = _unique_email("ip-idem")
    citizen_token = await _citizen_token(email)
    officer_token = await any_officer_token(_unique_email("ip-officer2"))
    complaint_id = await _create_complaint(
        client, citizen_token, desc="Road completely blocked by a fallen tree.", category="ROAD"
    )

    first = await client.get(
        f"{_BASE}/{complaint_id}", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert first.status_code == 200
    ctx_after_first = await _count_runs(complaint_id, "context")
    prio_after_first = await _count_runs(complaint_id, "priority")
    assert ctx_after_first == 1
    assert prio_after_first == 1

    # A plain re-view must NOT create duplicate runs — intelligence persists.
    second = await client.get(
        f"{_BASE}/{complaint_id}", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert second.status_code == 200
    assert await _count_runs(complaint_id, "context") == ctx_after_first
    assert await _count_runs(complaint_id, "priority") == prio_after_first

    await _delete_user(email)


@pytest.mark.asyncio
async def test_citizen_detail_view_does_not_trigger_pipeline(client, stub_agents):
    email = _unique_email("ip-citizen")
    citizen_token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client, citizen_token, desc="Water leak near the playground.", category="WATER"
    )

    detail = await client.get(
        f"{_BASE}/{complaint_id}", headers={"Authorization": f"Bearer {citizen_token}"}
    )
    assert detail.status_code == 200
    assert await _count_runs(complaint_id, "context") == 0
    assert await _count_runs(complaint_id, "priority") == 0

    await _delete_user(email)


@pytest.mark.asyncio
async def test_auto_intelligence_retries_failed_context_run(client, stub_agents):
    email = _unique_email("ip-failed")
    citizen_token = await _citizen_token(email)
    officer_token = await any_officer_token(_unique_email("ip-officer3"))
    complaint_id = await _create_complaint(
        client,
        citizen_token,
        desc="Dark street lights on the school lane.",
        category="STREET_LIGHTING",
    )

    # Simulate an earlier context run that FAILED (e.g. provider outage).
    await _insert_run(complaint_id, agent="context", status=AgentStatus.FAILED)

    detail = await client.get(
        f"{_BASE}/{complaint_id}", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert detail.status_code == 200

    latest = await _latest_run(complaint_id, "context")
    assert latest is not None
    assert latest.status == AgentStatus.SUCCEEDED
    assert latest.structured_result is not None
    assert await _count_runs(complaint_id, "context") == 2  # failed one replaced

    await _delete_user(email)


@pytest.mark.asyncio
async def test_auto_intelligence_rescores_when_triage_newer_than_score(client, stub_agents):
    email = _unique_email("ip-fresh")
    citizen_token = await _citizen_token(email)
    officer_token = await any_officer_token(_unique_email("ip-officer4"))
    complaint_id = await _create_complaint(
        client, citizen_token, desc="Garbage pileup blocking the footpath.", category="GARBAGE"
    )

    first = await client.get(
        f"{_BASE}/{complaint_id}", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert first.status_code == 200
    assert await _count_runs(complaint_id, "priority") == 1

    # A newer validated triage run lands after the score (e.g. officer re-triaged).
    await _insert_run(complaint_id, agent="triage", status=AgentStatus.SUCCEEDED)

    second = await client.get(
        f"{_BASE}/{complaint_id}", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert second.status_code == 200
    assert await _count_runs(complaint_id, "priority") == 2  # fresh score computed

    prio = await client.get(
        f"{_BASE}/{complaint_id}/priority-result",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert prio.status_code == 200
    assert prio.json()["status"] == AgentStatus.SUCCEEDED.value

    await _delete_user(email)


@pytest.mark.asyncio
async def test_auto_intelligence_disabled_flag_skips_pipeline(client):
    """The suite default (COMPLAINTS_AUTO_INTELLIGENCE=false) must be a no-op."""
    email = _unique_email("ip-off")
    citizen_token = await _citizen_token(email)
    officer_token = await any_officer_token(_unique_email("ip-officer5"))
    complaint_id = await _create_complaint(
        client, citizen_token, desc="Pothole needs repair.", category="ROAD"
    )

    detail = await client.get(
        f"{_BASE}/{complaint_id}", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert detail.status_code == 200
    assert await _count_runs(complaint_id, "context") == 0
    assert await _count_runs(complaint_id, "priority") == 0

    await _delete_user(email)


@pytest.mark.asyncio
async def test_deterministic_priority_engine_freezes_score_for_identical_inputs():
    """Same inputs ⇒ same score/bucket — reproducibility, zero randomness."""
    from app.services.priority_engine import Weights, score_priority

    kwargs = dict(
        severity="HIGH",
        population=240,
        hospitals=1,
        schools=1,
        bus_stops=1,
        weather_condition="Light rain",
        rain_mm=3.2,
        weather_available=True,
        complaint_count=4,
        historical_recurrence=6,
        ward_resolved=True,
        time_unresolved_hours=48.0,
        weights=Weights(),
        threshold_p1=80.0,
        threshold_p2=60.0,
        threshold_p3=40.0,
        weather_rain_mm=5.0,
        population_band=1000.0,
        complaint_band=10.0,
        history_band=15.0,
        time_band_hours=168.0,
    )
    s1, b1, f1 = score_priority(**kwargs)
    s2, b2, f2 = score_priority(**kwargs)
    assert s1 == s2
    assert b1 == b2
    assert f1 == f2
    assert 0 <= s1 <= 100
    assert sum(1 for f in f1 if f["present"]) >= 1
