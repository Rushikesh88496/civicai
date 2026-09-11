"""Tests for the GIS / Ward Detection & Spatial Intelligence module (Part 10).

Covers, against the live (dev) database and real PostGIS:

* reverse geocoding — Nominatim success + graceful degradation on
  rate-limit (429), transport error, and timeouts (no real network: the
  database-backed lookup tests rely on injected ``httpx.MockTransport``).
* ward detection — point-in-polygon returns the containing demo ward for the
  Hyderabad seed area and ``None`` for coordinates outside every boundary.
* nearby places & critical infrastructure — ``ST_DWithin`` geography-distance
  lookup returns roads/hospitals/schools/bus stops ordered by distance and the
  radius is clamped to ``GIS_MAX_RADIUS_M``.
* distance math — pure great-circle unit tests.
* API surface + RBAC — authenticated users (any role) may call lookup/wards/
  distance; unauthenticated requests get 401; out-of-range coordinates → 400.
* demo labeling — ward + facility rows are surfaced with ``is_demo=True``.
"""

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import User
from app.schemas.auth import RegisterIn
from app.services import auth_service
from app.services.geo_service import GeoService, get_geo_service
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/geo"
_SETTINGS = get_settings()

# Hyderabad seed area (inside the reference WARD-1 polygon).
_SEED_LAT = 17.4327
_SEED_LON = 78.3885


def _unique_email(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="GIS Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


# --------------------------------------------------------------------------- #
# Distance math (pure, no DB)
# --------------------------------------------------------------------------- #
def test_calculate_distance_equator_degree_degrees():
    svc = get_geo_service()
    # 1 degree of latitude ≈ 111.2 km.
    d = svc.calculate_distance(0.0, 0.0, 1.0, 0.0)
    assert pytest.approx(d, rel=0.01) == 111_195.0


def test_calculate_distance_same_point_is_zero():
    svc = get_geo_service()
    assert svc.calculate_distance(17.4327, 78.3885, 17.4327, 78.3885) == 0.0


def test_calculate_distance_symmetric():
    svc = get_geo_service()
    a = svc.calculate_distance(17.43, 78.38, 17.50, 78.50)
    b = svc.calculate_distance(17.50, 78.50, 17.43, 78.38)
    assert a == pytest.approx(b)


def test_calculate_distance_known_city_pair():
    # Mumbai (19.076, 72.8777) → Pune (18.5204, 73.8567) ≈ 120 km.
    svc = get_geo_service()
    d = svc.calculate_distance(19.0760, 72.8777, 18.5204, 73.8567)
    assert pytest.approx(d / 1000.0, rel=0.05) == 120.0


# --------------------------------------------------------------------------- #
# Ward detection (live PostGIS)
# --------------------------------------------------------------------------- #
async def test_find_ward_detects_demo_ward_at_seed_area():
    svc = get_geo_service()
    async with async_session_factory() as db:
        ward = await svc.find_ward(db, _SEED_LAT, _SEED_LON)
    assert ward is not None
    assert ward.code == "WARD-1"
    assert ward.name == "Ward 1"
    assert ward.is_demo is True


async def test_find_ward_none_outside_supported_region():
    svc = get_geo_service()
    async with async_session_factory() as db:
        ward = await svc.find_ward(db, 60.0, 30.0)  # well outside every polygon
    assert ward is None


async def test_find_ward_invalid_coordinates_raises():
    svc = get_geo_service()
    async with async_session_factory() as db:
        with pytest.raises(Exception):
            await svc.find_ward(db, 105.0, 0.0)  # lat out of range


# --------------------------------------------------------------------------- #
# Nearby places & critical infrastructure (live PostGIS)
# --------------------------------------------------------------------------- #
async def test_find_nearby_places_returns_seeded_facilities():
    svc = get_geo_service()
    async with async_session_factory() as db:
        hospital = await svc.find_nearby_places(
            db,
            _SEED_LAT,
            _SEED_LON,
            _SETTINGS.GIS_CRITICAL_RADIUS_M,
            category=None,
        )
    names = {p.name for p in hospital}
    assert "City Central Hospital" in names
    assert "Riverside Primary School" in names
    assert "Market Street Bus Stop" in names
    assert all(p.is_demo is True for p in hospital)


async def test_find_nearby_places_filters_by_category():
    from app.models.enums import CriticalLocationCategory

    svc = get_geo_service()
    async with async_session_factory() as db:
        hospitals = await svc.find_nearby_places(
            db, _SEED_LAT, _SEED_LON, 5000.0, category=CriticalLocationCategory.HOSPITAL
        )
    assert {p.name for p in hospitals} == {"City Central Hospital"}


async def test_find_nearby_places_radius_is_clamped():
    svc = get_geo_service()
    huge = 50_000_000.0  # far above GIS_MAX_RADIUS_M
    async with async_session_factory() as db:
        places = await svc.find_nearby_places(db, _SEED_LAT, _SEED_LON, huge)
    # Every returned place must be within the *clamped* max radius.
    for p in places:
        assert (p.distance_m or 0.0) <= _SETTINGS.GIS_MAX_RADIUS_M + 1.0


# --------------------------------------------------------------------------- #
# Reverse geocoding (injected httpx transport — no network)
# --------------------------------------------------------------------------- #
def _svc_with_client(handler) -> tuple[GeoService, httpx.AsyncClient]:
    svc = get_geo_service()
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url=_SETTINGS.GIS_BASE_URL)
    return svc, client


async def test_reverse_geocode_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"display_name": "Durgam Cheruvu Road, Madhapur, Hyderabad"},
        )

    svc, client = _svc_with_client(handler)
    out = await svc.reverse_geocode(_SEED_LAT, _SEED_LON, client)
    assert out.degraded is False
    assert out.source == "nominatim"
    assert "Durgam Cheruvu Road" in (out.address or "")


async def test_reverse_geocode_rate_limit_degrades():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Rate Limited"})

    svc, client = _svc_with_client(handler)
    out = await svc.reverse_geocode(_SEED_LAT, _SEED_LON, client)
    assert out.degraded is True
    assert out.address is None


async def test_reverse_geocode_transport_error_degrades():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out")

    svc, client = _svc_with_client(handler)
    out = await svc.reverse_geocode(_SEED_LAT, _SEED_LON, client)
    assert out.degraded is True
    assert out.address is None


async def test_reverse_geocode_server_error_degrades():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    svc, client = _svc_with_client(handler)
    out = await svc.reverse_geocode(_SEED_LAT, _SEED_LON, client)
    assert out.degraded is True
    assert out.address is None


# --------------------------------------------------------------------------- #
# API surface + RBAC
# --------------------------------------------------------------------------- #
async def test_lookup_requires_auth(client):
    r = await client.post(f"{_BASE}/lookup", json={"latitude": _SEED_LAT, "longitude": _SEED_LON})
    assert r.status_code == 401


async def test_wards_requires_auth(client):
    r = await client.get(f"{_BASE}/wards")
    assert r.status_code == 401


async def test_distance_requires_auth(client):
    r = await client.post(
        f"{_BASE}/distance",
        json={"latitude_a": 1.0, "longitude_a": 2.0, "latitude_b": 3.0, "longitude_b": 4.0},
    )
    assert r.status_code == 401


async def test_lookup_valid_auth_returns_demo_payload(client):
    email = _unique_email("geo-lookup")
    token = await _citizen_token(email)
    try:
        r = await client.post(
            f"{_BASE}/lookup",
            json={"latitude": _SEED_LAT, "longitude": _SEED_LON, "radius_m": 5000.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ward"]["code"] == "WARD-1"
        assert data["ward"]["is_demo"] is True
        assert data["demo_label"] == "DEMO DATA"
        assert data["address"]["source"] in ("nominatim",)
        # Critical infra should be populated from seeded demo rows.
        assert {"hospitals", "schools", "bus_stops", "nearby_roads"} <= set(data) and any(
            data["hospitals"]
        )
        assert all(p["is_demo"] is True for p in data["hospitals"])
    finally:
        await _delete_user(email)


async def test_lookup_accepts_any_authenticated_role(client):
    # Any authenticated role (here: OFFICER) may call the geo endpoints.
    from app.core.security import hash_password
    from app.models import Role
    from app.models.enums import RoleName

    email = _unique_email("geo-officer")
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        officer = User(
            email=email,
            full_name="GIS Officer",
            password_hash=hash_password(_PASSWORD),
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(officer)
        await db.flush()
        officer_id = officer.id
        await db.commit()
    token = create_access_token(str(officer_id), RoleName.OFFICER.value)
    try:
        r = await client.get(f"{_BASE}/wards", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert {"wards"} <= set(r.json())
    finally:
        await _delete_user(email)


async def test_distance_endpoint_pure_math(client):
    email = _unique_email("geo-dist")
    token = await _citizen_token(email)
    try:
        r = await client.post(
            f"{_BASE}/distance",
            json={"latitude_a": 0.0, "longitude_a": 0.0, "latitude_b": 1.0, "longitude_b": 0.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert pytest.approx(data["distance_km"], rel=0.01) == 111.195
        assert data["distance_m"] > 0
    finally:
        await _delete_user(email)


async def test_lookup_out_of_range_coordinates_returns_422(client):
    # The request schema bounds (lat/lon) reject out-of-range input at the
    # validation layer, before the service is invoked → 422.
    email = _unique_email("geo-bad")
    token = await _citizen_token(email)
    try:
        r = await client.post(
            f"{_BASE}/lookup",
            json={"latitude": 120.0, "longitude": 0.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422, r.text
    finally:
        await _delete_user(email)


def test_validate_coordinates_rejects_invalid():
    # The service-level guard also protects direct (non-API) callers.
    svc = get_geo_service()
    for lat, lon in [(120.0, 0.0), (0.0, 200.0), (-91.0, 0.0), (0.0, -181.0)]:
        with pytest.raises(Exception):
            svc.validate_coordinates(lat, lon)
    # Valid values pass without raising.
    svc.validate_coordinates(0.0, 0.0)


async def test_wards_returns_demo_boundary_rings(client):
    email = _unique_email("geo-wards")
    token = await _citizen_token(email)
    try:
        r = await client.get(f"{_BASE}/wards", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        data = r.json()
        wards = data["wards"]
        assert any(w["code"] == "WARD-1" for w in wards)
        for w in wards:
            assert w["is_demo"] is True
            assert "geometry" in w and len(w["geometry"]) >= 5  # closed polygon
    finally:
        await _delete_user(email)
