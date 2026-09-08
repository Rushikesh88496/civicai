"""Tests for Work Orders & Autonomous Dispatch (Part 14).

Layers exercised:

* **Engine** — ``app.services.dispatch_engine`` scores candidates on the five
  criteria (availability / skill / distance / workload / equipment) and ranks
  them deterministically (score desc, then name, then id) — never random.
* **Agent + service + API** — dispatching a complaint runs the deterministic
  graph, persists a *draft* ``WorkOrder`` (``PENDING_APPROVAL``) with an honest
  ETA (``source="estimated"`` when no live provider key is configured), and
  returns a recommendation + the created order. It selects an available worker
  with the required skills/equipment, falls back to an explicit ``no_worker_reason``
  when nobody is currently available (busy or unmatched), and keeps its selection
  deterministic across repeated runs.
* **Officer actions** — approve / assign / reassign / escalate / reject are
  RBAC-gated (OFFICER/ADMIN/WARD_REP allowed, CITIZEN denied) and record an
  append-only ``WorkOrderStatusHistory`` trail plus worker assignments.
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    Complaint,
    Department,
    FieldWorker,
    Role,
    User,
    UserProfile,
)
from app.models.enums import RoleName, WorkerStatus
from app.schemas.auth import RegisterIn
from app.services import auth_service

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"
_WO = "/api/v1/work-orders"
_SETTINGS = get_settings()
_LAT = 17.4327
_LON = 78.3885


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_token(email: str, full_name: str = "Dispatch Citizen") -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db, RegisterIn(email=email, password=_PASSWORD, full_name=full_name)
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _officer(email: str) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Dispatch Officer",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), RoleName.OFFICER.value)


async def _create_complaint(client, token: str, *, category: str = "GARBAGE") -> str:
    body = {
        "description": f"{category} dispatch test",
        "category": category,
        "media_ids": [],
        "location": {
            "latitude": _LAT,
            "longitude": _LON,
            "address": "Dispatch test location",
            "source": "gps",
            "geopoint_denied": False,
        },
    }
    r = await client.post(_BASE, json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _clear_workers() -> None:
    """Remove all field workers + their auth users so a test's pool is deterministic."""
    async with async_session_factory() as db:
        fws = (await db.execute(select(FieldWorker))).scalars().all()
        for fw in fws:
            await db.delete(fw)
        rrole = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        workers_users = (
            (await db.execute(select(User).where(User.role_id == rrole.id))).scalars().all()
        )
        for u in workers_users:
            await db.delete(u)
        await db.commit()


async def _seed_worker(
    *,
    email: str,
    dept_code: str,
    name: str = "Worker",
    specialty: str | None = None,
    skill_tags: list | None = None,
    equipment: list | None = None,
    lat: float | None = _LAT,
    lon: float | None = _LON,
    max_active_orders: int | None = None,
    status: WorkerStatus = WorkerStatus.ACTIVE,
    user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    async with async_session_factory() as db:
        dept = await db.scalar(select(Department).where(Department.code == dept_code))
        if dept is None:
            dept = Department(name=dept_code, code=dept_code, description=f"{dept_code} crew")
            db.add(dept)
            await db.flush()

        if user_id is None:
            rrole = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
            user = User(
                email=email,
                password_hash=hash_password(_PASSWORD),
                full_name=name,
                role_id=rrole.id,
                is_active=True,
                is_email_verified=True,
            )
            db.add(user)
            await db.flush()
            db.add(UserProfile(user_id=user.id))
            user_id = user.id

        fw = FieldWorker(
            user_id=user_id,
            department_id=dept.id,
            specialty=specialty,
            status=status,
            home_latitude=lat,
            home_longitude=lon,
            skill_tags=skill_tags or [],
            equipment=equipment or [],
            max_active_orders=max_active_orders,
        )
        db.add(fw)
        await db.commit()
        return fw.id


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _delete_complaint(complaint_id: str) -> None:
    async with async_session_factory() as db:
        await db.execute(delete(Complaint).where(Complaint.id == complaint_id))
        await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Engine: determinism, availability, scoring, ties
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_engine_ranks_deterministically():
    from app.services.dispatch_engine import CandidateInput, rank_candidates

    workers = [
        CandidateInput(
            worker_id=uuid.uuid4(),
            name="Alpha",
            department_code="WASTE",
            status=WorkerStatus.ACTIVE,
            specialty="waste-audit",
            skill_tags=["collections"],
            equipment=["garbage-truck", "broom"],
            home_lat=_LAT,
            home_lon=_LON,
            active_orders=0,
        ),
        CandidateInput(
            worker_id=uuid.uuid4(),
            name="Beta",
            department_code="WASTE",
            status=WorkerStatus.ACTIVE,
            specialty=None,
            skill_tags=[],
            equipment=[],
            home_lat=_LAT,
            home_lon=_LON,
            active_orders=0,
        ),
    ]
    r1 = rank_candidates(
        workers,
        required_skills=["waste-audit"],
        required_equipment=["garbage-truck"],
        order_lat=_LAT,
        order_lon=_LON,
        department="WASTE",
    )
    r2 = rank_candidates(
        workers,
        required_skills=["waste-audit"],
        required_equipment=["garbage-truck"],
        order_lat=_LAT,
        order_lon=_LON,
        department="WASTE",
    )
    assert [c.worker_id for c in r1] == [c.worker_id for c in r2]
    assert r1[0].score >= r1[1].score
    assert r1[0].available is True
    assert r1[0].skill == 1.0 or r1[0].skill > r1[1].skill


@pytest.mark.asyncio
async def test_engine_busy_worker_not_available():
    from app.services.dispatch_engine import CandidateInput, score_candidate

    wid = uuid.uuid4()
    w = CandidateInput(
        worker_id=wid,
        name="Busy",
        department_code="WASTE",
        status=WorkerStatus.ACTIVE,
        specialty="waste-audit",
        skill_tags=["collections"],
        equipment=["garbage-truck"],
        home_lat=_LAT,
        home_lon=_LON,
        active_orders=3,
        max_active_orders=3,
    )
    c = score_candidate(
        w, required_skills=[], required_equipment=[], order_lat=_LAT, order_lon=_LON
    )
    assert c.available is False
    assert c.availability == 0.0
    assert "busy or unavailable" in c.reasons


# --------------------------------------------------------------------------- #
# Agent + service + API
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dispatch_selects_available_worker(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-avail")
    token = await _citizen_token(email)
    wid = await _seed_worker(
        email=_unique_email("worker-avail"),
        dept_code="WASTE",
        name="Waste Wendy",
        specialty="waste-audit",
        skill_tags=["waste-audit", "collections"],
        equipment=["garbage-truck", "broom"],
    )
    cid = await _create_complaint(client, token)
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["work_order_id"] is not None
        rec = data["result"]["recommendation"]
        assert rec["department"] == "WASTE"
        assert rec["recommended_worker_id"] == str(wid)
        assert rec["eta_source"] == "estimated"
        assert rec["eta_minutes"] is not None
        assert [c["worker_id"] for c in rec["candidates"]] == [str(wid)]
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_no_worker_sets_reason(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-none")
    token = await _citizen_token(email)
    cid = await _create_complaint(client, token)
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        assert r.status_code == 201, r.text
        data = r.json()
        rec = data["result"]["recommendation"]
        assert rec["recommended_worker_id"] is None
        assert rec["no_worker_reason"]
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_wrong_skill_worker_scores_low(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-skill")
    token = await _citizen_token(email)
    wid = await _seed_worker(
        email=_unique_email("worker-skill"),
        dept_code="WASTE",
        name="Wrong Skill",
        specialty="electrical-line",
        skill_tags=["electrical-line"],
        equipment=["bucket-truck"],
    )
    cid = await _create_complaint(client, token)
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        assert r.status_code == 201, r.text
        data = r.json()
        rec = data["result"]["recommendation"]
        cands = {c["worker_id"]: c for c in rec["candidates"]}
        assert str(wid) in cands
        assert cands[str(wid)]["available"] is True
        assert cands[str(wid)]["skill"] < 0.5
        assert cands[str(wid)]["reasons"]
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_busy_worker_sets_no_worker(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-busy")
    token = await _citizen_token(email)
    busy_wid = await _seed_worker(
        email=_unique_email("worker-busy"),
        dept_code="WASTE",
        name="Busy Betty",
        specialty="waste-audit",
        skill_tags=["waste-audit"],
        equipment=["garbage-truck"],
        max_active_orders=1,
    )
    # Give Betty one active assignment so she is at her workload ceiling.
    from app.models import WorkerAssignment, WorkOrder

    async with async_session_factory() as db:
        busy_cid = await _create_complaint(client, token)
        busy_order = WorkOrder(
            complaint_id=busy_cid,
            department="WASTE",
            status="ASSIGNED",
            worker_id=busy_wid,
            created_by=None,
        )
        db.add(busy_order)
        await db.flush()
        db.add(
            WorkerAssignment(
                work_order_id=busy_order.id,
                worker_id=busy_wid,
                status="ASSIGNED",
                assigned_by=None,
                reason="seed busy",
            )
        )
        await db.commit()
    cid = await _create_complaint(client, token)
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        assert r.status_code == 201, r.text
        rec = r.json()["result"]["recommendation"]
        assert rec["recommended_worker_id"] is None
        assert rec["no_worker_reason"]
        cand = rec["candidates"]
        assert cand and cand[0]["available"] is False
    finally:
        await _delete_complaint(cid)
        await _delete_complaint(busy_cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_closest_skilled_worker_wins(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-multi")
    token = await _citizen_token(email)
    far_id = await _seed_worker(
        email=_unique_email("worker-far"),
        dept_code="WASTE",
        name="Far",
        specialty="waste-audit",
        skill_tags=["waste-audit"],
        equipment=["garbage-truck"],
        lat=_LAT + 5.0,
        lon=_LON,
    )
    near_id = await _seed_worker(
        email=_unique_email("worker-near"),
        dept_code="WASTE",
        name="Near",
        specialty="waste-audit",
        skill_tags=["waste-audit"],
        equipment=["garbage-truck"],
        lat=_LAT,
        lon=_LON,
    )
    cid = await _create_complaint(client, token)
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        assert r.status_code == 201, r.text
        rec = r.json()["result"]["recommendation"]
        assert rec["recommended_worker_id"] == str(near_id)
        near_d = next(c for c in rec["candidates"] if c["worker_id"] == str(near_id))["distance"]
        far_d = next(c for c in rec["candidates"] if c["worker_id"] == str(far_id))["distance"]
        assert near_d > far_d
        order = [c["worker_id"] for c in rec["candidates"]]
        # deterministic ordering: near is ranked above far
        assert order.index(str(near_id)) < order.index(str(far_id))
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_multi_department_flooding(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-flood")
    token = await _citizen_token(email)
    wid = await _seed_worker(
        email=_unique_email("worker-drain"),
        dept_code="DRAINAGE",
        name="Drainage Dan",
        specialty="drainage",
        skill_tags=["drainage", "jetted-outfall"],
        equipment=["jetting-rig", "manhole-tool"],
    )
    cid = await _create_complaint(client, token, category="FLOODING")
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        assert r.status_code == 201, r.text
        rec = r.json()["result"]["recommendation"]
        assert rec["department"] == "DRAINAGE"
        assert rec["recommended_worker_id"] == str(wid)
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_persists_draft_work_order(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    email = _unique_email("dispatch-persist")
    token = await _citizen_token(email)
    cid = await _create_complaint(client, token)
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        assert r.status_code == 201, r.text
        wid = r.json()["work_order_id"]
        lr = await client.get(f"{_BASE}/{cid}/work-orders", headers=_auth(token))
        assert lr.status_code == 200, lr.text
        orders = lr.json()["work_orders"]
        assert any(o["id"] == wid for o in orders)
        detail = await client.get(f"{_WO}/{wid}", headers=_auth(token))
        assert detail.status_code == 200, detail.text
        d = detail.json()
        assert d["work_order"]["status"] == "PENDING_APPROVAL"
        assert d["work_order"]["complaint_id"] == cid
        hist = await client.get(f"{_WO}/{wid}/history", headers=_auth(token))
        assert hist.status_code == 200
        assert hist.json()["entries"]
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# RBAC + missing resource
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dispatch_requires_auth(client):
    r = await client.post(f"{_BASE}/00000000-0000-0000-0000-000000000000/dispatch", json={})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_dispatch_unknown_complaint_404(client):
    email = _unique_email("dispatch-404")
    token = await _citizen_token(email)
    try:
        r = await client.post(
            f"{_BASE}/00000000-0000-0000-0000-000000000000/dispatch", headers=_auth(token)
        )
        assert r.status_code == 404
    finally:
        await _delete_user(email)


@pytest.mark.asyncio
async def test_citizen_cannot_approve(client):
    email = _unique_email("dispatch-rbac")
    token = await _citizen_token(email)
    cid = await _create_complaint(client, token)
    try:
        d = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        wid = d.json()["work_order_id"]
        r = await client.post(f"{_WO}/{wid}/approve", json={"note": "nope"}, headers=_auth(token))
        assert r.status_code == 403
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_officer_approve_assign_reassign_escalate(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-officer")
    token = await _citizen_token(email)
    otoken = await _officer(_unique_email("dispatch-officer-role"))
    await _seed_worker(
        email=_unique_email("worker-approve"),
        dept_code="WASTE",
        name="Approve Worker",
        specialty="waste-audit",
        skill_tags=["waste-audit"],
        equipment=["garbage-truck"],
    )
    cid = await _create_complaint(client, token)
    try:
        d = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        work_id = d.json()["work_order_id"]

        ap = await client.post(
            f"{_WO}/{work_id}/approve", json={"note": "go"}, headers=_auth(otoken)
        )
        assert ap.status_code == 200, ap.text
        assert ap.json()["work_order"]["status"] == "ASSIGNED"

        second = await _seed_worker(
            email=_unique_email("worker-approve2"),
            dept_code="WASTE",
            name="Second Worker",
            specialty="waste-audit",
            skill_tags=["waste-audit"],
            equipment=["garbage-truck"],
        )
        re = await client.post(
            f"{_WO}/{work_id}/reassign",
            json={"worker_id": str(second), "reason": "move"},
            headers=_auth(otoken),
        )
        assert re.status_code == 200, re.text
        assert re.json()["work_order"]["worker_name"] == "Second Worker"

        es = await client.post(
            f"{_WO}/{work_id}/escalate", json={"reason": "out of SLA"}, headers=_auth(otoken)
        )
        assert es.status_code == 200, es.text
        assert es.json()["work_order"]["status"] == "ESCALATED"

        hist = await client.get(f"{_WO}/{work_id}/history", headers=_auth(otoken))
        actions = [h["action"] for h in hist.json()["entries"]]
        assert "APPROVE" in actions and "REASSIGN" in actions and "ESCALATE" in actions
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_officer_reject_draft(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-reject")
    token = await _citizen_token(email)
    otoken = await _officer(_unique_email("dispatch-reject-role"))
    cid = await _create_complaint(client, token)
    try:
        d = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(token))
        work_id = d.json()["work_order_id"]
        rj = await client.post(
            f"{_WO}/{work_id}/reject", json={"note": "no"}, headers=_auth(otoken)
        )
        assert rj.status_code == 200, rj.text
        assert rj.json()["work_order"]["status"] == "REJECTED"
        rj2 = await client.post(f"{_WO}/{work_id}/approve", json={}, headers=_auth(otoken))
        assert rj2.status_code == 409
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)
