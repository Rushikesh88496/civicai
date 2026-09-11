"""Tests for the Department Routing Agent (Part 13).

Two layers:

* **Pure engine** — ``app.services.routing_engine.route_complaint`` maps every
  routable ``ComplaintCategory`` onto the correct department deterministically,
  folds multi-department rules (Flooding → Drainage + Roads; fallen electrical
  infrastructure → Electrical + Emergency), flags unknown categories as
  ambiguous and keeps confidence bounded.
* **Agent + service + API** — ``RoutingAgent`` runs against the live (dev) DB,
  persists a ``RoutingOutput`` to ``agent_runs`` (``agent="routing"``) and appends
  a ``complaint_department_history`` row; re-running detects a primary-department
  change. The officer override endpoint is RBAC-gated (OFFICER/ADMIN/WARD_REP
  allowed, CITIZEN denied) and records old / new department + reason + user +
  timestamp. The public detail endpoint surfaces the effective department.
"""

import uuid

import pytest
from sqlalchemy import select

from app.agents.routing_agent import RoutingAgent
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    ComplaintDepartmentHistory,
    Role,
    User,
    UserProfile,
)
from app.models.enums import ComplaintCategory, RoleName
from app.schemas.auth import RegisterIn
from app.services import auth_service
from app.services.routing_engine import route_complaint
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"
_SETTINGS = get_settings()
_SEED_LAT = 17.4327
_SEED_LON = 78.3885


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Routing Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _officer_token(email: str) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Routing Officer",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
    return create_access_token(str(user.id), RoleName.OFFICER.value)


async def _create_complaint(client, token: str, *, desc: str, category: str) -> str:
    body = {
        "description": desc,
        "category": category,
        "media_ids": [],
        "location": {
            "latitude": _SEED_LAT,
            "longitude": _SEED_LON,
            "address": "Routing test location",
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
# Pure engine: each category routes to the correct primary department
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "category,primary",
    [
        ("WATER", "WATER"),
        ("WATER_LEAK", "WATER"),
        ("ROAD", "ROADS"),
        ("ELECTRICITY", "ELECTRICAL"),
        ("STREET_LIGHTING", "ELECTRICAL"),
        ("GARBAGE", "WASTE"),
        ("SANITATION", "WASTE"),
        ("DRAINAGE", "DRAINAGE"),
        ("PARKS", "PARKS"),
        ("FALLEN_TREE", "PARKS"),
        ("PUBLIC_SAFETY", "EMERGENCY_DISASTER"),
    ],
)
def test_each_category_routes_to_correct_department(category, primary):
    decision = route_complaint(ComplaintCategory(category), settings=_SETTINGS)
    assert decision.primary_department.value == primary
    assert decision.secondary_departments == []
    assert decision.ambiguous is False
    assert decision.confidence >= _SETTINGS.ROUTING_CONFIDENCE_KNOWN
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.routing_reason  # always explainable


# --------------------------------------------------------------------------- #
# Pure engine: unknown category is ambiguous with low confidence
# --------------------------------------------------------------------------- #
def test_unknown_category_flags_ambiguous():
    decision = route_complaint(ComplaintCategory.OTHER, settings=_SETTINGS)
    assert decision.ambiguous is True
    assert decision.confidence == pytest.approx(_SETTINGS.ROUTING_CONFIDENCE_UNKNOWN)
    assert "ambig" in decision.routing_reason.lower()


# --------------------------------------------------------------------------- #
# Pure engine: multi-department
# --------------------------------------------------------------------------- #
def test_flooding_routes_to_drainage_plus_roads():
    decision = route_complaint(
        ComplaintCategory.FLOODING,
        description="Market road flooded after heavy rain.",
        settings=_SETTINGS,
    )
    assert decision.primary_department.value == "DRAINAGE"
    assert "ROADS" in decision.secondary_values
    assert decision.confidence == pytest.approx(_SETTINGS.ROUTING_CONFIDENCE_MULTI)


def test_fallen_electrical_routes_to_electrical_plus_emergency():
    decision = route_complaint(
        ComplaintCategory.ELECTRICITY,
        description="Fallen power pole with exposed live wires on the street.",
        settings=_SETTINGS,
    )
    assert decision.primary_department.value == "ELECTRICAL"
    assert "EMERGENCY_DISASTER" in decision.secondary_values


def test_electricity_without_fallen_hint_is_single_department():
    decision = route_complaint(
        ComplaintCategory.ELECTRICITY,
        description="Street lights not working in our block.",
        settings=_SETTINGS,
    )
    assert decision.primary_department.value == "ELECTRICAL"
    assert decision.secondary_departments == []


def test_priority_boost_raises_confidence_within_bounds():
    low = route_complaint(ComplaintCategory.ROAD, settings=_SETTINGS)
    from app.services.routing_engine import RoutingSignals

    boosted = route_complaint(
        ComplaintCategory.ROAD,
        signals=RoutingSignals(priority_bucket="P1_CRITICAL", triage_severity="CRITICAL"),
        settings=_SETTINGS,
    )
    assert boosted.confidence > low.confidence
    assert boosted.confidence <= 1.0


# --------------------------------------------------------------------------- #
# Agent-level integration (live DB)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_routing_persists_output_and_history(client):
    email = _unique_email("rout-run")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(
        client, token, desc="Water leak near the market.", category="WATER"
    )

    async with async_session_factory() as db:
        run = await RoutingAgent(settings=_SETTINGS).run(db, complaint_id=uuid.UUID(complaint_id))

    assert run.agent == "routing"
    assert run.status.value == "SUCCEEDED"
    result = run.structured_result
    assert result is not None
    assert result["primary_department"] == "WATER"
    assert result["confidence"] > 0
    assert result["routing_reason"]
    assert result["inputs"]["category"] == "WATER"

    async with async_session_factory() as db:
        hist = (
            (
                await db.execute(
                    select(ComplaintDepartmentHistory).where(
                        ComplaintDepartmentHistory.complaint_id == uuid.UUID(complaint_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(hist) == 1
    assert hist[0].primary_department == "WATER"
    assert hist[0].confidence > 0
    await _delete_user(email)


@pytest.mark.asyncio
async def test_run_routing_rerun_tracks_change(client):
    email = _unique_email("rout-rerun")
    token = await _citizen_token(email)
    # A FLOODING complaint → Drainage (multi-dept).
    complaint_id = await _create_complaint(
        client, token, desc="Street flooding after rain.", category="FLOODING"
    )

    async with async_session_factory() as db:
        first = await RoutingAgent(settings=_SETTINGS).run(db, complaint_id=uuid.UUID(complaint_id))
    async with async_session_factory() as db:
        second = await RoutingAgent(settings=_SETTINGS).run(
            db, complaint_id=uuid.UUID(complaint_id)
        )

    assert first.status.value == "SUCCEEDED"
    assert second.status.value == "SUCCEEDED"
    assert first.structured_result["primary_department"] == "DRAINAGE"
    assert second.structured_result["previous_department"] == "DRAINAGE"
    # Same routing on the re-run → unchanged.
    assert second.structured_result["changed"] is False

    async with async_session_factory() as db:
        hist = (
            (
                await db.execute(
                    select(ComplaintDepartmentHistory).where(
                        ComplaintDepartmentHistory.complaint_id == uuid.UUID(complaint_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(hist) == 2
    await _delete_user(email)


@pytest.mark.asyncio
async def test_detail_surfaces_effective_department_after_override(client):
    email = _unique_email("rout-detail")
    officer_email = _unique_email("rout-off-detail")
    token = await _citizen_token(email)
    officer_token = await _officer_token(officer_email)
    complaint_id = await _create_complaint(
        client, token, desc="Garbage pile on sidewalk.", category="GARBAGE"
    )

    await client.post(
        f"{_BASE}/{complaint_id}/routing", headers={"Authorization": f"Bearer {officer_token}"}
    )
    # Override to a different department.
    ov = await client.post(
        f"{_BASE}/{complaint_id}/routing/override",
        json={"new_department": "PARKS", "reason": "Officer deemed this a parks issue."},
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert ov.status_code == 200, ov.text
    assert ov.json()["override"]["old_department"] == "WASTE"
    assert ov.json()["override"]["new_department"] == "PARKS"
    assert ov.json()["override"]["override_by_name"] == "Routing Officer"

    detail = await client.get(
        f"{_BASE}/{complaint_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["department"] == "PARKS"
    await _delete_user(email)
    await _delete_user(officer_email)


# --------------------------------------------------------------------------- #
# API + RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_routing_requires_auth(client):
    r = await client.post(f"{_BASE}/{uuid.uuid4()}/routing")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_routing_requires_access(client):
    owner_email = _unique_email("rout-ow")
    other_email = _unique_email("rout-oth")
    owner_token = await _citizen_token(owner_email)
    other_token = await _citizen_token(other_email)
    complaint_id = await _create_complaint(client, owner_token, desc="Some issue.", category="ROAD")
    r = await client.post(
        f"{_BASE}/{complaint_id}/routing", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert r.status_code == 403, r.text
    await _delete_user(owner_email)
    await _delete_user(other_email)


@pytest.mark.asyncio
async def test_api_routing_404_unknown_complaint(client):
    otoken = await _officer_token(_unique_email("rout-404-officer"))
    r = await client.post(
        f"{_BASE}/{uuid.uuid4()}/routing", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_api_routing_full_run_result_and_history(client):
    email = _unique_email("rout-api")
    token = await _citizen_token(email)
    otoken = await _officer_token(_unique_email("rout-api-officer"))
    complaint_id = await _create_complaint(
        client, token, desc="Flooding on approach road.", category="FLOODING"
    )

    resp = await client.post(
        f"{_BASE}/{complaint_id}/routing", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "SUCCEEDED"
    result = body["result"]
    assert result["primary_department"] == "DRAINAGE"
    assert "ROADS" in result["secondary_departments"]

    getr = await client.get(
        f"{_BASE}/{complaint_id}/routing-result", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert getr.status_code == 200, getr.text
    assert getr.json()["agent"] == "routing"
    assert getr.json()["structured_result"]["primary_department"] == "DRAINAGE"

    h = await client.get(
        f"{_BASE}/{complaint_id}/routing-history", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert h.status_code == 200, h.text
    assert len(h.json()["entries"]) == 1
    assert h.json()["entries"][0]["primary_department"] == "DRAINAGE"
    await _delete_user(email)


@pytest.mark.asyncio
async def test_api_routing_result_none_before_run(client):
    email = _unique_email("rout-null")
    token = await _citizen_token(email)
    otoken = await _officer_token(_unique_email("rout-null-officer"))
    complaint_id = await _create_complaint(client, token, desc="Nothing yet.", category="PARKS")
    getr = await client.get(
        f"{_BASE}/{complaint_id}/routing-result", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert getr.status_code == 200, getr.text
    assert getr.json() is None
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Override RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_override_requires_officer_role(client):
    citizen_email = _unique_email("rout-cit")
    officer_email = _unique_email("rout-off")
    citizen_token = await _citizen_token(citizen_email)
    officer_token = await _officer_token(officer_email)
    complaint_id = await _create_complaint(
        client, citizen_token, desc="Water issue.", category="WATER"
    )

    # Citizen must be denied (403).
    denied = await client.post(
        f"{_BASE}/{complaint_id}/routing/override",
        json={"new_department": "ROADS", "reason": "citizen attempt"},
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert denied.status_code == 403, denied.text

    # Officer (staff) is allowed and the audit row is recorded.
    ok = await client.post(
        f"{_BASE}/{complaint_id}/routing/override",
        json={"new_department": "ROADS", "reason": "officer correction"},
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert ok.status_code == 200, ok.text
    over = ok.json()["override"]
    assert over["old_department"] is None  # no routing/override was set yet
    assert over["new_department"] == "ROADS"
    assert over["reason"] == "officer correction"
    assert over["override_by_name"] == "Routing Officer"

    # Override history shows the recorded audit trail (officer-only view).
    hist = await client.get(
        f"{_BASE}/{complaint_id}/routing/overrides",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert hist.status_code == 200, hist.text
    assert len(hist.json()["overrides"]) == 1
    await _delete_user(citizen_email)
    await _delete_user(officer_email)


@pytest.mark.asyncio
async def test_override_requires_auth(client):
    r = await client.post(
        f"{_BASE}/{uuid.uuid4()}/routing/override",
        json={"new_department": "WATER", "reason": "x"},
    )
    assert r.status_code == 401
