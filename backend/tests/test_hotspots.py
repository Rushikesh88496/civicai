"""Tests for Predictive Civic Hotspots (Part 23).

Layers exercised:

* **Grid geometry** — deterministic cell ids, centroid round-trip, neighbour
  adjacency and out-of-bounds rejection.
* **Leak-freedom of the feature extractor** — trailing features only use events
  strictly before the snapshot date; labels use only the next ``horizon`` days.
* **Corpus determinism** — same seed reproduces identical events; a different
  seed changes them.
* **Provider degradation** — unavailable rain/population are reported as flags,
  never raised errors.
* **End-to-end training** — the API writes an artifact file + a registry row;
  a second train bumps the version and deactivates the previous model.
* **RBAC** — city roles (officer / admin) may train/read while citizens,
  ward-reps and field workers are rejected.
* **Live prediction** — a fresh system lazily trains, real complaints map onto
  grid cells, and the response carries the AI-Prediction disclaimer.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.ml.corpus import build_corpus
from app.ml.external import LiveContextProvider
from app.ml.features import build_feature_frame
from app.ml.grid import HotspotGrid
from app.models import Complaint, ComplaintLocation, PredictiveModel, Role, User, UserProfile
from app.models.enums import ComplaintCategory, RoleName
from app.schemas.auth import RegisterIn
from app.services import auth_service

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/hotspots"
_SETTINGS = get_settings()
_LAT = 17.4327
_LON = 78.3885
_GRID = HotspotGrid(17.40, 78.35, 17.50, 78.49, _SETTINGS.HOTSPOT_CELL_DEG)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _citizen(email: str) -> uuid.UUID:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db, RegisterIn(email=email, password=_PASSWORD, full_name="HS Citizen")
        )
        user = await db.scalar(select(User).where(User.email == email))
        return user.id


async def _role_user(email: str, role_name: str, *, ward_id=None) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == role_name))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=f"{role_name} User",
            role_id=role.id,
            ward_id=ward_id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), role_name)


async def _insert_complaint(
    *,
    user_id: uuid.UUID,
    title: str,
    category: str = "GARBAGE",
    lat: float = _LAT,
    lon: float = _LON,
    created_at: datetime | None = None,
) -> uuid.UUID:
    async with async_session_factory() as db:
        complaint = Complaint(
            user_id=user_id,
            category=ComplaintCategory(category),
            title=title,
            description=f"desc {title}",
        )
        db.add(complaint)
        await db.flush()
        if created_at is not None:
            complaint.created_at = created_at
        db.add(
            ComplaintLocation(
                complaint_id=complaint.id, latitude=lat, longitude=lon, source="gps"
            )
        )
        await db.commit()
        return complaint.id


@pytest.fixture(autouse=True)
async def _fast_settings(tmp_path, monkeypatch):
    """Small, fast training config + isolated artifact directory."""
    for attr, value in (
        ("HOTSPOT_CORPUS_YEARS", 1),
        ("HOTSPOT_SNAPSHOT_EVERY_DAYS", 7),
        ("HOTSPOT_TEST_FINAL_DAYS", 120),
        ("HOTSPOT_CV_FOLDS", 1),
        ("HOTSPOT_N_ESTIMATORS", 30),
        ("HOTSPOT_ARTIFACT_DIR", str(tmp_path)),
    ):
        monkeypatch.setattr(_SETTINGS, attr, value)
    yield


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    async with async_session_factory() as db:
        await db.execute(delete(PredictiveModel))
        await db.execute(delete(ComplaintLocation))
        await db.execute(delete(Complaint))
        await db.execute(delete(User).where(User.email.like("%-%@example.com")))
        await db.commit()


async def _clear_models() -> None:
    async with async_session_factory() as db:
        await db.execute(delete(PredictiveModel))
        await db.commit()


# --------------------------------------------------------------------------- #
# Grid geometry
# --------------------------------------------------------------------------- #
def test_grid_cell_math():
    assert len(_GRID) == 15 * 11
    cid = _GRID.cell_id(_LAT, _LON)
    assert cid == "r3c3"
    lat, lon = _GRID.cell_centroid(cid)
    assert abs(lat - 17.435) < 0.001
    assert abs(lon - 78.385) < 0.001
    corner = _GRID.cell_id(_GRID.min_lat, _GRID.min_lon)
    assert set(_GRID.neighbors(corner)) == {"r1c0", "r0c1"}
    assert _GRID.cell_id(50.0, 100.0) is None
    assert _GRID.cell_id(_GRID.max_lat, _GRID.min_lon) is None  # upper edge is exclusive


def test_grid_replay_idempotent():
    again = HotspotGrid(17.40, 78.35, 17.50, 78.49, _SETTINGS.HOTSPOT_CELL_DEG)
    assert again.all_cells() == _GRID.all_cells()


# --------------------------------------------------------------------------- #
# Feature extractor leak-freedom
# --------------------------------------------------------------------------- #
def _event(day: int, cell: str = "r0c0", category: str = "ROAD"):
    from app.ml.corpus import ComplaintEvent

    ref = datetime(2026, 1, 1, 12, 0, tzinfo=UTC) + timedelta(days=day)
    lat, lon = _GRID.cell_centroid(cell)
    return ComplaintEvent(ts=ref, cell_id=cell, latitude=lat, longitude=lon, category=category)


def test_features_are_strictly_before_and_labels_are_next_window():
    from app.ml.external import LiveContextProvider

    provider = LiveContextProvider(_SETTINGS, population_per_cell={"r0c0": 0.0}).provider()
    # Events at days 0, 2 and 10; day 13 only extends the grid so the day-5
    # label window [6, 12] is fully observed (it stays 0 for that row).
    events = [_event(0), _event(2), _event(10), _event(13)]
    snapshots = [
        datetime(2026, 1, 1, 0, 0, tzinfo=UTC) + timedelta(days=d) for d in (0, 1, 2, 5)
    ]
    frame = build_feature_frame(events, snapshots, _GRID, provider, horizon_days=7)
    only_cell = frame[frame["cell_id"] == "r0c0"]
    row = {r["date"].date(): r for r in only_cell.to_dict("records")}

    d0 = row[datetime(2026, 1, 1, tzinfo=UTC).date()]
    assert d0["trail1"] == 0 and d0["trail7"] == 0  # same-day event excluded
    assert d0["y_reg"] == 1 and d0["y_clf"] == 1  # event at day 2 is in (0, 7]
    assert d0["cat_ROAD_14d"] == 0  # same-day category count excluded too

    d2 = row[datetime(2026, 1, 3, tzinfo=UTC).date()]
    assert d2["trail7"] == 1  # only day-0 event in (-5, 2]
    assert d2["y_reg"] == 0 and d2["y_clf"] == 0  # nothing in (3, 9]

    d5 = row[datetime(2026, 1, 6, tzinfo=UTC).date()]
    assert d5["trail7"] == 2  # day 0 and day 2 only; day 10/13 excluded
    assert d5["y_reg"] == 1  # day-10 event in (5, 12]; day 13 excluded
    assert d5["cat_ROAD_14d"] == 2


def test_features_span_every_grid_cell():
    from app.ml.external import LiveContextProvider

    provider = LiveContextProvider(_SETTINGS, population_per_cell={}).provider()
    events = [_event(0, cell="r3c3", category="WATER"), _event(2, cell="r10c14", category="WATER")]
    snapshots = [datetime(2026, 1, 1, 0, 0, tzinfo=UTC)]
    frame = build_feature_frame(events, snapshots, _GRID, provider, horizon_days=7)
    cols = {c["cell_id"] for c in frame.to_dict("records")}
    assert cols == set(_GRID.all_cells())
    assert len(frame) == len(_GRID)


# --------------------------------------------------------------------------- #
# Corpus determinism
# --------------------------------------------------------------------------- #
def test_corpus_is_deterministic():
    c1 = build_corpus(_GRID, 1, 42)
    c2 = build_corpus(_GRID, 1, 42)
    c3 = build_corpus(_GRID, 1, 43)
    assert len(c1.events) == len(c2.events)
    assert [(e.ts, e.cell_id, e.category) for e in c1.events] == [
        (e.ts, e.cell_id, e.category) for e in c2.events
    ]
    assert [(e.ts, e.cell_id, e.category) for e in c1.events] != [
        (e.ts, e.cell_id, e.category) for e in c3.events
    ]
    # Trailing months contain data so features have context at every snapshot.
    assert c1.events[-1].ts.date() > datetime(2026, 8, 1, tzinfo=UTC).date()


# --------------------------------------------------------------------------- #
# Provider degradation
# --------------------------------------------------------------------------- #
def test_live_provider_degrades_without_data():
    provider = LiveContextProvider(_SETTINGS).provider()
    feats = provider("r0c0", datetime.now(UTC))
    assert feats.rainfall_mm == 0.0 and feats.rainfall_available is False
    assert feats.population_density == 0.0 and feats.population_available is False
    assert feats.infra_available is False

    dense = LiveContextProvider(_SETTINGS, population_per_cell={"r0c0": 2500.0}).provider()
    feats2 = dense("r0c0", datetime.now(UTC))
    assert feats2.population_available is True
    assert 0.0 < feats2.population_density <= 1.0


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #
async def _officer_token() -> str:
    return await _role_user(_unique_email("hs-officer"), RoleName.OFFICER.value)


@pytest.mark.asyncio
async def test_rbac_forbids_non_city_roles(client: TestClient):
    citizen_id = await _citizen(_unique_email("hs-cit"))
    citizen_token = create_access_token(str(citizen_id), "CITIZEN")
    rep_token = await _role_user(
        _unique_email("hs-rep"), RoleName.WARD_REPRESENTATIVE.value
    )
    worker_token = await _role_user(_unique_email("hs-worker"), RoleName.FIELD_WORKER.value)

    for token in (citizen_token, rep_token, worker_token):
        for method, path in (
            ("GET", "/status"),
            ("GET", "/predictions"),
            ("POST", "/train"),
        ):
            rec = await client.request(method, f"{_BASE}{path}", headers=_auth(token))
            assert rec.status_code == 403

    r = await client.get(f"{_BASE}/status")
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------- #
# Training + registry versioning
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_train_persists_artifact_and_version_bumps(client: TestClient):
    token = await _officer_token()
    headers = _auth(token)

    r = await client.post(f"{_BASE}/train", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["trained"] is True
    assert data["version"] == 1
    assert data["rows"] > 0 and data["duration_seconds"] >= 0
    assert "clf" in data["metrics"] and "reg" in data["metrics"] and "baseline" in data["metrics"]
    assert data["metrics"]["clf"]["f1"] is not None
    assert data["metrics"]["reg"]["mae"] >= 0
    assert data["metrics"]["baseline"]["clf"]["f1"] is not None

    async with async_session_factory() as db:
        row = await db.scalar(select(PredictiveModel).where(PredictiveModel.is_active.is_(True)))
        assert row is not None and row.version == 1 and row.artifact_filename.endswith(".joblib")

    # Status reflects the active model + evaluation metrics.
    r = await client.get(f"{_BASE}/status", headers=headers)
    assert r.status_code == 200
    st = r.json()
    assert st["trained"] is True
    assert st["model"]["version"] == 1
    assert st["model"]["metrics"]["clf"]["roc_auc"] is not None

    # Retrain bumps the version and swaps active.
    r = await client.post(f"{_BASE}/train", headers=headers)
    assert r.json()["version"] == 2
    r = await client.get(f"{_BASE}/status", headers=headers)
    assert r.json()["model"]["version"] == 2
    async with async_session_factory() as db:
        old = await db.scalar(select(PredictiveModel).where(PredictiveModel.version == 1))
        assert old is not None and old.is_active is False


# --------------------------------------------------------------------------- #
# Live prediction
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_predictions_lazy_train_and_shape(client: TestClient):
    await _clear_models()
    token = await _officer_token()
    r = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["ai_prediction"] is True
    assert "forecast" in data["disclaimer"].lower()
    assert data["horizon_days"] == 7
    assert data["model"]["version"] >= 1
    assert len(data["cells"]) == len(_GRID.all_cells())
    for cell in data["cells"]:
        assert 0.0 <= cell["risk_score"] <= 1.0
        assert cell["tier"] in ("high", "medium", "low")
        assert -180.0 <= cell["longitude"] <= 180.0
        assert -90.0 <= cell["latitude"] <= 90.0
    assert data["complaint_events_used"] == 0

    # Second call reuses the trained model (no new active version).
    r2 = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r2.json()["model"]["version"] == data["model"]["version"]


@pytest.mark.asyncio
async def test_predictions_reflect_live_complaint(client: TestClient):
    citizen_id = await _citizen(_unique_email("hs-src"))
    await _insert_complaint(user_id=citizen_id, title="hs-live", category="GARBAGE")

    token = await _officer_token()
    r = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["complaint_events_used"] == 1
    hotspot = next(c for c in data["cells"] if c["cell_id"] == "r3c3")
    assert hotspot["trailing7"] >= 1
    assert hotspot["ward_code"] in ("W-001", "W-002", "W-003")
    assert data["population_cells"] >= 1
