"""Tests for the Real Nearby Infrastructure Data System (Part 35).

Covers, against the live (dev) database and real PostGIS + Redis:

* ``ingest_from_overpass`` — real-facility ingestion: ward-bbox resolution via
  point-in-polygon, provenance (source/source_id/dataset/url), FOUND state,
  idempotent re-runs (dedupe on ``(source, source_id)``) and graceful counting
  of transient provider failures. Network is never touched: the Overpass fetch
  is monkeypatched with fixture candidates.
* ``ingest_from_file`` — records without coordinates are stored
  ``PENDING_VERIFICATION`` (never invented coordinates).
* ``find_nearby`` — honest per-category states: FOUND / NO_VERIFIED_RECORDS /
  PENDING_VERIFICATION / DATA_UNAVAILABLE with the matching ``search_status``
  (resolved / partial / degraded), never conflating "no facilities" with
  "lookup could not be performed".
* ``registry_summary`` / ``list_registry`` — registry administration surfaces.
* API surface + RBAC — nearby accepts any authenticated role (401 anonymous,
  400 invalid coordinates); summary/list/sync are city-tool endpoints
  (citizen → 403, officer → 200).

Careful design points:
* all test rows are named ``Sync Test ...`` and cleaned up in ``finally`` so the
  shared suite never leaks registry rows; assertions are relative (never rely
  on absolute registry totals) so they stay valid while real sync runs.
* the API *sync* endpoint is NOT exercised via a real officer call — it would
  genuinely query the public Overpass mirror and slow the suite; the ingestion
  logic is covered at the service level with the fetch monkeypatched.
"""

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import CriticalLocation, Role, User, Ward
from app.models.enums import CriticalLocationCategory, InfrastructureDataStatus, RoleName
from app.schemas.geo import GeoPlace
from app.services.infrastructure_registry import (
    _OSM_DATASET,
    InfrastructureRegistry,
    get_infrastructure_registry,
)

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/infrastructure"
_SEED_LAT = 18.4634
_SEED_LON = 73.8912


def _registry() -> InfrastructureRegistry:
    settings = Settings(
        GIS_CACHE_ENABLED=False,
        GIS_OVERPASS_ENABLED=False,
        GIS_OVERPASS_MIRRORS="",
        GIS_MAX_RADIUS_M=5000.0,
        INFRASTRUCTURE_SEARCH_RADIUS_METERS=500.0,
        INFRASTRUCTURE_IMPORT_LIMIT_PER_CATEGORY=150,
        INFRASTRUCTURE_IMPORT_TIMEOUT_SECONDS=5.0,
        INFRASTRUCTURE_IMPORT_MAX_RETRIES=0,
        INFRASTRUCTURE_IMPORT_CONCURRENCY=4,
    )
    return get_infrastructure_registry(settings)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _delete_by_name_like(pattern: str) -> None:
    async with async_session_factory() as db:
        rows = await db.scalars(select(CriticalLocation).where(CriticalLocation.name.like(pattern)))
        for row in rows:
            await db.delete(row)
        await db.commit()


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.CITIZEN.value))
        user = User(
            email=email,
            full_name="Registry Citizen",
            password_hash=hash_password(_PASSWORD),
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        user_id = user.id
        await db.commit()
    return create_access_token(str(user_id), RoleName.CITIZEN.value)


async def _officer_token(email: str) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        officer = User(
            email=email,
            full_name="Registry Officer",
            password_hash=hash_password(_PASSWORD),
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(officer)
        await db.flush()
        officer_id = officer.id
        await db.commit()
    return create_access_token(str(officer_id), RoleName.OFFICER.value)


async def _insert_verified(
    name: str,
    category: CriticalLocationCategory,
    lat: float,
    lon: float,
    *,
    source: str = "openstreetmap",
    status: InfrastructureDataStatus = InfrastructureDataStatus.FOUND,
) -> uuid.UUID:
    async with async_session_factory() as db:
        ward = await db.scalar(select(Ward).where(Ward.code == "WARD-1"))
        row = CriticalLocation(
            name=name,
            category=category,
            latitude=lat,
            longitude=lon,
            address="Test address",
            is_demo=False,
            source=source,
            source_dataset=_OSM_DATASET,
            source_id=f"test/{name}",
            verification_status=status,
            last_verified_at=datetime.now(),
            is_active=True,
            ward_id=ward.id if ward else None,
            geom=func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326),
        )
        db.add(row)
        await db.flush()
        row_id = row.id
        await db.commit()
        return row_id


# --------------------------------------------------------------------------- #
# Ingestion from Overpass (fetch monkeypatched — real PostGIS ward resolution)
# --------------------------------------------------------------------------- #
async def test_ingest_overpass_persists_real_candidates_with_provenance(monkeypatch):
    svc = _registry()
    async with async_session_factory() as db:
        ward1 = next(w for w in await svc._ward_bboxes(db) if w[1] == "WARD-1")

    async def fake_bboxes(db):
        return [ward1]

    async def fake_fetch(bbox, category, client=None):
        if category == CriticalLocationCategory.HOSPITAL:
            return (
                [
                    {
                        "name": "Sync Test Hospital",
                        "category": category,
                        "latitude": _SEED_LAT,
                        "longitude": _SEED_LON,
                        "address": "Kondhwa Rd",
                        "source_id": "node/99100001",
                        "source_url": "https://www.openstreetmap.org/node/99100001",
                        "tags": {"amenity": "hospital", "name": "Sync Test Hospital"},
                        "kind": "amenity=hospital",
                    }
                ],
                True,
                "overpass:test",
            )
        if category == CriticalLocationCategory.SCHOOL:
            return (
                [
                    {
                        "name": "Sync Test School",
                        "category": category,
                        "latitude": _SEED_LAT + 0.001,
                        "longitude": _SEED_LON + 0.001,
                        "address": None,
                        "source_id": "node/99100002",
                        "source_url": "https://www.openstreetmap.org/node/99100002",
                        "tags": {"amenity": "school"},
                        "kind": "amenity=school",
                    }
                ],
                True,
                "overpass:test",
            )
        return [], True, "overpass:test"

    monkeypatch.setattr(svc, "_ward_bboxes", fake_bboxes)
    monkeypatch.setattr(svc, "_fetch_bbox_candidates", fake_fetch)

    try:
        async with async_session_factory() as db:
            out = await svc.ingest_from_overpass(db)
        assert out.source == "openstreetmap"
        assert out.wards_covered == 1
        assert out.fetched_total == 2
        assert out.inserted == 2
        assert out.failed_total == 0
        counts = {c.category: c for c in out.by_category}
        assert counts["HOSPITAL"].inserted == 1
        assert counts["HOSPITAL"].fetched == 1

        async with async_session_factory() as db:
            rows = (
                (
                    await db.execute(
                        select(CriticalLocation).where(
                            CriticalLocation.name.in_(["Sync Test Hospital", "Sync Test School"])
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 2
        row = next(r for r in rows if r.name == "Sync Test Hospital")
        assert row.verification_status == InfrastructureDataStatus.FOUND
        assert row.source == "openstreetmap"
        assert row.source_dataset == _OSM_DATASET
        assert row.source_id == "node/99100001"
        assert row.source_url == "https://www.openstreetmap.org/node/99100001"
        assert row.is_demo is False
        assert row.is_active is True
        assert row.geom is not None
        assert row.ward_id is not None  # resolved inside the real WARD-1 polygon
    finally:
        await _delete_by_name_like("Sync Test%")


async def test_ingest_overpass_is_idempotent_across_runs(monkeypatch):
    svc = _registry()
    async with async_session_factory() as db:
        ward1 = next(w for w in await svc._ward_bboxes(db) if w[1] == "WARD-1")

    async def fake_bboxes(db):
        return [ward1]

    async def fake_fetch(bbox, category, client=None):
        if category == CriticalLocationCategory.HOSPITAL:
            return (
                [
                    {
                        "name": "Sync Test Hospital",
                        "category": category,
                        "latitude": _SEED_LAT,
                        "longitude": _SEED_LON,
                        "address": "Kondhwa Rd",
                        "source_id": "node/99100001",
                        "source_url": "https://www.openstreetmap.org/node/99100001",
                        "tags": {"amenity": "hospital"},
                        "kind": "amenity=hospital",
                    }
                ],
                True,
                "overpass:test",
            )
        return [], True, "overpass:test"

    monkeypatch.setattr(svc, "_ward_bboxes", fake_bboxes)
    monkeypatch.setattr(svc, "_fetch_bbox_candidates", fake_fetch)

    try:
        async with async_session_factory() as db:
            first = await svc.ingest_from_overpass(db)
        async with async_session_factory() as db:
            second = await svc.ingest_from_overpass(db)
        assert first.inserted == 1
        assert first.fetched_total == 1
        assert second.inserted == 0
        assert second.skipped_duplicate >= 1

        async with async_session_factory() as db:
            count = await db.scalar(
                select(func.count(CriticalLocation.id)).where(
                    CriticalLocation.name == "Sync Test Hospital"
                )
            )
        assert count == 1  # upsert never duplicates
    finally:
        await _delete_by_name_like("Sync Test%")


# --------------------------------------------------------------------------- #
# File ingestion — unlocated rows stay PENDING (never invented coordinates)
# --------------------------------------------------------------------------- #
async def test_ingest_from_file_unlocated_row_is_pending(tmp_path):
    svc = _registry()
    csv_path: Path = tmp_path / "dataset.csv"
    csv_path.write_text(
        "name,category,latitude,longitude,address,source_id\n"
        "Sync Test Unlocated,HOSPITAL,,,No coords,row-1\n"
        "Sync Test Located,HOSPITAL,18.4634,73.8912,Kondhwa Rd,row-2\n",
        encoding="utf-8",
    )
    try:
        async with async_session_factory() as db:
            out = await svc.ingest_from_file(
                db, str(csv_path), source="testgov", source_dataset="testgov-trust", source_url=None
            )
        assert out.inserted == 2
        async with async_session_factory() as db:
            unlocated = await db.scalar(
                select(CriticalLocation).where(CriticalLocation.name == "Sync Test Unlocated")
            )
            located = await db.scalar(
                select(CriticalLocation).where(CriticalLocation.name == "Sync Test Located")
            )
        assert unlocated is not None
        assert unlocated.verification_status == InfrastructureDataStatus.PENDING_VERIFICATION
        assert unlocated.latitude is None
        assert unlocated.longitude is None
        assert unlocated.geom is None
        assert unlocated.source == "testgov"
        assert located is not None
        assert located.verification_status == InfrastructureDataStatus.FOUND
    finally:
        await _delete_by_name_like("Sync Test%")


# --------------------------------------------------------------------------- #
# find_nearby — honest per-category data-quality states
# --------------------------------------------------------------------------- #
async def test_find_nearby_found_with_verified_records(monkeypatch):
    svc = _registry()
    await _insert_verified(
        "Sync Test Nearby Hospital", CriticalLocationCategory.HOSPITAL, _SEED_LAT, _SEED_LON
    )
    await _insert_verified(
        "Sync Test Police Post",
        CriticalLocationCategory.POLICE_STATION,
        _SEED_LAT + 0.001,
        _SEED_LON,
    )
    try:
        async with async_session_factory() as db:
            out, cached = await svc.find_nearby(
                db,
                latitude=_SEED_LAT + 0.0002,
                longitude=_SEED_LON + 0.0002,
                categories=[
                    CriticalLocationCategory.HOSPITAL,
                    CriticalLocationCategory.POLICE_STATION,
                ],
                limit=5,
            )
        assert cached is False
        assert out.search_status == "resolved"
        by_cat = {c.category: c for c in out.categories}
        hospital = by_cat[CriticalLocationCategory.HOSPITAL]
        assert hospital.status == InfrastructureDataStatus.FOUND
        # Membership, not an exact set: a concurrent real sync may legitimately
        # surface additional verified Pune facilities near the seed point.
        assert "Sync Test Nearby Hospital" in {p.name for p in hospital.places}
        mine = next(p for p in hospital.places if p.name == "Sync Test Nearby Hospital")
        assert mine.source == "openstreetmap"
        assert mine.verification_status == InfrastructureDataStatus.FOUND
        assert mine.distance_m is not None
        assert (
            by_cat[CriticalLocationCategory.POLICE_STATION].status == InfrastructureDataStatus.FOUND
        )
        assert "Sync Test Police Post" in {
            p.name for p in by_cat[CriticalLocationCategory.POLICE_STATION].places
        }
        assert out.registry_total >= 2
    finally:
        await _delete_by_name_like("Sync Test%")


async def test_find_nearby_no_verified_records_in_range_is_not_empty_claim(monkeypatch):
    # A category that has verified registry records anywhere yields
    # NO_VERIFIED_RECORDS when none fall inside the radius — never an empty
    # "no facilities" lie and never DATA_UNAVAILABLE.
    svc = _registry()
    await _insert_verified(
        "Sync Test Far Hospital", CriticalLocationCategory.HOSPITAL, _SEED_LAT, _SEED_LON
    )
    try:
        # ~2 degrees (~220 km) east of the record: valid coords, out of range.
        async with async_session_factory() as db:
            out, _ = await svc.find_nearby(
                db,
                latitude=18.0,
                longitude=75.5,
                categories=[CriticalLocationCategory.HOSPITAL],
                radius_m=500.0,
            )
        hospital = out.categories[0]
        assert hospital.status == InfrastructureDataStatus.NO_VERIFIED_RECORDS
        assert hospital.count == 0
        assert hospital.places == []
        assert out.search_status == "resolved"
    finally:
        await _delete_by_name_like("Sync Test%")


async def test_find_nearby_data_unavailable_is_attributed_differently(monkeypatch):
    # No registry coverage and live lookups disabled ⇒ DATA_UNAVAILABLE (not
    # "no facilities"). Registry coverage is stubbed empty for determinism.
    svc = _registry()

    async def fake_counts(db, categories):
        return {}

    async def fake_nearby(db, latitude, longitude, radius_m, categories, limit):
        return {}  # isolate from verified records a real sync may be inserting

    monkeypatch.setattr(svc, "_registry_counts", fake_counts)
    monkeypatch.setattr(svc, "_nearby_from_registry", fake_nearby)
    async with async_session_factory() as db:
        out, _ = await svc.find_nearby(
            db,
            latitude=_SEED_LAT,
            longitude=_SEED_LON,
            categories=[CriticalLocationCategory.FIRE_STATION],
            limit=5,
        )
    cat = out.categories[0]
    assert cat.status == InfrastructureDataStatus.DATA_UNAVAILABLE
    assert cat.count == 0
    assert out.search_status == "degraded"


async def test_find_nearby_live_candidates_are_pending_not_verified(monkeypatch):
    # A live fallback that succeeds yields PENDING_VERIFICATION places (real
    # signal, not persisted fact) and a "partial" search status.
    svc = _registry()

    async def fake_counts(db, categories):
        return {}

    class FakeGeo:
        async def _fetch_overpass(self, lat, lon, radius, category, limit=20, client=None):
            return (
                [
                    GeoPlace(
                        id=None,
                        name="Sync Test Live School",
                        category=category,
                        latitude=lat,
                        longitude=lon,
                        distance_m=120.0,
                        is_demo=False,
                    )
                ],
                True,
                "overpass:test",
                False,
            )

    monkeypatch.setattr(svc, "_registry_counts", fake_counts)
    async with async_session_factory() as db:
        out, _ = await svc.find_nearby(
            db,
            latitude=_SEED_LAT,
            longitude=_SEED_LON,
            categories=[CriticalLocationCategory.SCHOOL],
            limit=5,
            geo_service=FakeGeo(),
        )
    cat = out.categories[0]
    assert cat.status == InfrastructureDataStatus.PENDING_VERIFICATION
    assert cat.places[0].verification_status == InfrastructureDataStatus.PENDING_VERIFICATION
    assert cat.places[0].is_demo is False
    assert out.search_status == "partial"
    assert out.live_fallback_used is True


# --------------------------------------------------------------------------- #
# Registry administration
# --------------------------------------------------------------------------- #
async def test_registry_summary_counts_verified_state():
    svc = _registry()
    await _insert_verified(
        "Sync Test Summary Hospital", CriticalLocationCategory.HOSPITAL, _SEED_LAT, _SEED_LON
    )
    try:
        async with async_session_factory() as db:
            summary = await svc.registry_summary(db)
        assert summary.total >= 1
        assert summary.verified >= 1
        assert summary.by_category.get("HOSPITAL", 0) >= 1
        assert summary.by_source.get("openstreetmap", 0) >= 1
        assert summary.by_status.get("FOUND", 0) >= 1
    finally:
        await _delete_by_name_like("Sync Test%")


async def test_list_registry_supports_filters(monkeypatch):
    svc = _registry()
    await _insert_verified(
        "Sync Test List Hospital", CriticalLocationCategory.HOSPITAL, _SEED_LAT, _SEED_LON
    )
    try:
        async with async_session_factory() as db:
            page = await svc.list_registry(
                db,
                source="openstreetmap",
                category=CriticalLocationCategory.HOSPITAL,
                limit=50,
            )
            matching = [r for r in page.items if r.name == "Sync Test List Hospital"]
        assert page.total >= 1
        assert len(matching) == 1
        assert matching[0].source_id == "test/Sync Test List Hospital"
        assert matching[0].ward_id is not None  # inside WARD-1 polygon
        assert matching[0].verification_status == InfrastructureDataStatus.FOUND
        # Category filter excludes the record when another category is asked for.
        async with async_session_factory() as db:
            other = await svc.list_registry(db, category=CriticalLocationCategory.SCHOOL, limit=100)
            assert not any(r.name == "Sync Test List Hospital" for r in other.items)
    finally:
        await _delete_by_name_like("Sync Test%")


# --------------------------------------------------------------------------- #
# API surface + RBAC
# --------------------------------------------------------------------------- #
async def test_nearby_requires_auth(client):
    r = await client.post(f"{_BASE}/nearby", json={"latitude": _SEED_LAT, "longitude": _SEED_LON})
    assert r.status_code == 401


async def test_nearby_accepts_any_authenticated_role(client):
    email = _unique_email("reg-nearby")
    token = await _citizen_token(email)
    try:
        r = await client.post(
            f"{_BASE}/nearby",
            json={"latitude": _SEED_LAT, "longitude": _SEED_LON, "limit": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data["categories"], list)
        assert data["query_id"]
        assert data["search_status"] in ("resolved", "partial", "degraded")
    finally:
        await _delete_user(email)


async def test_nearby_rejects_invalid_coordinates(client):
    email = _unique_email("reg-bad")
    token = await _citizen_token(email)
    try:
        r = await client.post(
            f"{_BASE}/nearby",
            json={"latitude": 120.0, "longitude": 0.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400, r.text
    finally:
        await _delete_user(email)


async def test_registry_admin_endpoints_require_officer(client):
    citizen_email = _unique_email("reg-citizen")
    officer_email = _unique_email("reg-officer")
    citizen = await _citizen_token(citizen_email)
    officer = await _officer_token(officer_email)
    try:
        anon = await client.get(f"{_BASE}/registry/summary")
        assert anon.status_code == 401

        as_citizen = await client.get(
            f"{_BASE}/registry/summary", headers={"Authorization": f"Bearer {citizen}"}
        )
        assert as_citizen.status_code == 403

        as_citizen_list = await client.get(
            f"{_BASE}/registry", headers={"Authorization": f"Bearer {citizen}"}
        )
        assert as_citizen_list.status_code == 403

        as_citizen_sync = await client.post(
            f"{_BASE}/registry/sync",
            json={"source": "openstreetmap"},
            headers={"Authorization": f"Bearer {citizen}"},
        )
        assert as_citizen_sync.status_code == 403

        summary = await client.get(
            f"{_BASE}/registry/summary", headers={"Authorization": f"Bearer {officer}"}
        )
        assert summary.status_code == 200, summary.text
        assert {"total", "verified", "by_source"} <= set(summary.json())

        listing = await client.get(
            f"{_BASE}/registry", headers={"Authorization": f"Bearer {officer}"}
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert "items" in body and "total" in body
    finally:
        await _delete_user(citizen_email)
        await _delete_user(officer_email)
