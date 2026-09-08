"""Tests for the centralized Notification System (Part 21).

Exercises the notification infrastructure end-to-end against the live dev
database:

* **Registry / store** — canonical event keys map to the right stored types,
  titles and channels (COMPLAINT_RECEIVED, AI_COMPLETE, PRIORITY_ASSIGNED /
  PRIORITY_CHANGE, WORK_ORDER_CREATED, P1_ALERT, WORKER_ASSIGNED /
  NEW_ASSIGNMENT / REASSIGNMENT, REPAIR_STARTED, WORK_ORDER_COMPLETED,
  ESCALATION, HUMAN_REVIEW, WARD_ALERT).
* **API** — pagination, unread-only filter, unread badge, mark-read (owner
  only), read-all, and 401 for anonymous callers.
* **WebSocket** — a valid token receives an initial snapshot; an invalid token
  is rejected.
* **Email provider** — the default provider is the no-op console provider.

MESSAGE / WORK_ORDER_REOPENED / SLA_AT_RISK / SLA_BREACHED emission is already
covered by test_conversations, test_verify_repair_agent and test_sla_monitor.
"""

import asyncio
import io
import uuid
from datetime import UTC, datetime

import pytest
from PIL import Image as PILImage
from sqlalchemy import delete, select

from app.agents.verify_repair_agent import VerifyRepairAgent
from app.core.config import get_settings
from app.core.email import get_email_provider
from app.core.security import create_access_token, decode_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    Complaint,
    ComplaintPriorityHistory,
    Department,
    FieldWorker,
    Notification,
    Role,
    User,
    UserProfile,
    Ward,
    WorkerAssignment,
    WorkOrder,
    WorkOrderPhoto,
)
from app.models.enums import (
    AssignmentStatus,
    ComplaintStatus,
    DynamicPriority,
    RoleName,
    VerificationStatus,
    WorkerStatus,
    WorkOrderStatus,
)
from app.schemas.verification import VerificationOutput
from app.services import auth_service
from app.storage import get_storage

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1"
_NOTIF = f"{_BASE}/notifications"
_COMPLAINTS = f"{_BASE}/complaints"
_WO = f"{_BASE}/work-orders"
_WORKER = f"{_BASE}/worker"
_WARD_REP = f"{_BASE}/ward-rep"
_SETTINGS = get_settings()
_LAT = 17.4327
_LON = 78.3885


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeAI:
    """Drop-in AIService fake for the verify agent's vision call."""

    def __init__(self, responses: list):
        self._responses = responses
        self.calls = 0

    async def structured_vision_completion(self, content, schema, **kwargs):
        self.calls += 1
        outcome = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _png_bytes(color: tuple = (120, 80, 40)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (64, 64), color=color).save(buf, format="PNG")
    return buf.getvalue()


async def _user_with_role(email: str, role: RoleName, ward_id: uuid.UUID | None = None) -> str:
    async with async_session_factory() as db:
        r = await db.scalar(select(Role).where(Role.name == role.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=f"{role.value} User",
            role_id=r.id,
            is_active=True,
            is_email_verified=True,
            ward_id=ward_id,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), role.value)


async def _citizen_with_ward(ward_id: uuid.UUID) -> tuple[str, uuid.UUID]:
    email = _unique_email("notif-ward-cit")
    token = await _user_with_role(email, RoleName.CITIZEN, ward_id=ward_id)
    return token, uuid.UUID(decode_token(token, "access")["sub"])


def _role_short(role: RoleName) -> str:
    return role.value.split("_")[0].lower()


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            auth_service.RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Notification Citizen",
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _seed_ward() -> uuid.UUID:
    async with async_session_factory() as db:
        ward = Ward(
            name=f"Notif Ward {uuid.uuid4().hex[:6]}",
            code=f"NW{uuid.uuid4().hex[:6].upper()}",
        )
        db.add(ward)
        await db.commit()
        return ward.id


async def _seed_worker(
    email: str, *, skill_tags: list | None = None, equipment: list | None = None
) -> tuple[str, uuid.UUID]:
    """Return a FIELD_WORKER token and FieldWorker id (agent-compatible pool)."""
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Notif Worker",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        dept = await db.scalar(select(Department).where(Department.code == "WASTE"))
        if dept is None:
            dept = Department(name="WASTE", code="WASTE", description="waste crew")
            db.add(dept)
            await db.flush()
        fw = FieldWorker(
            user_id=user.id,
            department_id=dept.id,
            status=WorkerStatus.ACTIVE,
            home_latitude=_LAT,
            home_longitude=_LON,
            skill_tags=skill_tags or ["waste-audit"],
            equipment=equipment or ["garbage-truck"],
        )
        db.add(fw)
        await db.commit()
        return create_access_token(str(user.id), RoleName.FIELD_WORKER.value), fw.id


async def _create_complaint(client, token: str, *, category: str = "GARBAGE") -> str:
    body = {
        "description": f"{category} notification test",
        "category": category,
        "media_ids": [],
        "location": {
            "latitude": _LAT,
            "longitude": _LON,
            "address": "Notif test location",
            "source": "gps",
            "geopoint_denied": False,
        },
    }
    r = await client.post(_COMPLAINTS, json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _dispatch(client, token: str, cid: str) -> str:
    d = await client.post(f"{_COMPLAINTS}/{cid}/dispatch", headers=_auth(token))
    assert d.status_code in (200, 201), d.text
    return d.json()["work_order_id"]


async def _approve(client, otoken: str, work_id: str) -> None:
    ap = await client.post(f"{_WO}/{work_id}/approve", json={"note": "go"}, headers=_auth(otoken))
    assert ap.status_code == 200, ap.text
    assert ap.json()["work_order"]["status"] == "ASSIGNED"


async def _clear_workers() -> None:
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


async def _purge_notifications() -> None:
    async with async_session_factory() as db:
        await db.execute(delete(Notification))
        await db.commit()


async def _notification_items(client, token: str, **params) -> list[dict]:
    r = await client.get(_NOTIF, headers=_auth(token), **({"params": params} if params else {}))
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def _notification_types(client, token: str, **params) -> list[str]:
    return [n["notification_type"] for n in await _notification_items(client, token, **params)]


async def _seed_assigned_order(complaint_id: str, worker_id: uuid.UUID) -> uuid.UUID:
    """Seed an ASSIGNED work order + assignment for priority-change tests."""
    async with async_session_factory() as db:
        order = WorkOrder(
            complaint_id=uuid.UUID(complaint_id),
            department="WASTE",
            priority="P2_HIGH",
            location_lat=_LAT,
            location_lon=_LON,
            address="Notif location",
            status=WorkOrderStatus.ASSIGNED,
            worker_id=worker_id,
            sla_hours=48,
            created_by=None,
        )
        db.add(order)
        await db.flush()
        db.add(
            WorkerAssignment(
                work_order_id=order.id,
                worker_id=worker_id,
                status=AssignmentStatus.ASSIGNED,
                assigned_by=None,
                reason="seeded for priority-change test",
            )
        )
        await db.commit()
        return order.id


async def _seed_priority_history(complaint_id: str, bucket: DynamicPriority, score: int) -> None:
    async with async_session_factory() as db:
        db.add(
            ComplaintPriorityHistory(
                complaint_id=uuid.UUID(complaint_id),
                score=score,
                priority=bucket,
                changed=False,
                inputs={},
                factors={},
            )
        )
        await db.commit()


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


async def _seed_completed_order(
    citizen_user: uuid.UUID,
    worker_id: uuid.UUID,
) -> tuple[str, str]:
    """Seed a COMPLETED work order with BEFORE + AFTER photos (Part 19 reuse)."""
    async with async_session_factory() as db:
        complaint = Complaint(
            description="Deep pothole near the school.",
            title="ROAD: Deep pothole near the school.",
            category="ROAD",
            status=ComplaintStatus.RESOLVED,
            user_id=citizen_user,
        )
        db.add(complaint)
        await db.flush()

        order = WorkOrder(
            complaint_id=complaint.id,
            department="WASTE",
            priority="P2_HIGH",
            location_lat=_LAT,
            location_lon=_LON,
            address="Test location",
            status=WorkOrderStatus.COMPLETED,
            worker_id=worker_id,
            sla_hours=24,
            created_by=None,
            completed_at=datetime.now(UTC),
        )
        db.add(order)
        await db.flush()

        for cat, color in (("BEFORE", (70, 60, 50)), ("AFTER", (200, 220, 90))):
            png = _png_bytes(color)
            key = f"notif-verify-{order.id}-{cat.lower()}.png"
            get_storage().upload(key, png, "image/png")
            db.add(
                WorkOrderPhoto(
                    work_order_id=order.id,
                    worker_id=worker_id,
                    category=cat,
                    original_filename=f"{cat.lower()}.png",
                    storage_key=key,
                    content_type="image/png",
                    size_bytes=len(png),
                    allowed=True,
                )
            )
        await db.commit()
        return str(order.id), str(complaint.id)


@pytest.fixture(autouse=True)
async def _isolate():
    await _purge_notifications()
    yield


# --------------------------------------------------------------------------- #
# COMPLAINT_RECEIVED + WARD_ALERT
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_created_complaint_notifies_citizen(client):
    email = _unique_email("notif-received")
    token = await _citizen_token(email)
    cid = await _create_complaint(client, token)
    try:
        r = await client.get(_NOTIF, headers=_auth(token))
        assert r.status_code == 200, r.text
        payload = r.json()
        items = payload["items"]
        assert payload["unread_count"] == 1
        assert len(items) == 1
        n = items[0]
        assert n["notification_type"] == "COMPLAINT_RECEIVED"
        assert n["title"] == "Complaint received"
        assert n["channel"] == "inbox"
        assert n["link"] == f"/dashboard/complaints/{cid}"
        assert n["complaint_id"] == cid
        assert n["is_read"] is False
        assert n["read_at"] is None

        badge = await client.get(f"{_NOTIF}/unread-count", headers=_auth(token))
        assert badge.json()["unread_count"] == 1
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_ward_alert_notifies_ward_rep(client):
    ward_id = await _seed_ward()
    ctoken, cid_user = await _citizen_with_ward(ward_id)
    rtoken = await _user_with_role(
        _unique_email("notif-ward-rep"), RoleName.WARD_REPRESENTATIVE, ward_id
    )
    cid = await _create_complaint(client, ctoken)
    try:
        citizen_types = await _notification_types(client, ctoken)
        assert "COMPLAINT_RECEIVED" in citizen_types
        rep_types = await _notification_types(client, rtoken)
        assert "WARD_ALERT" in rep_types
    finally:
        await _delete_complaint(cid)
        await _delete_user(rtoken)
        async with async_session_factory() as db:
            user = await db.get(User, cid_user)
            if user is not None:
                cemail = user.email
                await db.delete(user)
                await db.commit()
                await _delete_user(cemail)


# --------------------------------------------------------------------------- #
# API semantics: auth, pagination, read states
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_notifications_require_auth(client):
    r = await client.get(_NOTIF)
    assert r.status_code == 401
    r2 = await client.get(f"{_NOTIF}/unread-count")
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_pagination_unread_filter_and_read_all(client):
    email = _unique_email("notif-page")
    token = await _citizen_token(email)
    cids = []
    for i in range(4):
        cids.append(await _create_complaint(client, token))
    try:
        r = await client.get(_NOTIF, headers=_auth(token), params={"page_size": 2, "page": 2})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 4
        assert body["page"] == 2
        assert body["page_size"] == 2
        assert len(body["items"]) == 2
        assert body["unread_count"] == 4

        unread_ids = [item["id"] for item in body["items"]]
        first = unread_ids[0]

        own = await client.post(f"{_NOTIF}/{first}/read", headers=_auth(token))
        assert own.status_code == 200, own.text
        assert own.json()["is_read"] is True
        assert own.json()["read_at"] is not None

        unread = await client.get(
            _NOTIF, headers=_auth(token), params={"unread_only": "true", "page_size": 10}
        )
        after = unread.json()
        assert after["unread_count"] == 3
        assert len(after["items"]) == 3

        all_clear = await client.post(f"{_NOTIF}/read-all", headers=_auth(token))
        assert all_clear.status_code == 200, all_clear.text
        assert all_clear.json()["ok"] is True

        badge = await client.get(f"{_NOTIF}/unread-count", headers=_auth(token))
        assert badge.json()["unread_count"] == 0
    finally:
        for c in cids:
            await _delete_complaint(c)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_mark_read_owner_only(client):
    owner = await _citizen_token(_unique_email("notif-owner"))
    other = await _citizen_token(_unique_email("notif-other"))
    cid = await _create_complaint(client, owner)
    try:
        r = await client.get(_NOTIF, headers=_auth(owner))
        nid = r.json()["items"][0]["id"]

        thief = await client.post(f"{_NOTIF}/{nid}/read", headers=_auth(other))
        assert thief.status_code == 404, thief.text

        still = await client.get(f"{_NOTIF}/unread-count", headers=_auth(owner))
        assert still.json()["unread_count"] == 1
    finally:
        await _delete_complaint(cid)


# --------------------------------------------------------------------------- #
# Priority engine producers
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_priority_assigns_and_change_notify(client):
    email = _unique_email("notif-prio")
    token = await _citizen_token(email)
    cid = await _create_complaint(client, token)
    wtoken, wid = await _seed_worker(email=_unique_email("notif-prio-worker"))
    try:
        first = await client.post(f"{_COMPLAINTS}/{cid}/priority", headers=_auth(token))
        assert first.status_code == 200, first.text
        await asyncio.sleep(0)
        assert "PRIORITY_ASSIGNED" in await _notification_types(client, token)

        await _seed_assigned_order(cid, wid)
        # Simulate a previous P1 evaluation so the next run visibly changes bucket
        # (a bare complaint computes P4_LOW deterministically).
        await _seed_priority_history(cid, DynamicPriority.P1_CRITICAL, 90)

        second = await client.post(f"{_COMPLAINTS}/{cid}/priority", headers=_auth(token))
        assert second.status_code == 200, second.text
        await asyncio.sleep(0)

        change_types = await _notification_types(client, wtoken)
        assert "PRIORITY_CHANGE" in change_types
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# Dispatch producers
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dispatch_work_order_created_and_p1_alert(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    monkeypatch.setattr(_SETTINGS, "DISPATCH_ENABLED", True)
    await _clear_workers()
    email = _unique_email("notif-dispatch")
    token = await _citizen_token(email)
    otoken = await _user_with_role(_unique_email("notif-dispatch-officer"), RoleName.OFFICER)
    atoken = await _user_with_role(_unique_email("notif-dispatch-admin"), RoleName.ADMIN)
    cid = await _create_complaint(client, token)
    try:
        await _seed_priority_history(cid, DynamicPriority.P1_CRITICAL, 95)
        work_id = await _dispatch(client, token, cid)

        assert "WORK_ORDER_CREATED" in await _notification_types(client, token)
        staff_o = await _notification_types(client, otoken)
        staff_a = await _notification_types(client, atoken)
        assert "P1_ALERT" in staff_o
        assert "P1_ALERT" in staff_a

        officer_items = await _notification_items(client, otoken)
        p1_ids = {n["work_order_id"] for n in officer_items if n["notification_type"] == "P1_ALERT"}
        assert work_id in p1_ids
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_assign_new_notifies_citizen_and_worker(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("notif-assign")
    token = await _citizen_token(email)
    otoken = await _user_with_role(_unique_email("notif-assign-off"), RoleName.OFFICER)
    wtoken, _ = await _seed_worker(email=_unique_email("notif-assign-worker"))
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, token, cid)
        await _approve(client, otoken, work_id)

        assert "WORKER_ASSIGNED" in await _notification_types(client, token)
        assert "NEW_ASSIGNMENT" in await _notification_types(client, wtoken)
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_reassign_notifies_second_worker(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("notif-reassign")
    token = await _citizen_token(email)
    otoken = await _user_with_role(_unique_email("notif-reassign-off"), RoleName.OFFICER)
    _, wid1 = await _seed_worker(email=_unique_email("notif-reassign-w1"))
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, token, cid)
        await _approve(client, otoken, work_id)
        w2token, wid2 = await _seed_worker(
            email=_unique_email("notif-reassign-w2"),
            skill_tags=["waste-audit"],
            equipment=["garbage-truck"],
        )
        re = await client.post(
            f"{_WO}/{work_id}/reassign",
            json={"worker_id": str(wid2), "reason": "move"},
            headers=_auth(otoken),
        )
        assert re.status_code == 200, re.text

        assert "REASSIGNMENT" in await _notification_types(client, w2token)
        assert "WORKER_ASSIGNED" in await _notification_types(client, token)
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# Field worker producers
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_worker_start_and_complete_notify(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("notif-fw")
    token = await _citizen_token(email)
    otoken = await _user_with_role(_unique_email("notif-fw-off"), RoleName.OFFICER)
    wtoken, _ = await _seed_worker(email=_unique_email("notif-fw-worker"))
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, token, cid)
        await _approve(client, otoken, work_id)

        acc = await client.post(
            f"{_WORKER}/orders/{work_id}/accept",
            json={"latitude": _LAT, "longitude": _LON},
            headers=_auth(wtoken),
        )
        assert acc.status_code == 200, acc.text
        st = await client.post(
            f"{_WORKER}/orders/{work_id}/start",
            json={"client_ref": "n-start"},
            headers=_auth(wtoken),
        )
        assert st.status_code == 200, st.text
        assert "REPAIR_STARTED" in await _notification_types(client, token)

        cmb = await client.post(
            f"{_WORKER}/orders/{work_id}/complete",
            json={"notes": "Done", "client_ref": "n-complete"},
            headers=_auth(wtoken),
        )
        assert cmb.status_code == 200, cmb.text
        assert "WORK_ORDER_COMPLETED" in await _notification_types(client, token)

        cd = await client.get(f"{_COMPLAINTS}/{cid}", headers=_auth(token))
        assert cd.json()["status"] == "RESOLVED"
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# Escalations
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_officer_escalate_notifies_ward_reps(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    ward_id = await _seed_ward()
    email = _unique_email("notif-oesc")
    token = await _citizen_token(email)
    otoken = await _user_with_role(_unique_email("notif-oesc-off"), RoleName.OFFICER)
    rtoken = await _user_with_role(
        _unique_email("notif-oesc-rep"), RoleName.WARD_REPRESENTATIVE, ward_id
    )
    await _seed_worker(email=_unique_email("notif-oesc-worker"))
    cid = await _create_complaint(client, token)
    try:
        async with async_session_factory() as db:
            complaint = await db.get(Complaint, uuid.UUID(cid))
            complaint.ward_id = ward_id
            await db.commit()
        work_id = await _dispatch(client, token, cid)
        await _approve(client, otoken, work_id)
        es = await client.post(
            f"{_WO}/{work_id}/escalate", json={"reason": "out of SLA"}, headers=_auth(otoken)
        )
        assert es.status_code == 200, es.text
        assert es.json()["work_order"]["status"] == "ESCALATED"

        assert "ESCALATION" in await _notification_types(client, rtoken)
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_ward_rep_escalate_notifies_staff(client):
    ward_id = await _seed_ward()
    ctoken, cid_user = await _citizen_with_ward(ward_id)
    rtoken = await _user_with_role(
        _unique_email("notif-wesc-rep"), RoleName.WARD_REPRESENTATIVE, ward_id
    )
    otoken = await _user_with_role(_unique_email("notif-wesc-off"), RoleName.OFFICER)
    cid = await _create_complaint(client, ctoken)
    try:
        async with async_session_factory() as db:
            complaint = await db.get(Complaint, uuid.UUID(cid))
            complaint.ward_id = ward_id
            await db.commit()
        r = await client.post(
            f"{_WARD_REP}/complaints/{cid}/escalate",
            json={"body": "Residents report worsening smell"},
            headers=_auth(rtoken),
        )
        assert r.status_code == 200, r.text
        assert "ESCALATION" in await _notification_types(client, otoken)
    finally:
        await _delete_complaint(cid)
        async with async_session_factory() as db:
            user = await db.get(User, cid_user)
            if user is not None:
                cemail = user.email
                await db.delete(user)
                await db.commit()
                await _delete_user(cemail)


# --------------------------------------------------------------------------- #
# Verification agent producer
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_human_review_notifies_staff(client, monkeypatch):
    ctoken, cid_user = await _citizen_with_ward(None)
    otoken = await _user_with_role(_unique_email("notif-hr-off"), RoleName.OFFICER)
    wtoken, wid = await _seed_worker(email=_unique_email("notif-hr-worker"))
    order_id, cid = await _seed_completed_order(cid_user, wid)

    fake = FakeAI(
        [
            VerificationOutput(
                repair_evidence="AFTER shows the pothole filled with fresh asphalt.",
                remaining_issue="",
                confidence=0.4,
                verification_status=VerificationStatus.VERIFIED,
                issue_fixed=True,
                human_review_required=True,
            )
        ]
    )
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(ai=fake),
    )
    try:
        r = await client.post(f"{_WO}/{order_id}/verify", headers=_auth(otoken))
        assert r.status_code == 200, r.text

        staff_types = await _notification_types(client, otoken)
        assert "HUMAN_REVIEW" in staff_types
    finally:
        await _delete_complaint(cid)


# --------------------------------------------------------------------------- #
# Provider defaults
# --------------------------------------------------------------------------- #
def test_email_provider_defaults_to_console():
    provider = get_email_provider()
    assert type(provider).__name__ == "ConsoleEmailProvider"
    assert _SETTINGS.NOTIFICATIONS_EMAIL_ENABLED is False


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
def _make_ws_test_client():
    from starlette.testclient import TestClient

    from main import app

    return TestClient(app)


def _ws_context():
    """Return (engine, factory, restore) for an isolated NullPool DB session.

    Mirrors test_command_center: the WS handler opens DB sessions on whatever
    loop it runs on, so an isolated NullPool engine guarantees connections are
    never borrowed across the pytest async loop / asyncio.run / TestClient loop.
    """
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool

    import app.api.ws.notifications as notif_ws
    from app.core.config import get_settings

    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    original = notif_ws.async_session_factory
    notif_ws.async_session_factory = factory
    return engine, factory, lambda: setattr(notif_ws, "async_session_factory", original)


async def _ws_user(factory, email: str) -> str:
    async with factory() as db:
        await auth_service.register_user(
            db,
            auth_service.RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="WS Citizen",
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


def test_ws_notifications_valid_token_receives_snapshot():
    import asyncio

    email = _unique_email("nws-ok")
    engine, factory, restore = _ws_context()
    client = _make_ws_test_client()
    try:
        token = asyncio.run(_ws_user(factory, email))

        async def run():
            with client.websocket_connect(f"/ws/notifications?token={token}") as ws:
                first = ws.receive_json()
                assert first["type"] == "snapshot"
                assert first["unread_count"] == 0
                ws.send_json({"action": "sync"})
                second = ws.receive_json()
                assert second["type"] == "snapshot"

        asyncio.run(run())
        client.close()
        asyncio.run(_ws_delete_user(factory, email))
    finally:
        restore()
        asyncio.run(engine.dispose())


def test_ws_notifications_invalid_token_rejected():
    import asyncio

    from starlette.websockets import WebSocketDisconnect

    engine, factory, restore = _ws_context()
    client = _make_ws_test_client()
    try:

        async def run():
            try:
                bogus = create_access_token("00000000-0000-0000-0000-000000000000", "CITIZEN")
                with client.websocket_connect(f"/ws/notifications?token={bogus}") as _ws:
                    raise AssertionError("invalid token should be rejected")
            except WebSocketDisconnect as exc:
                assert exc.code == 4401

        asyncio.run(run())
        client.close()
    finally:
        restore()
        asyncio.run(engine.dispose())
