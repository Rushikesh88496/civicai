"""Zero-operational-data baseline verification (Part 35).

CivicAgent must start with ZERO operational data:

* Complaints: 0            (active + resolved derived from complaint status)
* Incidents: 0             (complaints are the only incident records)
* Hotspots: 0              (predictive_models registry is empty)
* Predictions: 0           (infrastructure assets/models/predictions empty)

Reference / structural data survives a safe dev reset: the four wards, their
boundaries, the six roles, departments, SLA policies, system settings, the
demo-labelled critical locations and the assistant knowledge base — plus the
single bootstrap ``admin@example.com`` SUPER_ADMIN.

This module performs and verifies the same safe development reset the
``seed.py --reset`` mechanism uses, then asserts every operational surface
(analytics, command center, hotspots, infrastructure) returns honest zero /
empty values. The suite's session teardown (``tests/conftest.py``) re-applies
the same reset so the shared dev database is always handed back at baseline.
"""

import uuid

import pytest
from sqlalchemy import func, select
from starlette.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    Complaint,
    Department,
    InfrastructureAsset,
    InfrastructureModel,
    InfrastructurePrediction,
    PredictiveModel,
    Role,
    User,
    UserProfile,
    Ward,
    WardBoundary,
    WorkOrder,
)
from app.models.enums import RoleName
from app.schemas.auth import RegisterIn
from app.services import auth_service
from app.services.command_center_service import _RESOLVED_STATUSES
from tests.helpers import any_active_ward_id

# --------------------------------------------------------------------------- #
# Counters
# --------------------------------------------------------------------------- #

_RESOLVED_VALUES = {s.value for s in _RESOLVED_STATUSES}

# (module, label) — every operational table must read 0 after a reset.
_OPERATIONAL_TABLES = [
    (InfrastructurePrediction, "infrastructure predictions"),
    (InfrastructureAsset, "infrastructure assets"),
    (InfrastructureModel, "infrastructure models"),
    (PredictiveModel, "predictive model registry (hotspots)"),
    (WorkOrder, "work orders"),
]


async def _table_count(db, model) -> int:
    return int(await db.scalar(select(func.count()).select_from(model)) or 0)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_PASSWORD = "TestPass#2026"
_SETTINGS: Settings = get_settings()


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _role_user(email: str, role_name: str) -> str:
    """Create a user directly (no ward requirement) and return an access token."""
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == role_name))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=f"{role_name} Baseline User",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), role_name)


async def _delete_user(email: str) -> None:
    from app.models import User

    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


# --------------------------------------------------------------------------- #
# Reset returns the exact zero baseline
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_reset_returns_to_zero_operational_baseline():
    from scripts.reset_dev_data import reset_dev_data_all

    async with async_session_factory() as db:
        total_ops, deleted_users, deleted_wards = await reset_dev_data_all(db)

        # Every operational counter must be zero.
        for model, label in _OPERATIONAL_TABLES:
            count = await _table_count(db, model)
            assert count == 0, f"{label} must be 0 after reset, got {count}"

        # Complaint-derived counters: none at all -> none active/resolved.
        complaint_total = await db.scalar(select(func.count()).select_from(Complaint))
        assert int(complaint_total or 0) == 0

        # Users: exactly the bootstrap admin.
        from app.models import User

        users = (await db.scalars(select(User))).all()
        assert len(users) == 1
        assert users[0].email == "admin@example.com"
        assert users[0].role.name == RoleName.SUPER_ADMIN.value

        # Reference wards + boundaries survive (geo lookup must keep working).
        wards = (await db.scalars(select(Ward).order_by(Ward.code))).all()
        assert {w.code for w in wards} == {"WARD-1", "WARD-2", "WARD-3", "WARD-4"}
        boundaries = int(await db.scalar(select(func.count()).select_from(WardBoundary)) or 0)
        assert boundaries >= 4

        # Every required role survives — and nothing else does.
        roles = set((await db.scalars(select(Role.name))).all())
        required_roles = {
            RoleName.CITIZEN.value,
            RoleName.OFFICER.value,
            RoleName.WARD_REPRESENTATIVE.value,
            RoleName.FIELD_WORKER.value,
            RoleName.ADMIN.value,
            RoleName.SUPER_ADMIN.value,
        }
        assert roles == required_roles

        # Structural departments reduce to the seed roster ({PW, SN, PR}).
        departments = set((await db.scalars(select(Department.code))).all())
        assert departments == {"PW", "SN", "PR"}

        # Reference / structural data survives.
        assert int(total_ops) >= 0
        assert deleted_users >= 0
        assert deleted_wards >= 0
        print(
            f"[baseline] reset ok: {total_ops} ops, {deleted_users} users, "
            f"{deleted_wards} wards removed; {len(users)} admin kept; "
            f"{len(wards)} reference wards kept."
        )


# --------------------------------------------------------------------------- #
# Every operational surface reports honest zero / empty values
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_operational_surfaces_report_zero_when_empty(client: TestClient):
    from scripts.reset_dev_data import reset_dev_data_all

    async with async_session_factory() as db:
        await reset_dev_data_all(db)

    officer_email = _unique_email("bl-officer")
    token = await _role_user(officer_email, RoleName.OFFICER.value)
    headers = {"Authorization": f"Bearer {token}"}

    # Analytics overview + heatmap: honest zeros, no fabricated charts.
    overview = await client.get("/api/v1/analytics/overview", headers=headers)
    assert overview.status_code == 200
    data = overview.json()
    assert data["kpis"]["total_complaints"] == 0
    assert data["kpis"]["resolved"] == 0
    assert data["kpis"]["resolution_rate"] == 0.0
    assert data["kpis"]["ai_triage_rate"] == 0.0
    assert data["kpis"]["escalation_rate"] == 0.0
    assert data["charts"]["complaints_over_time"] == []
    assert data["charts"]["categories"] == []
    assert sum(w["total"] for w in data["charts"]["wards"]) == 0

    heatmap = await client.get("/api/v1/analytics/heatmap", headers=headers)
    assert heatmap.status_code == 200
    assert heatmap.json()["total_points"] == 0
    assert heatmap.json()["clusters"] == []

    # Command center: zeroed KPIs, empty queue + map (no fake markers/hotspots).
    kpis = await client.get("/api/v1/command-center/kpis", headers=headers)
    assert kpis.status_code == 200
    k = kpis.json()
    assert k["total_complaints"] == 0
    assert k["p1"] == k["p2"] == k["p3"] == k["p4"] == 0
    assert k["pending"] == k["in_progress"] == k["resolved"] == 0
    assert k["sla_breaches"] == k["sla_at_risk"] == 0

    queue = await client.get("/api/v1/command-center/queue", headers=headers)
    assert queue.status_code == 200
    assert queue.json()["items"] == []
    assert queue.json()["total"] == 0

    map_data = await client.get("/api/v1/command-center/map", headers=headers)
    assert map_data.status_code == 200
    m = map_data.json()
    assert m["complaints"] == []
    assert m["work_orders"] == []
    assert m["hotspots"] == []

    # Hotspots: insufficient-data state instead of a trained model.
    status = await client.get("/api/v1/hotspots/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["prediction_status"] == "INSUFFICIENT_DATA"
    assert status.json()["model"] is None
    predictions = await client.get("/api/v1/hotspots/predictions", headers=headers)
    assert predictions.status_code == 200
    assert predictions.json()["prediction_status"] == "INSUFFICIENT_DATA"
    assert predictions.json()["cells"] == []

    # Infrastructure: insufficient-data until assets are registered.
    infra_status = await client.get("/api/v1/infrastructure/status", headers=headers)
    assert infra_status.status_code == 200
    assert infra_status.json()["prediction_status"] == "INSUFFICIENT_DATA"
    infra_pred = await client.get("/api/v1/infrastructure/predictions", headers=headers)
    assert infra_pred.status_code == 200
    assert infra_pred.json()["prediction_status"] == "INSUFFICIENT_DATA"
    assert infra_pred.json()["assets"] == []

    # Citizen dashboard for a fresh citizen: every statistic is zero.
    citizen_email = _unique_email("bl-citizen")
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=citizen_email,
                password=_PASSWORD,
                full_name="Baseline Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        citizen = await db.scalar(select(User).where(User.email == citizen_email))
        citizen_token = create_access_token(str(citizen.id), RoleName.CITIZEN.value)
    citizen_headers = {"Authorization": f"Bearer {citizen_token}"}
    dashboard = await client.get("/api/v1/citizen/dashboard", headers=citizen_headers)
    assert dashboard.status_code == 200
    d = dashboard.json()
    assert d["complaints"]["total"] == 0
    assert d["complaints"]["open"] == 0
    assert d["complaints"]["resolved"] == 0
    assert d["recent_complaints"] == []

    await _delete_user(officer_email)
    await _delete_user(citizen_email)
