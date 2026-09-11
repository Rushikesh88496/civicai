"""Tests for Predictive Infrastructure Maintenance (Part 24).

Layers exercised:

* **Corpus determinism** — the same seed reproduces identical asset tables.
* **Risk helpers** — threshold → risk_level mapping and the recommended-inspection
  / supporting-factors wording (always "predicted risk", never "will fail").
* **Missing data** — an asset without install date / coordinates still predicts
  (low signal), with unavailability honestly flagged in supporting factors.
* **Normal infrastructure** — a young, quiet asset lands in LOW risk.
* **High-risk infrastructure** — an old, heavily-complained-about asset lands in
  HIGH/CRITICAL with a meaningful failure_probability.
* **Prediction pipeline** — lazy training, stable model version across calls,
  every response carries the ai_prediction flag + disclaimer.
* **RBAC** — city roles (officer / admin) may train/read while citizens,
  ward-reps and field workers are rejected.
* **Regression** — retraining bumps the version and deactivates the old model.
* **Review workflow** — officer review (APPROVE / REJECT) and the optional
  preventive work order (only on approved predictions).
* **Part 31 gating** — forecasts/training/status refuse to serve until the
  registered-asset fleet clears ``INFRA_MIN_ASSETS``; a pinned test covers the
  gated responses. Behaviour tests set the minimum to 0 so they stay cheap.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.ml.infra_corpus import build_infra_corpus
from app.ml.infra_features import (
    feature_columns,
    recommend_action_text,
    recommendation_for,
    risk_level_for_probability,
    supporting_factors_for,
)
from app.models import (
    Complaint,
    ComplaintLocation,
    InfrastructureAsset,
    InfrastructureModel,
    InfrastructurePrediction,
    PreventiveWorkOrder,
    Role,
    User,
    UserProfile,
)
from app.models.enums import ComplaintCategory, InfrastructureRiskLevel, RoleName
from app.schemas.auth import RegisterIn
from app.services import auth_service
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/infrastructure"
_SETTINGS = get_settings()
_ASSET_LAT = 17.4330
_ASSET_LON = 78.3880


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _citizen(email: str) -> uuid.UUID:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Infra Citizen",
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
    category: str = "ROAD",
    lat: float = _ASSET_LAT,
    lon: float = _ASSET_LON,
    days_ago: int = 5,
) -> uuid.UUID:
    async with async_session_factory() as db:
        created = datetime.now(UTC) - timedelta(days=days_ago)
        complaint = Complaint(
            user_id=user_id,
            category=ComplaintCategory(category),
            title=f"infra-test {uuid.uuid4().hex[:8]}",
            description="desc",
            created_at=created,
        )
        db.add(complaint)
        await db.flush()
        db.add(
            ComplaintLocation(complaint_id=complaint.id, latitude=lat, longitude=lon, source="gps")
        )
        await db.commit()
        return complaint.id


async def _register_asset(client: TestClient, token: str, payload: dict) -> dict:
    res = await client.post(f"{_BASE}/assets", json=payload, headers=_auth(token))
    assert res.status_code == 201
    return res.json()


@pytest.fixture(autouse=True)
async def _fast_settings(tmp_path, monkeypatch):
    """Small, fast training config + isolated artifact directory."""
    for attr, value in (
        ("INFRA_CORPUS_YEARS", 1),
        ("INFRA_SNAPSHOT_EVERY_DAYS", 14),
        ("INFRA_CORPUS_ASSETS", 60),
        ("INFRA_TEST_FINAL_DAYS", 120),
        ("INFRA_CV_FOLDS", 1),
        ("INFRA_N_ESTIMATORS", 80),
        ("INFRA_ARTIFACT_DIR", str(tmp_path)),
        # Part 31 gating: behaviour tests are about the pipeline, not the fleet
        # gate, so the minimum asset fleet is lowered to zero here.
        ("INFRA_MIN_ASSETS", 0),
    ):
        monkeypatch.setattr(_SETTINGS, attr, value)
    yield


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    async with async_session_factory() as db:
        await db.execute(delete(PreventiveWorkOrder))
        await db.execute(delete(InfrastructurePrediction))
        await db.execute(delete(InfrastructureModel))
        await db.execute(delete(InfrastructureAsset))
        await db.execute(delete(ComplaintLocation))
        await db.execute(delete(Complaint))
        await db.execute(delete(User).where(User.email.like("%-%@example.com")))
        await db.commit()


async def _officer_token() -> str:
    return await _role_user(_unique_email("infra-officer"), RoleName.OFFICER.value)


async def _clear_models() -> None:
    async with async_session_factory() as db:
        await db.execute(delete(InfrastructureModel))
        await db.commit()


# --------------------------------------------------------------------------- #
# Corpus determinism + feature contract
# --------------------------------------------------------------------------- #
def test_corpus_is_deterministic():
    a = build_infra_corpus(_SETTINGS)
    b = build_infra_corpus(_SETTINGS)
    assert len(a) == len(b)
    assert a["y_fail"].equals(b["y_fail"])
    assert a["y_fail"].isin([0, 1]).all()
    assert "age_years" in feature_columns()
    assert any(c.startswith("cat_") for c in feature_columns())


# --------------------------------------------------------------------------- #
# Risk helpers
# --------------------------------------------------------------------------- #
def test_risk_level_thresholds_map_probabilities():
    assert risk_level_for_probability(0.10, _SETTINGS) is InfrastructureRiskLevel.LOW
    assert risk_level_for_probability(0.35, _SETTINGS) is InfrastructureRiskLevel.MEDIUM
    assert risk_level_for_probability(0.60, _SETTINGS) is InfrastructureRiskLevel.HIGH
    assert risk_level_for_probability(0.90, _SETTINGS) is InfrastructureRiskLevel.CRITICAL


def test_recommendation_wording_never_claims_failure():
    for level in InfrastructureRiskLevel:
        text = recommendation_for(level, "WATER_MAIN")
        assert "inspection" in text.lower()
        assert "will fail" not in text.lower()
        action = recommend_action_text(level, "WATER_MAIN")
        assert "inspection" in action.lower()


def test_supporting_factors_flag_missing_data():
    factors = supporting_factors_for(
        category="ROAD",
        age=0.0,
        age_available=False,
        complaints_90d=0,
        repairs_12m=0,
        rainfall_mm=None,
        ward_label=None,
        location_available=False,
    )
    assert len(factors) >= 2
    assert any("unavailable" in f.lower() for f in factors)
    assert any("treated as" in f.lower() for f in factors)


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rbac_forbids_non_city_roles(client: TestClient):
    citizen_id = await _citizen(_unique_email("infra-cit"))
    citizen_token = create_access_token(str(citizen_id), "CITIZEN")
    rep_token = await _role_user(_unique_email("infra-rep"), RoleName.WARD_REPRESENTATIVE.value)
    worker_token = await _role_user(_unique_email("infra-worker"), RoleName.FIELD_WORKER.value)

    for token in (citizen_token, rep_token, worker_token):
        for method, path in (
            ("GET", "/status"),
            ("GET", "/predictions"),
            ("POST", "/train"),
            ("GET", "/assets"),
        ):
            rec = await client.request(method, f"{_BASE}{path}", headers=_auth(token))
            assert rec.status_code == 403

    r = await client.get(f"{_BASE}/status")
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------- #
# Training + registry versioning
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_gating_refuses_serving_without_fleet(client: TestClient, monkeypatch):
    # Defaults are lowered to 0 by the fixture; re-raise to pin the gate.
    monkeypatch.setattr(_SETTINGS, "INFRA_MIN_ASSETS", 1000)
    token = await _officer_token()
    headers = _auth(token)

    r = await client.get(f"{_BASE}/predictions", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["prediction_status"] == "INSUFFICIENT_DATA"
    assert data["model"] is None and data["assets"] == []
    assert data["registered_assets"] == 0
    assert data["message"] and "assets" in data["message"]

    st = await client.get(f"{_BASE}/status", headers=headers)
    assert st.json()["trained"] is False
    assert st.json()["prediction_status"] == "INSUFFICIENT_DATA"

    tr = await client.post(f"{_BASE}/train", headers=headers)
    assert tr.json()["trained"] is False
    assert tr.json()["status"] == "INSUFFICIENT_DATA"

    async with async_session_factory() as db:
        rows = (await db.execute(select(InfrastructureModel))).scalars().all()
    assert rows == []


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
    assert data["metrics"]["clf"]["f1"] is not None
    assert data["metrics"]["baseline"]["f1"] is not None

    async with async_session_factory() as db:
        row = await db.scalar(
            select(InfrastructureModel).where(InfrastructureModel.is_active.is_(True))
        )
        assert row is not None and row.version == 1 and row.artifact_filename.endswith(".joblib")

    r = await client.get(f"{_BASE}/status", headers=headers)
    assert r.json()["trained"] is True and r.json()["model"]["version"] == 1

    r = await client.post(f"{_BASE}/train", headers=headers)
    assert r.json()["version"] == 2
    async with async_session_factory() as db:
        old = await db.scalar(select(InfrastructureModel).where(InfrastructureModel.version == 1))
        assert old is not None and old.is_active is False


# --------------------------------------------------------------------------- #
# Missing data
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_missing_data_still_predicts_and_flags_unavailability(client: TestClient):
    token = await _officer_token()
    asset = await _register_asset(
        client,
        token,
        {
            "name": "Unregistered Age Road",
            "category": "ROAD",
            "latitude": None,
            "longitude": None,
            "condition_note": "No install date on record.",
        },
    )

    r = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["ai_prediction"] is True
    assert data["assets_assessed"] == 1
    entry = data["assets"][0]
    assert entry["asset"]["id"] == asset["id"]
    assert 0.0 <= entry["failure_probability"] <= 1.0
    assert entry["risk_level"] in {lv.value for lv in InfrastructureRiskLevel}
    assert any("unavailable" in f.lower() for f in entry["supporting_factors"])


# --------------------------------------------------------------------------- #
# Normal infrastructure -> LOW
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_normal_quiet_asset_is_low_risk(client: TestClient):
    token = await _officer_token()
    await _register_asset(
        client,
        token,
        {
            "name": "New Corner Park",
            "category": "PARK",
            "latitude": _ASSET_LAT,
            "longitude": _ASSET_LON,
            "installed_at": "2020-07-01",
        },
    )
    r = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r.status_code == 200
    entry = r.json()["assets"][0]
    assert entry["risk_level"] == InfrastructureRiskLevel.LOW.value
    assert entry["failure_probability"] < _SETTINGS.INFRA_RISK_MEDIUM
    assert "inspection" in entry["recommended_inspection"].lower()


# --------------------------------------------------------------------------- #
# High-risk infrastructure -> HIGH/CRITICAL
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_high_risk_old_asset_with_many_complaints(client: TestClient):
    token = await _officer_token()
    citizen_id = await _citizen(_unique_email("infra-high-cit"))
    asset = await _register_asset(
        client,
        token,
        {
            "name": "Old Riverside Water Main",
            "category": "WATER_MAIN",
            "latitude": _ASSET_LAT,
            "longitude": _ASSET_LON,
            "installed_at": "1990-07-01",
        },
    )
    for _ in range(12):
        await _insert_complaint(user_id=citizen_id)

    r = await client.get(f"{_BASE}/predictions", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    entry = next(a for a in data["assets"] if a["asset"]["id"] == asset["id"])
    assert entry["risk_level"] in (
        InfrastructureRiskLevel.HIGH.value,
        InfrastructureRiskLevel.CRITICAL.value,
    )
    assert entry["failure_probability"] >= _SETTINGS.INFRA_RISK_HIGH
    assert entry["history"]["complaints_90d"] == 12
    assert any("complaint" in f.lower() for f in entry["supporting_factors"])


# --------------------------------------------------------------------------- #
# Prediction pipeline shape + stability
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_predictions_lazy_train_and_reuse_version(client: TestClient):
    await _clear_models()
    token = await _officer_token()
    headers = _auth(token)

    r = await client.get(f"{_BASE}/predictions", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["ai_prediction"] is True
    assert "forecast" in data["disclaimer"].lower() or "prediction" in data["disclaimer"].lower()
    assert data["model"]["version"] >= 1
    assert data["assets"] == [] or data["assets_assessed"] == len(data["assets"])

    r2 = await client.get(f"{_BASE}/predictions", headers=headers)
    assert r2.json()["model"]["version"] == data["model"]["version"]

    async with async_session_factory() as db:
        n = await db.scalar(select(func.count(InfrastructurePrediction.id)))
        assert n == 0  # no assets, no stored predictions


# --------------------------------------------------------------------------- #
# Review workflow + preventive work order
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_review_and_preventive_work_order_flow(client: TestClient):
    token = await _officer_token()
    headers = _auth(token)
    await _register_asset(
        client,
        token,
        {"name": "Reviewed Main", "category": "WATER_MAIN", "installed_at": "1985-07-01"},
    )

    data = (await client.get(f"{_BASE}/predictions", headers=headers)).json()
    prediction_id = data["assets"][0]["id"]

    r = await client.post(
        f"{_BASE}/predictions/{prediction_id}/review",
        json={"decision": "APPROVED", "note": "proceed"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["review_status"] == "APPROVED"

    wo = await client.post(
        f"{_BASE}/predictions/{prediction_id}/work-orders",
        json={"department": "WATER", "recommended_action": "Pressure test the main."},
        headers=headers,
    )
    assert wo.status_code == 201
    out = wo.json()
    assert out["status"] == "PENDING_APPROVAL"
    assert out["department"] == "WATER"
    assert out["asset"]["name"] == "Reviewed Main"

    # Second prediction (fresh run) -> reject invalid decision.
    data2 = (await client.get(f"{_BASE}/predictions", headers=headers)).json()
    pred2 = data2["assets"][0]["id"]
    bad = await client.post(
        f"{_BASE}/predictions/{pred2}/review", json={"decision": "MAYBE"}, headers=headers
    )
    assert bad.status_code == 422

    # A REJECTED prediction cannot raise a preventive work order.
    rej = await client.post(
        f"{_BASE}/predictions/{pred2}/review",
        json={"decision": "REJECTED", "note": "no action"},
        headers=headers,
    )
    assert rej.status_code == 200
    denied = await client.post(
        f"{_BASE}/predictions/{pred2}/work-orders", json={"department": "WATER"}, headers=headers
    )
    assert denied.status_code == 400
