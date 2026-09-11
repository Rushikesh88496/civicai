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
from sqlalchemy import delete, select, update

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
    Ward,
)
from app.models.enums import RoleName, WorkerStatus
from app.schemas.auth import RegisterIn
from app.services import auth_service
from tests.helpers import any_active_ward_id

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
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name=full_name,
                ward_id=await any_active_ward_id(db),
            ),
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
    ward_id: uuid.UUID | None = None,
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
                ward_id=ward_id,
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
async def test_engine_department_crew_alias_prefers_owning_crew():
    from app.services.dispatch_engine import CandidateInput, rank_candidates

    # Two workers identical on every criterion except their crew. The routed
    # department is WASTE, which the Sanitation crew (SN) owns — so SN must
    # out-rank PW solely because of the department-match factor.
    pw = CandidateInput(
        worker_id=uuid.uuid4(),
        name="PW Worker",
        department_code="PW",
        status=WorkerStatus.ACTIVE,
        specialty="waste-audit",
        skill_tags=["collections"],
        equipment=["garbage-truck"],
        home_lat=_LAT,
        home_lon=_LON,
        active_orders=0,
    )
    sn = CandidateInput(
        worker_id=uuid.uuid4(),
        name="SN Worker",
        department_code="SN",
        status=WorkerStatus.ACTIVE,
        specialty="waste-audit",
        skill_tags=["collections"],
        equipment=["garbage-truck"],
        home_lat=_LAT,
        home_lon=_LON,
        active_orders=0,
    )
    scored = rank_candidates(
        [pw, sn],
        required_skills=["waste-audit"],
        required_equipment=["garbage-truck"],
        order_lat=_LAT,
        order_lon=_LON,
        department="WASTE",
    )
    by_id = {c.worker_id: c for c in scored}
    assert by_id[sn.worker_id].department == 1.0
    assert by_id[pw.worker_id].department == 0.0
    assert scored[0].worker_id == sn.worker_id


@pytest.mark.asyncio
async def test_engine_exact_department_code_matches():
    from app.services.dispatch_engine import CandidateInput, score_candidate

    w = CandidateInput(
        worker_id=uuid.uuid4(),
        name="Direct Crew",
        department_code="WASTE",
        status=WorkerStatus.ACTIVE,
        specialty="collections",
        skill_tags=[],
        equipment=[],
        home_lat=_LAT,
        home_lon=_LON,
    )
    c = score_candidate(
        w,
        required_skills=[],
        required_equipment=[],
        order_lat=_LAT,
        order_lon=_LON,
        order_department="WASTE",
    )
    assert c.department == 1.0
    assert "different department" not in c.reasons


@pytest.mark.asyncio
async def test_engine_ward_match_prefers_same_ward():
    from app.services.dispatch_engine import CandidateInput, rank_candidates

    w1 = CandidateInput(
        worker_id=uuid.uuid4(),
        name="Ward One",
        department_code="WASTE",
        status=WorkerStatus.ACTIVE,
        specialty="waste-audit",
        skill_tags=["collections"],
        equipment=["garbage-truck"],
        home_lat=_LAT,
        home_lon=_LON,
        ward_code="WARD-1",
    )
    w2 = CandidateInput(
        worker_id=uuid.uuid4(),
        name="Ward Two",
        department_code="WASTE",
        status=WorkerStatus.ACTIVE,
        specialty="waste-audit",
        skill_tags=["collections"],
        equipment=["garbage-truck"],
        home_lat=_LAT,
        home_lon=_LON,
        ward_code="WARD-2",
    )
    scored = rank_candidates(
        [w1, w2],
        required_skills=["waste-audit"],
        required_equipment=["garbage-truck"],
        order_lat=_LAT,
        order_lon=_LON,
        department="WASTE",
        order_ward="WARD-1",
    )
    by_id = {c.worker_id: c for c in scored}
    assert by_id[w1.worker_id].ward == 1.0
    assert by_id[w2.worker_id].ward == 0.0
    assert scored[0].worker_id == w1.worker_id
    assert "different ward" in by_id[w2.worker_id].reasons


@pytest.mark.asyncio
async def test_engine_priority_urgency_factor():
    from app.services.dispatch_engine import CandidateInput, score_candidate

    w = CandidateInput(
        worker_id=uuid.uuid4(),
        name="Any Worker",
        department_code="WASTE",
        status=WorkerStatus.ACTIVE,
        specialty="waste-audit",
        skill_tags=["collections"],
        equipment=["garbage-truck"],
        home_lat=_LAT,
        home_lon=_LON,
    )
    urgent = score_candidate(
        w,
        required_skills=["waste-audit"],
        required_equipment=[],
        order_lat=_LAT,
        order_lon=_LON,
        priority="P1_CRITICAL",
    )
    calm = score_candidate(
        w,
        required_skills=["waste-audit"],
        required_equipment=[],
        order_lat=_LAT,
        order_lon=_LON,
        priority="P4_LOW",
    )
    assert urgent.priority == 1.0
    assert calm.priority == 0.5


# --------------------------------------------------------------------------- #
# Agent + service + API
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
    otoken = await _officer(_unique_email("dispatch-avail-officer"))
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
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
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
    otoken = await _officer(_unique_email("dispatch-none-officer"))
    cid = await _create_complaint(client, token)
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
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
    otoken = await _officer(_unique_email("dispatch-skill-officer"))
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
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
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
    otoken = await _officer(_unique_email("dispatch-busy-officer"))
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
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
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
    otoken = await _officer(_unique_email("dispatch-multi-officer"))
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
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
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
    otoken = await _officer(_unique_email("dispatch-flood-officer"))
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
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
        assert r.status_code == 201, r.text
        rec = r.json()["result"]["recommendation"]
        assert rec["department"] == "DRAINAGE"
        assert rec["recommended_worker_id"] == str(wid)
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_real_seeded_worker_vocabulary_matches_routing(client, monkeypatch):
    """A worker seeded exactly like the 25 real field workers (PW crew, real
    skill tags) must score >0 on skill for its routed department and be the
    recommended worker — this is what connects dispatch to the real crews."""
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-vocab")
    token = await _citizen_token(email)
    otoken = await _officer(_unique_email("dispatch-vocab-officer"))
    wid = await _seed_worker(
        email=_unique_email("worker-vocab"),
        dept_code="PW",
        name="Road Ramesh",
        specialty="Road Maintenance",
        skill_tags=["road-maintenance", "asphalt", "patching"],
        equipment=["road-roller", "compactor"],
    )
    cid = await _create_complaint(client, token, category="ROAD")
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
        assert r.status_code == 201, r.text
        rec = r.json()["result"]["recommendation"]
        assert rec["department"] == "ROADS"
        assert "road-maintenance" in rec["required_skills"]
        cands = {c["worker_id"]: c for c in rec["candidates"]}
        assert str(wid) in cands
        assert cands[str(wid)]["department"] == 1.0
        assert cands[str(wid)]["skill"] > 0.0
        assert cands[str(wid)]["available"] is True
        assert rec["recommended_worker_id"] == str(wid)
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_prefers_same_ward_worker(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-ward")
    token = await _citizen_token(email)
    otoken = await _officer(_unique_email("dispatch-ward-officer"))
    async with async_session_factory() as db:
        w1 = await db.scalar(select(Ward).where(Ward.code == "WARD-1"))
        w2 = await db.scalar(select(Ward).where(Ward.code == "WARD-2"))
        assert w1 is not None and w2 is not None
        ward1_id, ward2_id = w1.id, w2.id
    inw = await _seed_worker(
        email=_unique_email("worker-in-ward"),
        dept_code="WASTE",
        name="In Ward",
        specialty="waste-audit",
        skill_tags=["waste-audit"],
        equipment=["garbage-truck"],
        ward_id=ward1_id,
    )
    outw = await _seed_worker(
        email=_unique_email("worker-out-ward"),
        dept_code="WASTE",
        name="Out Ward",
        specialty="waste-audit",
        skill_tags=["waste-audit"],
        equipment=["garbage-truck"],
        ward_id=ward2_id,
    )
    cid = await _create_complaint(client, token)
    # Pin the complaint to WARD-1 so the ward factor is deterministic.
    async with async_session_factory() as db:
        await db.execute(update(Complaint).where(Complaint.id == cid).values(ward_id=ward1_id))
        await db.commit()
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
        assert r.status_code == 201, r.text
        rec = r.json()["result"]["recommendation"]
        assert rec["recommended_worker_id"] == str(inw)
        cands = {c["worker_id"]: c for c in rec["candidates"]}
        assert cands[str(inw)]["ward"] == 1.0
        assert cands[str(outw)]["ward"] == 0.0
        order = [c["worker_id"] for c in rec["candidates"]]
        assert order.index(str(inw)) < order.index(str(outw))
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_candidate_reports_postgis_distance_km(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("dispatch-km")
    token = await _citizen_token(email)
    otoken = await _officer(_unique_email("dispatch-km-officer"))
    wid = await _seed_worker(
        email=_unique_email("worker-km"),
        dept_code="WASTE",
        name="Km Wendy",
        specialty="waste-audit",
        skill_tags=["waste-audit"],
        equipment=["garbage-truck"],
    )
    cid = await _create_complaint(client, token)
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
        assert r.status_code == 201, r.text
        cands = r.json()["result"]["recommendation"]["candidates"]
        cand = next(c for c in cands if c["worker_id"] == str(wid))
        assert cand["distance_km"] is None or cand["distance_km"] >= 0.0
        if cand["distance_km"] is not None:
            assert cand["distance_km"] < 60.0  # home is right at the complaint point
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_dispatch_persists_draft_work_order(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    email = _unique_email("dispatch-persist")
    token = await _citizen_token(email)
    otoken = await _officer(_unique_email("dispatch-persist-officer"))
    cid = await _create_complaint(client, token)
    try:
        r = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
        assert r.status_code == 201, r.text
        wid = r.json()["work_order_id"]
        lr = await client.get(f"{_BASE}/{cid}/work-orders", headers=_auth(otoken))
        assert lr.status_code == 200, lr.text
        orders = lr.json()["work_orders"]
        assert any(o["id"] == wid for o in orders)
        detail = await client.get(f"{_WO}/{wid}", headers=_auth(otoken))
        assert detail.status_code == 200, detail.text
        d = detail.json()
        assert d["work_order"]["status"] == "PENDING_APPROVAL"
        assert d["work_order"]["complaint_id"] == cid
        hist = await client.get(f"{_WO}/{wid}/history", headers=_auth(otoken))
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
    otoken = await _officer(email)
    try:
        r = await client.post(
            f"{_BASE}/00000000-0000-0000-0000-000000000000/dispatch", headers=_auth(otoken)
        )
        assert r.status_code == 404
    finally:
        await _delete_user(email)


@pytest.mark.asyncio
async def test_citizen_cannot_approve(client):
    email = _unique_email("dispatch-rbac")
    token = await _citizen_token(email)
    otoken = await _officer(_unique_email("dispatch-rbac-officer"))
    cid = await _create_complaint(client, token)
    try:
        d = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
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
        d = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
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
        d = await client.post(f"{_BASE}/{cid}/dispatch", headers=_auth(otoken))
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
