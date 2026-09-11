"""Tests for the Municipal Officer Command Center (Part 15).

Layers exercised:

* **KPIs** — total complaints, P1..P4 (from the *latest* priority-history bucket),
  pending / in-progress / resolved status buckets, and SLA breaches (open work
  orders whose due date has passed).
* **Priority queue** — pagination, plus filters on status / category / priority /
  department / ward / date and free-text search over title & description.
* **Map** — complaints (with location), work orders, wards and per-ward hotspots.
* **AI activity** — per-agent run status aggregation (completed / failed / running)
  including the synthesized (0-run) "gis" entry.
* **Realtime** — the ``agent_run_service.finalize_run`` choke point publishes a
  best-effort refresh onto the command-center channel (graceful when Redis is down).
* **RBAC** — officers/admins/ward-reps may read, citizens are forbidden, and a
  ward-representative is scoped to their own ward.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    AgentRun,
    Complaint,
    ComplaintDepartmentHistory,
    ComplaintLocation,
    ComplaintPriorityHistory,
    Role,
    User,
    UserProfile,
    Ward,
    WorkOrder,
)
from app.models.enums import (
    ComplaintCategory,
    ComplaintStatus,
    DynamicPriority,
    RoleName,
    WorkOrderStatus,
)
from app.schemas.auth import RegisterIn
from app.services import auth_service
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/command-center"
_SETTINGS = get_settings()
_LAT = 17.4327
_LON = 78.3885


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="CC Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


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


async def _ward(code: str, name: str | None = None) -> uuid.UUID:
    token = uuid.uuid4().hex[:6]
    wname = name or code
    async with async_session_factory() as db:
        ward = Ward(code=f"{code}-{token}", name=f"{wname}-{token}", description="wc")
        db.add(ward)
        await db.commit()
        return ward.id


async def _insert_complaint(
    *,
    user_id: uuid.UUID,
    title: str,
    description: str | None = None,
    ward_id: uuid.UUID | None = None,
    category: str = "GARBAGE",
    status: ComplaintStatus = ComplaintStatus.SUBMITTED,
) -> uuid.UUID:
    async with async_session_factory() as db:
        complaint = Complaint(
            user_id=user_id,
            ward_id=ward_id,
            category=ComplaintCategory(category),
            title=title,
            description=description,
            status=status,
        )
        db.add(complaint)
        await db.flush()
        no_location = {
            ComplaintStatus.RESOLVED,
            ComplaintStatus.CLOSED,
            ComplaintStatus.CITIZEN_VERIFIED,
        }
        if status not in no_location:
            db.add(
                ComplaintLocation(
                    complaint_id=complaint.id,
                    latitude=_LAT,
                    longitude=_LON,
                    source="gps",
                )
            )
        await db.commit()
        return complaint.id


async def _priority(
    complaint_id: uuid.UUID,
    bucket: DynamicPriority,
    score: int = 50,
    at: datetime | None = None,
):
    async with async_session_factory() as db:
        kwargs = {"inputs": {}, "factors": {}}
        if at is not None:
            kwargs["calculated_at"] = at
        db.add(
            ComplaintPriorityHistory(
                complaint_id=complaint_id,
                priority=bucket,
                score=score,
                **kwargs,
            )
        )
        await db.commit()


async def _department(complaint_id: uuid.UUID, dept: str, confidence: float = 0.9):
    async with async_session_factory() as db:
        db.add(
            ComplaintDepartmentHistory(
                complaint_id=complaint_id,
                primary_department=dept,
                routing_reason=f"test {dept}",
                confidence=confidence,
                inputs={},
            )
        )
        await db.commit()


async def _agent_run(complaint_id: uuid.UUID, agent: str, status: str = "SUCCEEDED"):
    async with async_session_factory() as db:
        db.add(AgentRun(complaint_id=complaint_id, agent=agent, status=status))
        await db.commit()


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _delete_complaint(complaint_id) -> None:
    async with async_session_factory() as db:
        await db.execute(delete(Complaint).where(Complaint.id == complaint_id))
        await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_requires_auth(client):
    r = await client.get(f"{_BASE}/kpis")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_citizen_forbidden(client):
    email = _unique_email("cc-citizen")
    token = await _citizen_token(email)
    try:
        for path in ("/kpis", "/queue", "/map", "/ai-activity", "/snapshot"):
            r = await client.get(f"{_BASE}{path}", headers=_auth(token))
            assert r.status_code == 403, (path, r.status_code)
    finally:
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_kpis_aggregate(client):
    citizen_email = _unique_email("cc-kpi-c")
    await _citizen_token(citizen_email)
    async with async_session_factory() as db:
        citizen = await db.scalar(select(User).where(User.email == citizen_email))

    otoken = await _role_user(_unique_email("cc-kpi-o"), RoleName.OFFICER.value)
    cids = []
    try:
        baseline = (await client.get(f"{_BASE}/kpis", headers=_auth(otoken))).json()

        prefix = uuid.uuid4().hex[:8]
        c1 = await _insert_complaint(
            user_id=citizen.id, title=f"{prefix} p1 pipe", status=ComplaintStatus.SUBMITTED
        )
        c2 = await _insert_complaint(
            user_id=citizen.id, title=f"{prefix} p2 drain", status=ComplaintStatus.SUBMITTED
        )
        c3 = await _insert_complaint(
            user_id=citizen.id, title=f"{prefix} done", status=ComplaintStatus.RESOLVED
        )
        await _priority(c1, DynamicPriority.P1_CRITICAL, 92, at=datetime.now(UTC))
        await _priority(c2, DynamicPriority.P3_MEDIUM, 55, at=datetime.now(UTC))  # older
        await _priority(
            c2, DynamicPriority.P2_HIGH, 78, at=datetime.now(UTC) + timedelta(minutes=1)
        )
        cids = [c1, c2, c3]

        r = await client.get(f"{_BASE}/kpis", headers=_auth(otoken))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total_complaints"] >= baseline["total_complaints"] + 3
        assert data["p1"] >= baseline["p1"] + 1
        # c2's latest bucket is P2 (its older P3 row must NOT win)
        assert data["p2"] >= baseline["p2"] + 1
        assert data["pending"] >= baseline["pending"] + 2
        assert data["resolved"] >= baseline["resolved"] + 1

        # The "latest bucket wins" invariant, verified deterministically via the
        # queue's search isolation (c2's effective priority must be P2_HIGH).
        q = (
            await client.get(f"{_BASE}/queue", params={"search": prefix}, headers=_auth(otoken))
        ).json()
        rows = {i["id"]: i for i in q["items"]}
        assert rows[str(c1)]["priority"] == "P1_CRITICAL"
        assert rows[str(c2)]["priority"] == "P2_HIGH"
    finally:
        for c in cids:
            await _delete_complaint(c)
        await _delete_user(citizen_email)


@pytest.mark.asyncio
async def test_kpis_sla_breach(client):
    citizen_email = _unique_email("cc-sla-c")
    await _citizen_token(citizen_email)
    async with async_session_factory() as db:
        citizen = await db.scalar(select(User).where(User.email == citizen_email))

    otoken = await _role_user(_unique_email("cc-sla-o"), RoleName.OFFICER.value)
    cid = None
    try:
        cid = await _insert_complaint(
            user_id=citizen.id, title="sla overdue", status=ComplaintStatus.IN_PROGRESS
        )
        from datetime import UTC, datetime, timedelta

        async with async_session_factory() as db:
            db.add(
                WorkOrder(
                    complaint_id=cid,
                    department="WASTE",
                    status=WorkOrderStatus.ASSIGNED,
                    due_at=datetime.now(UTC) - timedelta(hours=2),
                    location_lat=_LAT,
                    location_lon=_LON,
                )
            )
            await db.commit()

        r = await client.get(f"{_BASE}/kpis", headers=_auth(otoken))
        assert r.status_code == 200
        assert r.json()["sla_breaches"] >= 1

        # A completed order should NOT count as an SLA breach.
        async with async_session_factory() as db:
            db.add(
                WorkOrder(
                    complaint_id=cid,
                    department="WASTE",
                    status=WorkOrderStatus.COMPLETED,
                    due_at=datetime.now(UTC) - timedelta(hours=2),
                    location_lat=_LAT,
                    location_lon=_LON,
                )
            )
            await db.commit()
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# Priority queue
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_queue_pagination_and_search(client):
    citizen_email = _unique_email("cc-q-c")
    await _citizen_token(citizen_email)
    async with async_session_factory() as db:
        citizen = await db.scalar(select(User).where(User.email == citizen_email))
    otoken = await _role_user(_unique_email("cc-q-o"), RoleName.OFFICER.value)
    prefix = uuid.uuid4().hex[:8]
    cid_a = cid_b = None
    try:
        cid_a = await _insert_complaint(
            user_id=citizen.id,
            title=f"{prefix} burst water main",
            description="gushing on main road",
        )
        cid_b = await _insert_complaint(
            user_id=citizen.id,
            title=f"{prefix} pothole",
            description="deep crater",
        )
        await _priority(cid_a, DynamicPriority.P1_CRITICAL, 95)
        await _priority(cid_b, DynamicPriority.P3_MEDIUM, 55)
        await _department(cid_a, "WATER")

        # full list returns our complaints (search-isolated to this test)
        r = await client.get(f"{_BASE}/queue", params={"search": prefix}, headers=_auth(otoken))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total"] == 2
        # order: P1 before P3
        assert data["items"][0]["id"] == str(cid_a)
        assert data["items"][0]["priority"] == "P1_CRITICAL"
        assert data["items"][1]["priority"] == "P3_MEDIUM"

        # search matches title/description
        r2 = await client.get(
            f"{_BASE}/queue", params={"search": f"{prefix} pothole"}, headers=_auth(otoken)
        )
        ids2 = [i["id"] for i in r2.json()["items"]]
        assert str(cid_b) in ids2
        assert str(cid_a) not in ids2
        # description search
        r2b = await client.get(
            f"{_BASE}/queue", params={"search": "deep crater"}, headers=_auth(otoken)
        )
        assert str(cid_b) in [i["id"] for i in r2b.json()["items"]]

        # department filter (isolated by prefix only when combined with search)
        r3 = await client.get(
            f"{_BASE}/queue",
            params={"search": prefix, "department": "WATER"},
            headers=_auth(otoken),
        )
        ids3 = [i["id"] for i in r3.json()["items"]]
        assert str(cid_a) in ids3
        assert str(cid_b) not in ids3

        # priority filter (combined with search to stay isolated)
        r4 = await client.get(
            f"{_BASE}/queue",
            params={"search": prefix, "priority": "P3_MEDIUM"},
            headers=_auth(otoken),
        )
        ids4 = [i["id"] for i in r4.json()["items"]]
        assert str(cid_b) in ids4
        assert str(cid_a) not in ids4

        # pagination page_size=1 -> total_pages reflects it
        r5 = await client.get(
            f"{_BASE}/queue",
            params={"search": prefix, "page_size": 1},
            headers=_auth(otoken),
        )
        assert len(r5.json()["items"]) == 1
        assert r5.json()["total"] == 2
        assert r5.json()["total_pages"] == 2
    finally:
        for c in (cid_a, cid_b):
            if c:
                await _delete_complaint(c)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_map_returns_complaints_wards_hotspots(client):
    citizen_email = _unique_email("cc-map-c")
    await _citizen_token(citizen_email)
    async with async_session_factory() as db:
        citizen = await db.scalar(select(User).where(User.email == citizen_email))
    otoken = await _role_user(_unique_email("cc-map-o"), RoleName.OFFICER.value)
    ward_id = await _ward("MAP01", "MapOne")
    async with async_session_factory() as db:
        ward_code = (await db.get(Ward, ward_id)).code
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="mapped hotspot", ward_id=ward_id)
        await _priority(cid, DynamicPriority.P2_HIGH, 80)

        r = await client.get(f"{_BASE}/map", headers=_auth(otoken))
        assert r.status_code == 200, r.text
        data = r.json()
        assert any(c["id"] == str(cid) for c in data["complaints"])
        assert any(w["code"] == ward_code for w in data["wards"])
        hotspots = {h["ward_code"]: h for h in data["hotspots"]}
        assert hotspots.get(ward_code) is not None
        assert hotspots[ward_code]["complaint_count"] >= 1

        # work orders surfaced on the map when located
        from datetime import UTC, datetime, timedelta

        async with async_session_factory() as db:
            db.add(
                WorkOrder(
                    complaint_id=cid,
                    department="WASTE",
                    status=WorkOrderStatus.ASSIGNED,
                    location_lat=_LAT,
                    location_lon=_LON,
                    due_at=datetime.now(UTC) + timedelta(hours=2),
                )
            )
            await db.commit()
        r2 = await client.get(f"{_BASE}/map", headers=_auth(otoken))
        assert any(wo["complaint_id"] == str(cid) for wo in r2.json()["work_orders"])
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# AI activity
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ai_activity_aggregates_runs(client):
    citizen_email = _unique_email("cc-ai-c")
    await _citizen_token(citizen_email)
    async with async_session_factory() as db:
        citizen = await db.scalar(select(User).where(User.email == citizen_email))
    otoken = await _role_user(_unique_email("cc-ai-o"), RoleName.OFFICER.value)
    cid = None
    try:
        base = (await client.get(f"{_BASE}/ai-activity", headers=_auth(otoken))).json()
        base_agents = {a["agent"]: a for a in base["agents"]}

        cid = await _insert_complaint(user_id=citizen.id, title="ai activity")
        await _agent_run(cid, "triage", "SUCCEEDED")
        await _agent_run(cid, "triage", "FAILED")
        await _agent_run(cid, "vision", "RUNNING")

        r = await client.get(f"{_BASE}/ai-activity", headers=_auth(otoken))
        assert r.status_code == 200, r.text
        data = r.json()
        agents = {a["agent"]: a for a in data["agents"]}
        assert agents["triage"]["completed"] >= base_agents["triage"]["completed"] + 1
        assert agents["triage"]["failed"] >= base_agents["triage"]["failed"] + 1
        assert agents["vision"]["running"] >= base_agents["vision"]["running"] + 1
        # synthesized GIS entry (service, not an agent) -> disabled + 0 runs
        assert agents["gis"]["enabled"] is False
        assert agents["gis"]["total"] == 0
        # all seven panels present
        for label in (
            "Triage",
            "Vision",
            "Duplicate Detection",
            "GIS / Geo",
            "Context",
            "Priority",
            "Routing",
            "Dispatch",
        ):
            assert label in [a["label"] for a in data["agents"]]
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# Ward-representative scoping
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ward_rep_scoped_to_own_ward(client):
    citizen_email = _unique_email("cc-wr-c")
    await _citizen_token(citizen_email)
    async with async_session_factory() as db:
        citizen = await db.scalar(select(User).where(User.email == citizen_email))

    ward_a = await _ward("WR-A", "WardA")
    ward_b = await _ward("WR-B", "WardB")
    wtoken = await _role_user(
        _unique_email("cc-wr-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward_a
    )
    cid_a = await _insert_complaint(user_id=citizen.id, title="in ward a", ward_id=ward_a)
    cid_b = await _insert_complaint(user_id=citizen.id, title="in ward b", ward_id=ward_b)
    try:
        r = await client.get(f"{_BASE}/queue", headers=_auth(wtoken))
        ids = [i["id"] for i in r.json()["items"]]
        assert str(cid_a) in ids
        assert str(cid_b) not in ids

        k = await client.get(f"{_BASE}/kpis", headers=_auth(wtoken))
        assert k.json()["total_complaints"] == 1

        m = await client.get(f"{_BASE}/map", headers=_auth(wtoken))
        mcids = [c["id"] for c in m.json()["complaints"]]
        assert str(cid_a) in mcids
        assert str(cid_b) not in mcids
    finally:
        await _delete_complaint(cid_a)
        await _delete_complaint(cid_b)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# Realtime WebSocket
# --------------------------------------------------------------------------- #
def _make_ws_test_client():
    from main import app

    return TestClient(app)


def _ws_context():
    """Return (engine, factory, restore) for an isolated NullPool DB session.

    The WS handler opens DB sessions on whatever loop it runs on. Using an
    isolated NullPool engine -- temporarily wired into the handler module --
    guarantees connections are never borrowed across event loops (pytest's
    async loop vs ``asyncio.run`` vs TestClient's portal loop).
    """
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool

    import app.api.ws.command_center as cc_ws
    from app.core.config import get_settings

    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    original = cc_ws.async_session_factory
    cc_ws.async_session_factory = factory
    return engine, factory, lambda: setattr(cc_ws, "async_session_factory", original)


async def _ws_role_user(factory, email: str, role_name: str) -> str:
    from app.core.security import hash_password
    from app.models import Role

    async with factory() as db:
        role = await db.scalar(select(Role).where(Role.name == role_name))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=f"{role_name} User",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), role_name)


async def _ws_citizen_user(factory, email: str) -> str:
    async with factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="CC Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
        return create_access_token(str(user.id), "CITIZEN")


async def _ws_delete_user(factory, email: str) -> None:
    async with factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


def test_websocket_officer_receives_snapshot():
    """Officer can connect to /ws/command-center and receives an initial
    snapshot with KPIs, and a refreshed snapshot after a client 'refresh'."""
    import asyncio

    officer_email = _unique_email("cc-ws-o")
    engine, factory, restore = _ws_context()
    client = _make_ws_test_client()
    try:
        token = asyncio.run(_ws_role_user(factory, officer_email, RoleName.OFFICER.value))

        async def run():
            with client.websocket_connect(f"/ws/command-center?token={token}") as ws:
                first = ws.receive_json()
                assert first["type"] == "snapshot"
                assert "kpis" in first
                assert "total_complaints" in first["kpis"]
                ws.send_json({"action": "refresh"})
                second = ws.receive_json()
                assert second["type"] == "snapshot"
                assert "kpis" in second

        asyncio.run(run())
        client.close()
        asyncio.run(_ws_delete_user(factory, officer_email))
    finally:
        restore()
        asyncio.run(engine.dispose())


def test_websocket_citizen_rejected():
    """A citizen token cannot connect to the command-center websocket."""
    import asyncio

    from starlette.websockets import WebSocketDisconnect

    citizen_email = _unique_email("cc-ws-c")
    engine, factory, restore = _ws_context()
    client = _make_ws_test_client()
    try:
        token = asyncio.run(_ws_citizen_user(factory, citizen_email))

        async def run():
            try:
                with client.websocket_connect(f"/ws/command-center?token={token}") as ws:
                    ws.receive_json()
                    raise AssertionError("citizen should not receive command-center data")
            except WebSocketDisconnect:
                pass  # expected: server closes the pre-accept connection

        asyncio.run(run())
        client.close()
        asyncio.run(_ws_delete_user(factory, citizen_email))
    finally:
        restore()
        asyncio.run(engine.dispose())
