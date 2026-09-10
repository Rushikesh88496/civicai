"""WARD_REPRESENTATIVE cross-ward data isolation tests (CIVICAGENT).

A ward representative may only read / action complaints (and everything derived
from them: analytics, command center, SLA board, governance, repair
verification, media) in their OWN ward. The ward is ALWAYS derived from the
authenticated user's database record (``User.ward_id``) - a ``ward_id`` query
parameter supplied by the client must never widen the scope.

Matrix exercised here:

- Complaint detail / timeline / operational agents: same-ward OK, other-ward 403.
- Analytics overview + command-center KPIs/queue: scoped; spoofed ``ward_id``
  yields empty results (scope is ANDed, never widened).
- SLA board: scoped to own ward; running the agent + policy writes denied.
- Governance: reads scoped to own ward (cross-ward 403); override writes denied.
- Work-order repair verification: cross-ward run / read / review denied.
- Media: fetching another ward's evidence by storage key is denied.

Helpers model the seeding used across the suite (fresh wards + users + one
complaint per ward) and tear everything down afterwards.
"""

import io
import uuid

import pytest
from PIL import Image as PILImage
from sqlalchemy import delete, select

from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    AIDecisionLog,
    Complaint,
    ComplaintMedia,
    Role,
    User,
    UserProfile,
    Ward,
    WorkOrder,
)
from app.models.enums import (
    ComplaintCategory,
    ComplaintStatus,
    MediaType,
    RoleName,
    WorkOrderStatus,
)
from app.storage import get_storage

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _png_bytes(color: tuple = (120, 80, 40)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 8), color=color).save(buf, format="PNG")
    return buf.getvalue()


async def _citizen_user(email: str) -> User:
    return await _staff_user(email, RoleName.CITIZEN.value)


async def _staff_user(email: str, role_name: str, *, ward_id=None) -> User:
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
        return await db.get(User, user.id)


def _token(user: User, role_name: str) -> str:
    return create_access_token(str(user.id), role_name)


async def _ward(code: str, name: str) -> Ward:
    token = uuid.uuid4().hex[:6]
    async with async_session_factory() as db:
        ward = Ward(
            code=f"{code}-{token}",
            name=f"{name}-{token}",
            description=f"isolation {code}",
        )
        db.add(ward)
        await db.commit()
        return await db.get(Ward, ward.id)


async def _insert_complaint(
    user_id: uuid.UUID, ward_id: uuid.UUID, title: str, *, status=ComplaintStatus.SUBMITTED
) -> uuid.UUID:
    async with async_session_factory() as db:
        complaint = Complaint(
            user_id=user_id,
            ward_id=ward_id,
            category=ComplaintCategory.ROAD,
            title=title,
            description=title,
            status=status,
        )
        db.add(complaint)
        await db.commit()
        return complaint.id


async def _insert_order(complaint_id: uuid.UUID, *, status=WorkOrderStatus.ASSIGNED) -> uuid.UUID:
    async with async_session_factory() as db:
        order = WorkOrder(
            complaint_id=complaint_id,
            incident="isolation order",
            department="ROADS",
            priority="P2_HIGH",
            status=status,
            location_lat=17.4327,
            location_lon=78.3885,
        )
        db.add(order)
        await db.commit()
        return order.id


async def _attach_media(complaint_id: uuid.UUID, user_id: uuid.UUID, key: str) -> str:
    """Upload a real file for a complaint and record its storage key."""
    data = _png_bytes()
    get_storage().upload(key, data, "image/png")
    async with async_session_factory() as db:
        db.add(
            ComplaintMedia(
                complaint_id=complaint_id,
                user_id=user_id,
                media_type=MediaType.IMAGE,
                original_filename="evidence.png",
                storage_key=key,
                storage_backend="local",
                content_type="image/png",
                size_bytes=len(data),
            )
        )
        await db.commit()
    return key


async def _seed_decision(complaint_id: uuid.UUID) -> None:
    from app.services.ai_governance_service import log_ai_decision

    async with async_session_factory() as db:
        await log_ai_decision(
            db,
            complaint_id=complaint_id,
            agent_name="triage",
            model_name="test-model",
            confidence=0.8,
            result={"category": "ROAD"},
        )
        await db.commit()


@pytest.fixture
async def isolation_scope(client):
    """Two wards, one complaint each, plus a WR bound to ward A."""
    citizen = await _citizen_user(_unique_email("iso-cit"))

    ward_a = await _ward("ISOA", "IsoWardA")
    ward_b = await _ward("ISOB", "IsoWardB")
    wr = await _staff_user(
        _unique_email("iso-wr"),
        RoleName.WARD_REPRESENTATIVE.value,
        ward_id=ward_a.id,
    )
    officer = await _staff_user(_unique_email("iso-off"), RoleName.OFFICER.value)

    cid_a = await _insert_complaint(citizen.id, ward_a.id, "Ward A pothole")
    cid_b = await _insert_complaint(citizen.id, ward_b.id, "Ward B pothole")

    yield {
        "ward_a": str(ward_a.id),
        "ward_b": str(ward_b.id),
        "complaint_a": str(cid_a),
        "complaint_b": str(cid_b),
        "citizen_id": str(citizen.id),
        "wr": _token(wr, RoleName.WARD_REPRESENTATIVE.value),
        "officer": _token(officer, RoleName.OFFICER.value),
    }

    async with async_session_factory() as db:
        for cid in (cid_a, cid_b):
            await db.execute(delete(ComplaintMedia).where(ComplaintMedia.complaint_id == cid))
            await db.execute(delete(AIDecisionLog).where(AIDecisionLog.complaint_id == cid))
            await db.execute(delete(WorkOrder).where(WorkOrder.complaint_id == cid))
            await db.execute(delete(Complaint).where(Complaint.id == cid))
        for email in (citizen.email, wr.email, officer.email):
            await db.execute(delete(User).where(User.email == email))
        await db.execute(delete(Ward).where(Ward.id.in_([ward_a.id, ward_b.id])))
        await db.commit()


# --------------------------------------------------------------------------- #
# Complaint detail / timeline / operational agents
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_complaint_detail_and_timeline_scoped(client, isolation_scope):
    s = isolation_scope
    headers = _auth(s["wr"])

    own = await client.get(f"{_BASE}/complaints/{s['complaint_a']}", headers=headers)
    assert own.status_code == 200, own.text
    assert own.json()["id"] == s["complaint_a"]

    other = await client.get(f"{_BASE}/complaints/{s['complaint_b']}", headers=headers)
    assert other.status_code == 403, other.text

    other_timeline = await client.get(
        f"{_BASE}/complaints/{s['complaint_b']}/timeline", headers=headers
    )
    assert other_timeline.status_code == 403, other_timeline.text


@pytest.mark.asyncio
async def test_operational_agents_denied_cross_ward(client, isolation_scope):
    s = isolation_scope
    headers = _auth(s["wr"])

    for path in ("triage", "vision", "correlate", "context"):
        r = await client.post(
            f"{_BASE}/complaints/{s['complaint_b']}/{path}",
            json={},
            headers=headers,
        )
        assert r.status_code == 403, (path, r.status_code)


# --------------------------------------------------------------------------- #
# Analytics + command center: scoped; spoofed ward_id never widens
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_analytics_overview_scoped_and_spoof_safe(client, isolation_scope):
    s = isolation_scope
    headers = _auth(s["wr"])

    overview = await client.get(f"{_BASE}/analytics/overview", headers=headers)
    assert overview.status_code == 200, overview.text
    assert overview.json()["kpis"]["total_complaints"] == 1

    spoofed = await client.get(
        f"{_BASE}/analytics/overview?ward_id={s['ward_b']}", headers=headers
    )
    assert spoofed.status_code == 200, spoofed.text
    assert spoofed.json()["kpis"]["total_complaints"] == 0


@pytest.mark.asyncio
async def test_command_center_scoped_and_spoof_safe(client, isolation_scope):
    s = isolation_scope
    headers = _auth(s["wr"])

    kpis = await client.get(f"{_BASE}/command-center/kpis", headers=headers)
    assert kpis.status_code == 200, kpis.text
    assert kpis.json()["total_complaints"] == 1

    queue = await client.get(f"{_BASE}/command-center/queue", headers=headers)
    assert queue.status_code == 200, queue.text
    ids = {item["complaint_id"] for item in queue.json()["items"]}
    assert s["complaint_a"] in ids
    assert s["complaint_b"] not in ids

    spoofed = await client.get(
        f"{_BASE}/command-center/queue?ward_id={s['ward_b']}", headers=headers
    )
    assert spoofed.status_code == 200, spoofed.text
    assert spoofed.json()["total"] == 0
    assert spoofed.json()["items"] == []


# --------------------------------------------------------------------------- #
# SLA board: scoped to own ward; run + policy writes denied to WR
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_sla_board_scoped_and_writes_denied(client, isolation_scope):
    s = isolation_scope
    headers = _auth(s["wr"])

    await _insert_order(uuid.UUID(s["complaint_b"]))
    await _insert_order(uuid.UUID(s["complaint_a"]))

    board = await client.get(f"{_BASE}/sla/orders", headers=headers)
    assert board.status_code == 200, board.text
    body = board.json()
    cids = {item["complaint_id"] for item in body["items"]}
    assert s["complaint_a"] in cids
    assert s["complaint_b"] not in cids
    assert body["counts"]["open"] == 1

    denied_run = await client.post(f"{_BASE}/sla/run", headers=headers)
    assert denied_run.status_code == 403, denied_run.text

    denied_policy = await client.post(
        f"{_BASE}/sla/policies",
        json={"name": "x", "priority": "P1_CRITICAL", "sla_hours": 8},
        headers=headers,
    )
    assert denied_policy.status_code == 403, denied_policy.text
    # No policy row was written by the denied request.
    async with async_session_factory() as db:
        from app.models import SlaPolicy

        leftover = await db.scalar(
            select(SlaPolicy).where(SlaPolicy.name == "x")
        )
        assert leftover is None

    listed = await client.get(f"{_BASE}/sla/policies", headers=headers)
    assert listed.status_code == 200

    # Officers keep city-wide reads.
    off_headers = _auth(s["officer"])
    off_board = await client.get(f"{_BASE}/sla/orders", headers=off_headers)
    assert off_board.status_code == 200
    off_cids = {item["complaint_id"] for item in off_board.json()["items"]}
    assert s["complaint_a"] in off_cids
    assert s["complaint_b"] in off_cids


# --------------------------------------------------------------------------- #
# Governance: reads scoped (cross-ward 403); override writes denied to WR
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_governance_scoped_and_override_write_denied(client, isolation_scope):
    s = isolation_scope
    headers = _auth(s["wr"])

    await _seed_decision(uuid.UUID(s["complaint_b"]))

    for path in ("decisions", "evidence", "overrides", "summary"):
        r = await client.get(f"{_BASE}/governance/complaints/{s['complaint_b']}/{path}", headers=headers)
        assert r.status_code == 403, (path, r.status_code)

    for cid in (s["complaint_a"], s["complaint_b"]):
        r = await client.post(
            f"{_BASE}/governance/complaints/{cid}/overrides",
            json={"override_type": "priority", "reason": "not my call"},
            headers=headers,
        )
        assert r.status_code == 403, (cid, r.status_code)

    own = await client.get(
        f"{_BASE}/governance/complaints/{s['complaint_a']}/decisions", headers=headers
    )
    assert own.status_code == 200, own.text
    assert own.json() == []


# --------------------------------------------------------------------------- #
# Work-order repair verification: cross-ward run / read / review denied
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_verification_cross_ward_denied(client, isolation_scope):
    s = isolation_scope
    headers = _auth(s["wr"])

    order_b = await _insert_order(
        uuid.UUID(s["complaint_b"]), status=WorkOrderStatus.COMPLETED
    )

    run = await client.post(f"{_BASE}/work-orders/{order_b}/verify", headers=headers)
    assert run.status_code == 403, run.text

    read = await client.get(f"{_BASE}/work-orders/{order_b}/verification", headers=headers)
    assert read.status_code == 403, read.text

    review = await client.post(
        f"{_BASE}/work-orders/{order_b}/verification/review",
        json={"decision": "CONFIRM_VERIFIED"},
        headers=headers,
    )
    assert review.status_code == 403, review.text


# --------------------------------------------------------------------------- #
# Media: evidence fetch is scoped by the owning complaint
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_media_scoped_by_owning_complaint(client, isolation_scope):
    s = isolation_scope
    headers = _auth(s["wr"])

    key_a = f"iso-media-a-{uuid.uuid4().hex[:10]}.png"
    key_b = f"iso-media-b-{uuid.uuid4().hex[:10]}.png"
    await _attach_media(uuid.UUID(s["complaint_a"]), uuid.UUID(s["citizen_id"]), key_a)
    await _attach_media(uuid.UUID(s["complaint_b"]), uuid.UUID(s["citizen_id"]), key_b)

    own = await client.get(f"/media/{key_a}", headers=headers)
    assert own.status_code == 200, own.text

    other = await client.get(f"/media/{key_b}", headers=headers)
    assert other.status_code == 403, other.text