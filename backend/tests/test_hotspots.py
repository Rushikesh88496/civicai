"""Tests for Predictive Civic Hotspots (Part 23 + Part 36 real-data training).

Part 36 hard requirements exercised here:

* Hotspots are trained and predicted **only from real complaint records** stored
  in the database (coordinates from user GPS or explicit manual map selection);
  there is no synthetic / random / hardcoded / demo corpus anymore.
* **No lazy provisioning** — simply opening the hotspot page never trains a
  model or creates a prediction. With real history present but no model trained,
  ``GET /predictions`` returns ``READY`` with ``model=None`` and zero cells and
  the ``predictive_models`` registry stays empty.
* Hotspot geographic positions are **calculated from the actual complaint
  coordinates** (crowd centroid per cell), never from fabricated positions.
* Too-compressed history is refused with ``INSUFFICIENT_DATA`` (span must cover
  the feature warm-up plus the label horizon).
* Thin/empty history stays gated as ``INSUFFICIENT_DATA`` (Part 31).

Also covered: grid geometry, feature leak-freedom, provider degradation, RBAC,
registry versioning and live-prediction shape.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.ml.corpus import corpus_from_events
from app.ml.external import LiveContextProvider
from app.ml.features import build_feature_frame
from app.ml.grid import HotspotGrid
from app.models import (
    Complaint,
    ComplaintLocation,
    PredictiveModel,
    Role,
    User,
    UserProfile,
    Ward,
)
from app.models.enums import ComplaintCategory, RoleName
from app.schemas.auth import RegisterIn
from app.services import auth_service
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/hotspots"
_SETTINGS = get_settings()
_LAT = 17.4327
_LON = 78.3885
_GRID = HotspotGrid(17.40, 78.35, 17.50, 78.49, _SETTINGS.HOTSPOT_CELL_DEG)

_HOTSPOT_CELLS = ("r3c3", "r3c4", "r4c3")
_SCATTER_CELLS = (
    "r0c0",
    "r0c14",
    "r2c7",
    "r5c1",
    "r6c10",
    "r8c5",
    "r9c12",
    "r11c2",
    "r12c8",
    "r13c11",
    "r14c3",
    "r7c6",
)
_CATEGORIES = ("GARBAGE", "ROAD", "WATER", "SANITATION")


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _offset(lat: float, lon: float) -> tuple[float, float]:
    """A reproducible real coordinate inside the same grid cell as the centroid."""
    return round(lat + 0.002, 6), round(lon - 0.002, 6)


async def _citizen(email: str) -> uuid.UUID:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="HS Citizen",
                ward_id=await any_active_ward_id(db),
            ),
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
    source: str = "gps",
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
            ComplaintLocation(complaint_id=complaint.id, latitude=lat, longitude=lon, source=source)
        )
        await db.commit()
        return complaint.id


async def _seed_real_history(
    citizen_id: uuid.UUID,
    *,
    span_days: int = 150,
) -> dict[str, tuple[float, float]]:
    """Insert REAL complaint records spread across ``span_days``.

    ``_HOTSPOT_CELLS`` receive a regular stream of complaints (a real hotspot
    persisted over time), ``_SCATTER_CELLS`` receive one-off reports. Every
    coordinate is an explicit GPS/manual-map value, so the expected per-cell
    crowd centroid is exactly the offset coordinate.

    Returns {cell_id: (lat, lon)} for the cells with recurring complaints.
    """
    now = datetime.now(UTC)
    coords_by_cell: dict[str, tuple[float, float]] = {}

    idx = 0
    for day in range(span_days):
        if day % 2 != 0:
            continue
        cell = _HOTSPOT_CELLS[(day // 2) % len(_HOTSPOT_CELLS)]
        if cell not in coords_by_cell:
            clat, clon = _GRID.cell_centroid(cell)
            coords_by_cell[cell] = _offset(clat, clon)
        lat, lon = coords_by_cell[cell]
        await _insert_complaint(
            user_id=citizen_id,
            title=f"hs-hot-{idx}",
            category=_CATEGORIES[idx % len(_CATEGORIES)],
            lat=lat,
            lon=lon,
            created_at=now - timedelta(days=span_days - 1 - day),
        )
        idx += 1

    for k, cell in enumerate(_SCATTER_CELLS):
        clat, clon = _GRID.cell_centroid(cell)
        lat, lon = _offset(clat, clon)
        await _insert_complaint(
            user_id=citizen_id,
            title=f"hs-scatter-{k}",
            category=_CATEGORIES[k % len(_CATEGORIES)],
            lat=lat,
            lon=lon,
            created_at=now - timedelta(days=span_days - 40 - k * 7),
        )

    return coords_by_cell


async def _trained_system(client: TestClient) -> tuple[str, dict[str, tuple[float, float]]]:
    """Seed real history, run the explicit training action, return officer token."""
    citizen_id = await _citizen(_unique_email("hs-train"))
    coords = await _seed_real_history(citizen_id)
    token = await _officer_token()
    r = await client.post(f"{_BASE}/train", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["trained"] is True
    return token, coords


@pytest.fixture(autouse=True)
async def _fast_settings(tmp_path, monkeypatch):
    """Small, fast training config + isolated artifact directory."""
    for attr, value in (
        ("HOTSPOT_TRAIN_LOOKBACK_DAYS", 400),
        ("HOTSPOT_SNAPSHOT_EVERY_DAYS", 7),
        ("HOTSPOT_TEST_FINAL_DAYS", 15),
        ("HOTSPOT_CV_FOLDS", 1),
        ("HOTSPOT_N_ESTIMATORS", 30),
        ("HOTSPOT_ARTIFACT_DIR", str(tmp_path)),
    ):
        monkeypatch.setattr(_SETTINGS, attr, value)
    yield


@pytest.fixture(autouse=True)
def _low_gating_thresholds(monkeypatch):
    """Part 31 gating minima of 1/1 keep the behaviour tests cheap.

    Seeding 25+ spread complaints for every hotspot behaviour test would dominate
    the suite; lowering the thresholds to 1/1 exercises the full ready-path with
    modest real history. The dedicated gating test re-raises them via the same
    fixture override logic.
    """
    monkeypatch.setattr(_SETTINGS, "MINIMUM_TRAINING_RECORDS", 1)
    monkeypatch.setattr(_SETTINGS, "MINIMUM_AREA_TIME_OBSERVATIONS", 1)
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
    snapshots = [datetime(2026, 1, 1, 0, 0, tzinfo=UTC) + timedelta(days=d) for d in (0, 1, 2, 5)]
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
# Corpus is a real-data container (Part 36: no synthetic generator).
# --------------------------------------------------------------------------- #
def test_corpus_from_events_is_real_data_container():
    evs = [_event(1, "r0c0"), _event(0, "r0c0")]
    corpus = corpus_from_events(evs)
    assert corpus.events[0].ts < corpus.events[1].ts
    assert corpus.events == sorted(evs, key=lambda e: e.ts)
    assert corpus.cells == {} and corpus.rain_mm == {}


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
    rep_token = await _role_user(_unique_email("hs-rep"), RoleName.WARD_REPRESENTATIVE.value)
    worker_token = await _role_user(_unique_email("hs-worker"), RoleName.FIELD_WORKER.value)

    # Citizen + field worker are denied every hotspot surface.
    for token in (citizen_token, worker_token):
        for method, path in (
            ("GET", "/status"),
            ("GET", "/predictions"),
            ("POST", "/train"),
        ):
            rec = await client.request(method, f"{_BASE}{path}", headers=_auth(token))
            assert rec.status_code == 403

    # A ward representative may READ status + predictions, but never retrain.
    for method, path in (("GET", "/status"), ("GET", "/predictions")):
        rec = await client.request(method, f"{_BASE}{path}", headers=_auth(rep_token))
        assert rec.status_code == 200

    rec = await client.post(f"{_BASE}/train", headers=_auth(rep_token))
    assert rec.status_code == 403

    r = await client.get(f"{_BASE}/status")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_ward_rep_predictions_scoped_to_own_ward(client: TestClient):
    """A representative only ever sees the risk cells inside their own ward.

    The trained model is city-wide (real complaints), but GET /predictions for a
    WARD_REPRESENTATIVE must filter every returned cell to their assigned ward.
    Another representative of a ward with no cells gets an empty (non-leaking)
    forecast.
    """
    token, _coords = await _trained_system(client)

    async with async_session_factory() as db:
        ward_id = await any_active_ward_id(db)
        ward = await db.get(Ward, ward_id)
        assert ward is not None
        ward_code = ward.code

    covering_rep = await _role_user(
        _unique_email("hs-rep-cover"),
        RoleName.WARD_REPRESENTATIVE.value,
        ward_id=ward_id,
    )

    st = await client.get(f"{_BASE}/status", headers=_auth(covering_rep))
    assert st.status_code == 200
    assert st.json()["trained"] is True

    pred = await client.get(f"{_BASE}/predictions", headers=_auth(covering_rep))
    assert pred.status_code == 200, pred.text
    data = pred.json()
    assert data["prediction_status"] == "READY"
    assert data["cells"] != []
    for cell in data["cells"]:
        assert cell["ward_code"] == ward_code, cell

    # A representative bound to a ward the grid does not cover sees zero cells.
    async with async_session_factory() as db:
        empty_ward = Ward(
            code=f"HSE-{uuid.uuid4().hex[:6]}",
            name=f"Empty-{uuid.uuid4().hex[:6]}",
            description="no cells over this ward",
        )
        db.add(empty_ward)
        await db.commit()
        empty_ward_id = empty_ward.id

    empty_rep = await _role_user(
        _unique_email("hs-rep-empty"),
        RoleName.WARD_REPRESENTATIVE.value,
        ward_id=empty_ward_id,
    )
    pred2 = await client.get(f"{_BASE}/predictions", headers=_auth(empty_rep))
    assert pred2.status_code == 200, pred2.text
    assert pred2.json()["cells"] == []


# --------------------------------------------------------------------------- #
# Gating / no lazy provisioning (Part 31 + Part 36)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_predictions_no_lazy_train_when_gated(client: TestClient, monkeypatch):
    # Default (high) Part 31 thresholds with zero complaints → INSUFFICIENT_DATA
    # everywhere and NO model is provisioned (the platform stays genuinely empty).
    for attr, value in (
        ("MINIMUM_TRAINING_RECORDS", 1000),
        ("MINIMUM_AREA_TIME_OBSERVATIONS", 1000),
    ):
        monkeypatch.setattr(_SETTINGS, attr, value)
    await _clear_models()
    token = await _officer_token()

    r = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["prediction_status"] == "INSUFFICIENT_DATA"
    assert data["model"] is None
    assert data["cells"] == []
    assert data["records_available"] == 0
    assert data["complaint_events_used"] == 0
    assert "minimum" in data["message"]

    st = await client.get(f"{_BASE}/status", headers=_auth(token))
    assert st.json()["trained"] is False
    assert st.json()["prediction_status"] == "INSUFFICIENT_DATA"

    tr = await client.post(f"{_BASE}/train", headers=_auth(token))
    assert tr.json()["trained"] is False
    assert tr.json()["status"] == "INSUFFICIENT_DATA"

    async with async_session_factory() as db:
        rows = (await db.execute(select(PredictiveModel))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_predictions_without_trained_model_stay_empty(client: TestClient):
    # Real history clears the gate, but NO model exists: opening the hotspot
    # page must NOT create a model or any forecast (no lazy provisioning).
    await _clear_models()
    citizen_id = await _citizen(_unique_email("hs-notrained"))
    await _seed_real_history(citizen_id)
    token = await _officer_token()

    r = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["prediction_status"] == "READY"
    assert data["ai_prediction"] is True
    assert data["model"] is None
    assert data["cells"] == []
    assert "trained" in data["message"].lower() or "officer" in data["message"].lower()
    assert data["complaint_events_used"] == 0

    # Repeated page loads still never provision anything.
    r2 = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r2.json()["model"] is None
    async with async_session_factory() as db:
        rows = (await db.execute(select(PredictiveModel))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_train_refuses_compressed_history(client: TestClient):
    # A burst confined to a few days is not a training time series (warm-up +
    # horizon must fit inside the real history span).
    citizen_id = await _citizen(_unique_email("hs-compact"))
    for m in range(4):
        lat, lon = _offset(*_GRID.cell_centroid(_HOTSPOT_CELLS[m % len(_HOTSPOT_CELLS)]))
        await _insert_complaint(
            user_id=citizen_id,
            title=f"hs-compact-{m}",
            lat=lat,
            lon=lon,
            created_at=datetime.now(UTC) - timedelta(days=4 - m),
        )
    token = await _officer_token()

    tr = await client.post(f"{_BASE}/train", headers=_auth(token))
    assert tr.status_code == 200
    assert tr.json()["trained"] is False
    assert tr.json()["status"] == "INSUFFICIENT_DATA"
    assert "span" in tr.json()["message"].lower()

    pred = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert pred.json()["cells"] == []


# --------------------------------------------------------------------------- #
# Training uses ONLY real complaint locations (Part 36)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_train_persists_artifact_and_version_bumps(client: TestClient):
    citizen_id = await _citizen(_unique_email("hs-train"))
    coords = await _seed_real_history(citizen_id)
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

    # The bundle provenance must prove real-data training:
    assert data["config"]["training_source"] == "real_complaints"
    assert "no synthetic" in data["config"]["training_description"].lower()
    assert "database" in data["config"]["training_description"].lower()
    assert "corpus_years" not in data["config"]
    assert "corpus_seed" not in data["config"]
    assert data["config"]["training_lookback_days"] == 400

    async with async_session_factory() as db:
        row = await db.scalar(select(PredictiveModel).where(PredictiveModel.is_active.is_(True)))
        assert row is not None and row.version == 1 and row.artifact_filename.endswith(".joblib")
        stored = row.config or {}
    assert stored.get("training_source") == "real_complaints"

    # Status reflects the active model + evaluation metrics.
    r = await client.get(f"{_BASE}/status", headers=headers)
    assert r.status_code == 200
    st = r.json()
    assert st["trained"] is True
    assert st["model"]["version"] == 1
    assert st["model"]["metrics"]["clf"]["roc_auc"] is not None
    assert st["model"]["config"]["training_source"] == "real_complaints"

    # Retrain bumps the version and swaps active.
    r = await client.post(f"{_BASE}/train", headers=headers)
    assert r.json()["version"] == 2
    r = await client.get(f"{_BASE}/status", headers=headers)
    assert r.json()["model"]["version"] == 2
    async with async_session_factory() as db:
        old = await db.scalar(select(PredictiveModel).where(PredictiveModel.version == 1))
        assert old is not None and old.is_active is False

    # Hotspot positions in live forecasts are the crowd centroids of the REAL
    # complaint coordinates for the window the model was trained on windows of.
    r = await client.get(f"{_BASE}/predictions", headers=headers)
    assert r.status_code == 200
    pred = r.json()
    assert pred["prediction_status"] == "READY"
    hotspot = next(c for c in pred["cells"] if c["cell_id"] == "r3c3")
    expected_lat, expected_lon = coords["r3c3"]
    assert abs(hotspot["latitude"] - expected_lat) < 0.0005
    assert abs(hotspot["longitude"] - expected_lon) < 0.0005
    # And the crowd centroid is NOT the fabricated grid centroid.
    grid_lat, grid_lon = _GRID.cell_centroid("r3c3")
    assert abs(hotspot["latitude"] - grid_lat) > 0.001


# --------------------------------------------------------------------------- #
# Live prediction shape
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_predictions_shape(client: TestClient):
    token, _coords = await _trained_system(client)
    r = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["ai_prediction"] is True
    assert "not a confirmed incident" in data["disclaimer"].lower()
    assert data["horizon_days"] == 7
    assert data["model"]["version"] >= 1
    assert data["complaint_events_used"] >= 1
    assert len(data["cells"]) >= 1
    for cell in data["cells"]:
        assert 0.0 <= cell["risk_score"] <= 1.0
        assert cell["tier"] in ("high", "medium", "low")
        assert -180.0 <= cell["longitude"] <= 180.0
        assert -90.0 <= cell["latitude"] <= 90.0

    # Second call reuses the trained model (no new active version).
    r2 = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r2.json()["model"]["version"] == data["model"]["version"]


@pytest.mark.asyncio
async def test_predictions_reflect_live_complaint(client: TestClient):
    token, coords = await _trained_system(client)
    r = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["complaint_events_used"] >= 1
    hotspot = next(c for c in data["cells"] if c["cell_id"] == "r3c3")
    assert hotspot["trailing7"] >= 1
    assert hotspot["latitude"] == coords["r3c3"][0]
    assert hotspot["ward_code"] == "WARD-1"
    assert data["population_cells"] >= 1
