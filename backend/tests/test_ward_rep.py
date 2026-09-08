"""Tests for the Ward Representative Portal (Part 16).

Layers exercised:

* **Dashboard** — ward identity, representative identity, and ward-scoped KPIs
  (total / open / critical / resolved / SLA breaches). The representative's
  numbers reflect only their own ward, not the whole city.
* **Map** — the representative's complaints (with dynamic priority bucket) and
  their work orders, scoped to the assigned ward.
* **AI ward summary** — returns a factual summary; when no Groq key is
  configured it falls back to a deterministic synthesis still grounded in the
  ward's real records (``generated_by == "synthesized"``).
* **Wrong ward** — a representative cannot read/action a complaint that belongs
  to a different ward (403).
* **Empty ward** — a representative of a ward with no complaints sees zeroed KPI
  and an empty map without error.
* **Large dataset** — a ward with many complaints is aggregated correctly.
* **Escalation** — a representative can request an escalation (status ->
  ESCALATED with a status-history note) and cannot escalate an already-resolved
  complaint.
* **Conversations** — a representative can send an update on a complaint thread
  and read it back; access is denied for other wards.
* **Permissions** — citizens are forbidden from every portal endpoint while
  OFFICER / ADMIN are allowed.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    Complaint,
    ComplaintCorrelation,
    ComplaintDepartmentHistory,
    ComplaintLocation,
    ComplaintPriorityHistory,
    Conversation,
    Message,
    Role,
    User,
    UserProfile,
    Ward,
    WorkOrder,
)
from app.models.enums import (
    ComplaintCategory,
    ComplaintStatus,
    CorrelationMatchStatus,
    DynamicPriority,
    RoleName,
    WorkOrderStatus,
)
from app.schemas.auth import RegisterIn
from app.services import auth_service

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/ward-rep"
_SETTINGS = get_settings()
_LAT = 17.4327
_LON = 78.3885


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_user(email: str) -> User:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db, RegisterIn(email=email, password=_PASSWORD, full_name="WR Citizen")
        )
        return await db.scalar(select(User).where(User.email == email))


async def _role_token(email: str, role_name: str, *, ward_id=None) -> str:
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


async def _ward(code: str, name: str | None = None) -> Ward:
    token = uuid.uuid4().hex[:6]
    wname = name or code
    async with async_session_factory() as db:
        ward = Ward(code=f"{code}-{token}", name=f"{wname}-{token}", description=f"ward {code}")
        db.add(ward)
        await db.commit()
        return await db.get(Ward, ward.id)


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


async def _message(complaint_id: uuid.UUID, author_id: uuid.UUID, role: str, body: str):
    async with async_session_factory() as db:
        conv = await db.scalar(
            select(Conversation).where(Conversation.complaint_id == complaint_id)
        )
        if conv is None:
            conv = Conversation(complaint_id=complaint_id)
            db.add(conv)
            await db.flush()
        db.add(
            Message(
                conversation_id=conv.id,
                complaint_id=complaint_id,
                author_id=author_id,
                role=role,
                body=body,
            )
        )
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
# Permissions / RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_requires_auth(client):
    r = await client.get(f"{_BASE}/dashboard")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_citizen_forbidden_on_all_endpoints(client):
    email = _unique_email("wr-citizen")
    user = await _citizen_user(email)
    token = create_access_token(str(user.id), RoleName.CITIZEN.value)
    paths = [
        "/dashboard",
        "/map",
        "/summary",
        f"/complaints/{uuid.uuid4()}/conversation",
        f"/complaints/{uuid.uuid4()}/cluster",
    ]
    try:
        for path in paths:
            r = await client.get(f"{_BASE}{path}", headers=_auth(token))
            assert r.status_code == 403, (path, r.status_code)
    finally:
        await _delete_user(email)


@pytest.mark.asyncio
async def test_officer_and_admin_allowed(client):
    for role in (RoleName.OFFICER.value, RoleName.ADMIN.value):
        email = _unique_email(f"wr-{role.lower()}")
        token = await _role_token(email, role)
        try:
            r = await client.get(f"{_BASE}/dashboard", headers=_auth(token))
            assert r.status_code == 200, (role, r.status_code)
        finally:
            await _delete_user(email)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dashboard_scoped_to_own_ward(client):
    citizen_email = _unique_email("wr-dash-c")
    citizen = await _citizen_user(citizen_email)

    ward_a = await _ward("WRA", "WardA")
    ward_b = await _ward("WRB", "WardB")
    wtoken = await _role_token(
        _unique_email("wr-dash-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward_a.id
    )
    cid_a1 = None
    cid_a2 = None
    cid_b = None
    try:
        cid_a1 = await _insert_complaint(
            user_id=citizen.id,
            title="ward a open",
            ward_id=ward_a.id,
            status=ComplaintStatus.SUBMITTED,
        )
        cid_a2 = await _insert_complaint(
            user_id=citizen.id,
            title="ward a resolved",
            ward_id=ward_a.id,
            status=ComplaintStatus.RESOLVED,
        )
        cid_b = await _insert_complaint(
            user_id=citizen.id,
            title="ward b",
            ward_id=ward_b.id,
        )
        await _priority(cid_a1, DynamicPriority.P1_CRITICAL, 95)
        await _priority(cid_b, DynamicPriority.P1_CRITICAL, 95)

        r = await client.get(f"{_BASE}/dashboard", headers=_auth(wtoken))
        assert r.status_code == 200, r.text
        data = r.json()
        # Ward identity
        assert data["ward"]["name"] == ward_a.name
        assert data["ward"]["code"] == ward_a.code
        # KPIs reflect ONLY ward A, NOT ward B
        assert data["kpis"]["total_complaints"] == 2
        assert data["kpis"]["open"] == 1
        assert data["kpis"]["resolved"] == 1
        assert data["kpis"]["critical"] == 1  # ward A's P1, not ward B's
    finally:
        for c in (cid_a1, cid_a2, cid_b):
            if c:
                await _delete_complaint(c)
        await _delete_user(citizen_email)


@pytest.mark.asyncio
async def test_dashboard_sla_breach_in_ward(client):
    citizen_email = _unique_email("wr-sla-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("WR-SLA", "SlaWard")
    wtoken = await _role_token(
        _unique_email("wr-sla-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cid = None
    try:
        cid = await _insert_complaint(
            user_id=citizen.id,
            title="sla ward",
            ward_id=ward.id,
            status=ComplaintStatus.IN_PROGRESS,
        )
        async with async_session_factory() as db:
            db.add(
                WorkOrder(
                    complaint_id=cid,
                    department="WASTE",
                    status=WorkOrderStatus.ASSIGNED,
                    due_at=datetime.now(UTC) - timedelta(hours=3),
                    location_lat=_LAT,
                    location_lon=_LON,
                )
            )
            await db.commit()

        r = await client.get(f"{_BASE}/dashboard", headers=_auth(wtoken))
        assert r.status_code == 200
        assert r.json()["kpis"]["sla_breaches"] == 1
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


@pytest.mark.asyncio
async def test_empty_ward_dashboard_and_map(client):
    ward = await _ward("WR-EMPTY", "EmptyWard")
    wtoken = await _role_token(
        _unique_email("wr-empty-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    try:
        r = await client.get(f"{_BASE}/dashboard", headers=_auth(wtoken))
        assert r.status_code == 200
        data = r.json()
        assert data["kpis"]["total_complaints"] == 0
        assert data["kpis"]["open"] == 0
        assert data["kpis"]["critical"] == 0
        assert data["kpis"]["resolved"] == 0

        m = await client.get(f"{_BASE}/map", headers=_auth(wtoken))
        assert m.status_code == 200
        assert m.json()["complaints"] == []
        assert m.json()["work_orders"] == []

        s = await client.get(f"{_BASE}/summary", headers=_auth(wtoken))
        assert s.status_code == 200
        assert s.json()["complaint_count"] == 0
    finally:
        # no complaint to clean up; user only
        pass


# --------------------------------------------------------------------------- #
# Large dataset
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_large_dataset_aggregation(client):
    citizen_email = _unique_email("wr-big-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("WR-BIG", "BigWard")
    wtoken = await _role_token(
        _unique_email("wr-big-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cids = []
    try:
        statuses = [
            ComplaintStatus.SUBMITTED,
            ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.RESOLVED,
        ]
        for i in range(30):
            st = statuses[i % 3]
            cid = await _insert_complaint(
                user_id=citizen.id, title=f"bulk {i}", ward_id=ward.id, status=st
            )
            cids.append(cid)
            bucket = [
                DynamicPriority.P1_CRITICAL,
                DynamicPriority.P2_HIGH,
                DynamicPriority.P3_MEDIUM,
                DynamicPriority.P4_LOW,
            ][i % 4]
            await _priority(cid, bucket, score=100 - i)

        r = await client.get(f"{_BASE}/dashboard", headers=_auth(wtoken))
        assert r.status_code == 200
        k = r.json()["kpis"]
        assert k["total_complaints"] == 30
        assert k["resolved"] == 10
        assert k["critical"] == 8  # 30 % 4 -> indices 0,4,... P1 (every 4th, 8 total)

        m = await client.get(f"{_BASE}/map", headers=_auth(wtoken))
        assert m.status_code == 200
        assert len(m.json()["complaints"]) == 30
    finally:
        for c in cids:
            await _delete_complaint(c)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_map_returns_ward_complaints_with_priority(client):
    citizen_email = _unique_email("wr-map-c")
    citizen = await _citizen_user(citizen_email)
    ward_a = await _ward("WR-MAP-A", "MapA")
    ward_b = await _ward("WR-MAP-B", "MapB")
    wtoken = await _role_token(
        _unique_email("wr-map-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward_a.id
    )
    cid_a = cid_b = None
    try:
        cid_a = await _insert_complaint(user_id=citizen.id, title="map a", ward_id=ward_a.id)
        cid_b = await _insert_complaint(user_id=citizen.id, title="map b", ward_id=ward_b.id)
        await _priority(cid_a, DynamicPriority.P2_HIGH, 80)
        await _department(cid_a, "WATER")
        await _priority(cid_b, DynamicPriority.P3_MEDIUM, 50)

        r = await client.get(f"{_BASE}/map", headers=_auth(wtoken))
        assert r.status_code == 200
        data = r.json()
        ids = [c["id"] for c in data["complaints"]]
        assert str(cid_a) in ids
        assert str(cid_b) not in ids
        by_id = {c["id"]: c for c in data["complaints"]}
        assert by_id[str(cid_a)]["priority"] == "P2_HIGH"
        assert by_id[str(cid_a)]["department"] == "WATER"

        # Work order surfaced
        async with async_session_factory() as db:
            db.add(
                WorkOrder(
                    complaint_id=cid_a,
                    department="WATER",
                    status=WorkOrderStatus.ASSIGNED,
                    location_lat=_LAT,
                    location_lon=_LON,
                    due_at=datetime.now(UTC) + timedelta(hours=2),
                )
            )
            await db.commit()
        r2 = await client.get(f"{_BASE}/map", headers=_auth(wtoken))
        wos = [w["complaint_id"] for w in r2.json()["work_orders"]]
        assert str(cid_a) in wos
    finally:
        for c in (cid_a, cid_b):
            if c:
                await _delete_complaint(c)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# AI ward summary
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ward_summary_endpoint(client):
    """The endpoint returns a factual, non-empty summary grounded in the ward.

    ``generated_by`` may be ``groq`` (live LLM, when a key is configured) or
    ``synthesized`` (deterministic fallback); both must reference the real ward
    complaint count.
    """
    citizen_email = _unique_email("wr-sum-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("WR-SUM", "SumWard")
    wtoken = await _role_token(
        _unique_email("wr-sum-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="leaking main", ward_id=ward.id)
        await _priority(cid, DynamicPriority.P1_CRITICAL, 96)

        r = await client.get(f"{_BASE}/summary", headers=_auth(wtoken))
        assert r.status_code == 200
        data = r.json()
        assert data["generated_by"] in ("groq", "synthesized")
        assert data["complaint_count"] == 1
        assert data["summary"]
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


@pytest.mark.asyncio
async def test_ward_summary_synthesized_path_when_groq_unavailable():
    """The deterministic fallback is factual when no Groq key is configured."""
    from app.services import ward_rep_service

    class _NoKeyAI:
        is_configured = False

        async def chat_completion(self, *args, **kwargs):
            raise AssertionError("should not call Groq when not configured")

    citizen = await _citizen_user(_unique_email("wr-synth-c"))
    ward = await _ward("WR-SYNTH", "SynthWard")
    rep_email = _unique_email("wr-synth-w")
    cid = None
    try:
        async with async_session_factory() as db:
            role = await db.scalar(
                select(Role).where(Role.name == RoleName.WARD_REPRESENTATIVE.value)
            )
            rep = User(
                email=rep_email,
                password_hash=hash_password(_PASSWORD),
                full_name="WR Synth",
                role_id=role.id,
                ward_id=ward.id,
                is_active=True,
                is_email_verified=True,
            )
            db.add(rep)
            await db.flush()
            db.add(UserProfile(user_id=rep.id))
            await db.commit()
            rep = await db.get(User, rep.id)

        cid = await _insert_complaint(
            user_id=citizen.id,
            title="burst pipe",
            ward_id=ward.id,
            status=ComplaintStatus.SUBMITTED,
        )
        await _priority(cid, DynamicPriority.P2_HIGH, 70)

        async with async_session_factory() as db:
            res = await ward_rep_service.get_ward_summary(db, rep, ai=_NoKeyAI())

        assert res.generated_by == "synthesized"
        assert res.complaint_count == 1
        assert "1" in res.summary
        assert res.highlights
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen.email)
        await _delete_user(rep_email)


# --------------------------------------------------------------------------- #
# Conversations
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_conversation_send_and_read_scoped(client):
    citizen_email = _unique_email("wr-conv-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("WR-CONV", "ConvWard")
    other_ward = await _ward("WR-CONV2", "OtherWard")
    wtoken = await _role_token(
        _unique_email("wr-conv-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    other_token = await _role_token(
        _unique_email("wr-conv-o"), RoleName.WARD_REPRESENTATIVE.value, ward_id=other_ward.id
    )
    cid = None
    try:
        cid = await _insert_complaint(
            user_id=citizen.id, title="conversation base", ward_id=ward.id
        )
        # Citizen opened the thread.
        await _message(cid, citizen.id, "CITIZEN", "Please look at the water leak.")

        # Representative reads the (authorized) conversation.
        r = await client.get(f"{_BASE}/complaints/{cid}/conversation", headers=_auth(wtoken))
        assert r.status_code == 200, r.text
        msgs = r.json()["messages"]
        assert len(msgs) == 1
        assert msgs[0]["role"] == "CITIZEN"
        assert msgs[0]["body"] == "Please look at the water leak."

        # Representative sends an update.
        r2 = await client.post(
            f"{_BASE}/complaints/{cid}/send-update",
            json={"body": "We have dispatched a team."},
            headers=_auth(wtoken),
        )
        assert r2.status_code == 200, r2.text
        msgs = r2.json()["messages"]
        assert len(msgs) == 2
        assert msgs[1]["role"] == "WARD_REPRESENTATIVE"
        assert msgs[1]["body"] == "We have dispatched a team."

        # A representative of a DIFFERENT ward cannot access the conversation.
        r3 = await client.get(f"{_BASE}/complaints/{cid}/conversation", headers=_auth(other_token))
        assert r3.status_code == 403
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# Escalation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_escalation_request_and_state_guard(client):
    citizen_email = _unique_email("wr-esc-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("WR-ESC", "EscWard")
    wtoken = await _role_token(
        _unique_email("wr-esc-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cid = resolved_cid = None
    try:
        cid = await _insert_complaint(
            user_id=citizen.id,
            title="escalate me",
            ward_id=ward.id,
            status=ComplaintStatus.IN_PROGRESS,
        )
        r = await client.post(
            f"{_BASE}/complaints/{cid}/escalate",
            json={"body": "No water for 3 days, needs urgent attention."},
            headers=_auth(wtoken),
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "ESCALATED"
        assert "urgent" in data["note"]

        # The status transition was recorded in the timeline.
        async with async_session_factory() as db:
            complaint = await db.get(Complaint, cid)
            assert complaint.status == ComplaintStatus.ESCALATED

        # Cannot escalate an already-resolved complaint.
        resolved_cid = await _insert_complaint(
            user_id=citizen.id,
            title="already done",
            ward_id=ward.id,
            status=ComplaintStatus.RESOLVED,
        )
        r2 = await client.post(
            f"{_BASE}/complaints/{resolved_cid}/escalate",
            json={"body": "nope"},
            headers=_auth(wtoken),
        )
        assert r2.status_code == 400

        # Wrong-ward escalation is forbidden (403), not escalated.
        other_ward = await _ward("WR-ESC2", "EscOther")
        cid_other = await _insert_complaint(
            user_id=citizen.id,
            title="other ward",
            ward_id=other_ward.id,
        )
        r3 = await client.post(
            f"{_BASE}/complaints/{cid_other}/escalate",
            json={"body": "x"},
            headers=_auth(wtoken),
        )
        assert r3.status_code == 403
        await _delete_complaint(cid_other)
    finally:
        for c in (cid, resolved_cid):
            if c:
                await _delete_complaint(c)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# Work order view + cluster
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_work_order_view_and_cluster(client):
    citizen_email = _unique_email("wr-woc-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("WR-WOC", "WocWard")
    wtoken = await _role_token(
        _unique_email("wr-woc-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cid = related = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="work order base", ward_id=ward.id)
        async with async_session_factory() as db:
            db.add(
                WorkOrder(
                    complaint_id=cid,
                    department="WASTE",
                    status=WorkOrderStatus.ASSIGNED,
                    incident="work order base",
                    priority="P1_CRITICAL",
                    location_lat=_LAT,
                    location_lon=_LON,
                    due_at=datetime.now(UTC) + timedelta(hours=6),
                )
            )
            await db.commit()

        r = await client.get(f"{_BASE}/complaints/{cid}/work-order", headers=_auth(wtoken))
        assert r.status_code == 200, r.text
        wo = r.json()
        assert wo["complaint_id"] == str(cid)
        assert wo["department"] == "WASTE"
        assert wo["status"] == "ASSIGNED"

        # Cluster: a correlated duplicate.
        related = await _insert_complaint(
            user_id=citizen.id, title="same issue reported again", ward_id=ward.id
        )
        async with async_session_factory() as db:
            db.add(
                ComplaintCorrelation(
                    source_complaint_id=related,
                    target_complaint_id=cid,
                    similarity=0.92,
                    distance_m=120.0,
                    time_diff_hours=3.0,
                    category_match=True,
                    score=0.9,
                    reason="same location and category",
                    status=CorrelationMatchStatus.CONFIRMED,
                )
            )
            await db.commit()

        rc = await client.get(f"{_BASE}/complaints/{cid}/cluster", headers=_auth(wtoken))
        assert rc.status_code == 200, rc.text
        cluster = rc.json()
        assert cluster["base_complaint_id"] == str(cid)
        members = {m["id"] for m in cluster["members"]}
        assert str(related) in members
        member = next(m for m in cluster["members"] if m["id"] == str(related))
        assert member["similarity"] == 0.92
        assert member["correlation_status"] == "CONFIRMED_DUPLICATE"

        # Wrong-ward cluster access is forbidden.
        other_ward = await _ward("WR-WOC2", "OtherWoc")
        cid_other = await _insert_complaint(
            user_id=citizen.id, title="other", ward_id=other_ward.id
        )
        rbad = await client.get(f"{_BASE}/complaints/{cid_other}/cluster", headers=_auth(wtoken))
        assert rbad.status_code == 403
        await _delete_complaint(cid_other)
    finally:
        for c in (cid, related):
            if c:
                await _delete_complaint(c)
        await _delete_user(citizen_email)
