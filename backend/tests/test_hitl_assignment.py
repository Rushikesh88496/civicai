"""Human-in-the-loop assignment provenance (Part 32).

The Dispatch Agent only ever produces a *recommendation*; the actual assignment
is an official officer action. These tests assert:

* dispatch persists a DRAFT work order (``PENDING_APPROVAL``) with a frozen
  ``recommended_worker_id`` and **no** ``WorkerAssignment`` row — an AI
  recommendation is never presented as (nor recorded as) an official assignment;
* officer approve/assign/reassign write a ``WorkerAssignment`` whose ``origin``
  classifies the pick: ``AI_RECOMMENDATION`` / ``OFFICER_OVERRIDE`` / ``MANUAL``;
* an override pick (different worker than the AI recommended) is persisted as a
  ``human_overrides`` row (``override_type="assignment"``);
* the work-order audit trail (``work_order.approve`` / ``.assign`` / ``.reassign``)
  records complaint + work-order ids, previous/new assignee, assigning officer,
  reason/source, is_ai_recommended, officer_decision, and status;
* the complaint timeline merges the work-order milestone trail
  (``work_order_events``) so the UI can render the full lifecycle;
* RBAC: citizens and field workers may not approve, and a ward representative of
  another ward cannot act on a work order.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    AuditLog,
    Complaint,
    Department,
    FieldWorker,
    HumanOverride,
    Role,
    User,
    UserProfile,
    Ward,
    WorkerAssignment,
    WorkOrder,
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


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="HITL Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _staff_token(email: str, role: RoleName, ward_id: uuid.UUID | None = None) -> str:
    async with async_session_factory() as db:
        rrole = await db.scalar(select(Role).where(Role.name == role.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=f"{role.value} HITL",
            role_id=rrole.id,
            ward_id=ward_id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), role.value)


async def _create_second_ward(db) -> uuid.UUID:
    ward = Ward(
        name="HITL Other Ward",
        code=f"HITL-{uuid.uuid4().hex[:6]}",
        description="test other ward",
    )
    db.add(ward)
    await db.flush()
    await db.commit()
    return ward.id


async def _create_complaint(client, token: str) -> str:
    body = {
        "description": "HITL assignment test",
        "category": "GARBAGE",
        "media_ids": [],
        "location": {
            "latitude": _LAT,
            "longitude": _LON,
            "address": "HITL test location",
            "source": "gps",
            "geopoint_denied": False,
        },
    }
    r = await client.post(_BASE, json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _clear_workers() -> None:
    async with async_session_factory() as db:
        for fw in (await db.execute(select(FieldWorker))).scalars().all():
            await db.delete(fw)
        rrole = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        for u in (await db.execute(select(User).where(User.role_id == rrole.id))).scalars().all():
            await db.delete(u)
        await db.commit()


async def _seed_worker(*, email: str, name: str = "HITL Worker") -> uuid.UUID:
    async with async_session_factory() as db:
        dept = await db.scalar(select(Department).where(Department.code == "WASTE"))
        if dept is None:
            dept = Department(name="WASTE", code="WASTE", description="waste crew")
            db.add(dept)
            await db.flush()
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
        fw = FieldWorker(
            user_id=user.id,
            department_id=dept.id,
            specialty="waste-audit",
            status=WorkerStatus.ACTIVE,
            home_latitude=_LAT,
            home_longitude=_LON,
            skill_tags=["waste-audit", "collections"],
            equipment=["garbage-truck"],
        )
        db.add(fw)
        await db.commit()
        return fw.id


async def _worker_token(email: str) -> str:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), RoleName.FIELD_WORKER.value)


async def _assignment_rows(work_order_id: str) -> list[list]:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(WorkerAssignment).where(
                    WorkerAssignment.work_order_id == work_order_id
                )
            )
        )
        return [
            [r.worker_id, r.status, r.origin, r.reason, r.assigned_by]
            for r in rows.scalars().all()
        ]


async def _override_rows(complaint_id: str) -> list[HumanOverride]:
    async with async_session_factory() as db:
        return list(
            (
                await db.execute(
                    select(HumanOverride).where(HumanOverride.complaint_id == complaint_id)
                )
            )
            .scalars()
            .all()
        )


async def _audit_after(action: str, work_order_id: str) -> dict:
    async with async_session_factory() as db:
        row = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == action, AuditLog.entity_id == work_order_id
            )
        )
        return row.after if row is not None else {}


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _delete_complaint(complaint_id: str) -> None:
    async with async_session_factory() as db:
        complaint = await db.scalar(select(Complaint).where(Complaint.id == complaint_id))
        if complaint is not None:
            await db.delete(complaint)
            await db.commit()


async def _dispatch(client, dispatch_token: str, complaint_id: str) -> str:
    r = await client.post(f"{_BASE}/{complaint_id}/dispatch", headers=_auth(dispatch_token))
    assert r.status_code == 201, r.text
    return r.json()["work_order_id"]


# --------------------------------------------------------------------------- #
# AI recommendation is NOT an assignment
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dispatch_draft_has_recommendation_but_no_assignment(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-draft")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-draft-o"), RoleName.OFFICER)
    wid = await _seed_worker(email=_unique_email("hitl-draft-w"), name="Draft Worker")
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, otoken, cid)
        async with async_session_factory() as db:
            order = await db.scalar(select(WorkOrder).where(WorkOrder.id == work_id))
            assert order is not None
            assert order.status == "PENDING_APPROVAL"
            assert str(order.recommended_worker_id) == str(wid)
            # Draft carries the proposed worker, but the AI recommendation is
            # NOT an official assignment yet (no WorkerAssignment row), and the
            # recommendation is frozen separately for provenance.
            assert str(order.worker_id) == str(wid)
        assert await _assignment_rows(work_id) == []
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# Officer approve / assign classification
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_approve_records_ai_recommendation_assignment(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-apr")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-apr-o"), RoleName.OFFICER)
    wid = await _seed_worker(email=_unique_email("hitl-apr-w"), name="Approve Worker")
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, otoken, cid)
        r = await client.post(
            f"{_WO}/{work_id}/approve", json={"note": "sounds right"}, headers=_auth(otoken)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["work_order"]["status"] == "ASSIGNED"
        assert body["work_order"]["worker_name"] == "Approve Worker"
        assert body["work_order"]["recommended_worker_name"] == "Approve Worker"

        rows = await _assignment_rows(work_id)
        assert len(rows) == 1
        assert str(rows[0][0]) == str(wid)
        assert rows[0][2] == "AI_RECOMMENDATION"
        assert await _override_rows(cid) == []
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_assign_same_worker_as_recommendation_is_ai(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-assignsame")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-assignsame-o"), RoleName.OFFICER)
    wid = await _seed_worker(email=_unique_email("hitl-assignsame-w"), name="Same Worker")
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, otoken, cid)
        r = await client.post(
            f"{_WO}/{work_id}/assign",
            json={"worker_id": str(wid), "reason": "keep the pick"},
            headers=_auth(otoken),
        )
        assert r.status_code == 200, r.text
        assert r.json()["work_order"]["worker_name"] == "Same Worker"
        rows = await _assignment_rows(work_id)
        assert len(rows) == 1
        assert rows[0][2] == "AI_RECOMMENDATION"
        assert await _override_rows(cid) == []

        a = await _audit_after("work_order.assign", work_id)
        assert a.get("is_ai_recommended") is True
        assert a.get("officer_decision") == "accepted"
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_assign_different_worker_records_override(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-override")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-override-o"), RoleName.OFFICER)
    rec_wid = await _seed_worker(
        email=_unique_email("hitl-override-w1"), name="Recommended Worker"
    )
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, otoken, cid)
        d = await client.get(f"{_WO}/{work_id}", headers=_auth(otoken))
        assert d.status_code == 200, d.text
        assert d.json()["work_order"]["recommended_worker_id"] == str(rec_wid)
        # Seed the alternative worker only AFTER dispatch so it cannot have been
        # ranked — selecting it is unambiguously an officer override.
        other_wid = await _seed_worker(
            email=_unique_email("hitl-override-w2"), name="Alternative Worker"
        )
        r = await client.post(
            f"{_WO}/{work_id}/assign",
            json={"worker_id": str(other_wid), "reason": "closer to site"},
            headers=_auth(otoken),
        )
        assert r.status_code == 200, r.text
        assert r.json()["work_order"]["worker_name"] == "Alternative Worker"

        rows = await _assignment_rows(work_id)
        assert len(rows) == 1
        assert rows[0][2] == "OFFICER_OVERRIDE"

        overrides = await _override_rows(cid)
        assert len(overrides) == 1
        o = overrides[0]
        assert o.override_type == "assignment"
        assert o.original_value == "Recommended Worker"
        assert o.new_value == "Alternative Worker"
        assert "AI recommended Recommended Worker" in o.reason

        a = await _audit_after("work_order.assign", work_id)
        assert a.get("assignment_source") == "OFFICER_OVERRIDE"
        assert a.get("is_ai_recommended") is False
        assert a.get("officer_decision") == "overridden"
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_assign_without_recommendation_is_manual(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-manual")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-manual-o"), RoleName.OFFICER)
    cid = await _create_complaint(client, token)
    try:
        # No worker pool at dispatch time → no recommendation.
        work_id = await _dispatch(client, otoken, cid)
        wid = await _seed_worker(email=_unique_email("hitl-manual-w"), name="Manual Worker")
        async with async_session_factory() as db:
            order = await db.scalar(select(WorkOrder).where(WorkOrder.id == work_id))
            assert order.recommended_worker_id is None

        r = await client.post(
            f"{_WO}/{work_id}/assign",
            json={"worker_id": str(wid), "reason": "assign manually"},
            headers=_auth(otoken),
        )
        assert r.status_code == 200, r.text
        rows = await _assignment_rows(work_id)
        assert len(rows) == 1
        assert rows[0][2] == "MANUAL"
        assert await _override_rows(cid) == []
        a = await _audit_after("work_order.assign", work_id)
        assert a.get("officer_decision") == "manual"
        assert a.get("is_ai_recommended") is False
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# Recommendation explanation + assignment-audit enrichment
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dispatch_recommendation_has_explanation(client, monkeypatch):
    """The recommended worker ships a concise explanation built ONLY from the
    actual scored candidate data (skill / department / ward / availability /
    workload / distance) — never hardcoded worker picks."""
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-explain")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-explain-o"), RoleName.OFFICER)
    wid = await _seed_worker(email=_unique_email("hitl-explain-w"), name="Explain Worker")
    cid = await _create_complaint(client, token)
    try:
        await _dispatch(client, otoken, cid)
        r = await client.get(f"{_BASE}/{cid}/dispatch-result", headers=_auth(otoken))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["structured_result"] is not None
        rec = body["structured_result"]["recommendation"]
        assert rec["recommended_worker_id"] == str(wid)
        explanation = rec["recommended_worker_explanation"]
        assert explanation
        assert explanation.startswith("Recommended because")
        assert "Explain Worker" in explanation
        # Built from real scored data: distance and/or active-assignment count.
        assert " km from the complaint" in explanation or "active assignment" in explanation
        # The raw workload snapshot behind the normalized score is exposed too.
        best = next(c for c in rec["candidates"] if c["worker_id"] == str(wid))
        assert best["active_orders"] == 0
        assert best["capacity"] is not None
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_assign_audit_records_recommended_worker_and_timestamp(client, monkeypatch):
    """The assignment audit entry records the AI-recommended worker, the assigned
    worker, the officer id and the exact assignment timestamp."""
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-auditrec")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-auditrec-o"), RoleName.OFFICER)
    wid = await _seed_worker(email=_unique_email("hitl-auditrec-w"), name="Audit Rec Worker")
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, otoken, cid)
        r = await client.post(
            f"{_WO}/{work_id}/assign",
            json={"worker_id": str(wid), "reason": "accept the pick"},
            headers=_auth(otoken),
        )
        assert r.status_code == 200, r.text
        a = await _audit_after("work_order.assign", work_id)
        assert a.get("complaint_id") == cid
        assert str(a.get("recommended_worker_id")) == str(wid)
        assert a.get("recommended_worker_name") == "Audit Rec Worker"
        assert str(a.get("new_assignee_id")) == str(wid)
        assert a.get("new_assignee_name") == "Audit Rec Worker"
        assert a.get("assigning_user_id")
        assert a.get("assigned_at")
        assert a.get("assignment_source") == "AI_RECOMMENDATION"
        assert a.get("officer_decision") == "accepted"
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# Reassign + full audit payload
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_reassign_captures_previous_assignee_and_audit_fields(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-reassign")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-reassign-o"), RoleName.OFFICER)
    first_wid = await _seed_worker(email=_unique_email("hitl-reassign-w1"), name="First Worker")
    third_wid = await _seed_worker(email=_unique_email("hitl-reassign-w2"), name="Third Worker")
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, otoken, cid)
        await client.post(
            f"{_WO}/{work_id}/approve", json={"note": "ok"}, headers=_auth(otoken)
        )
        r = await client.post(
            f"{_WO}/{work_id}/reassign",
            json={"worker_id": str(third_wid), "reason": "not a good fit"},
            headers=_auth(otoken),
        )
        assert r.status_code == 200, r.text
        assert r.json()["work_order"]["worker_name"] == "Third Worker"

        rows = await _assignment_rows(work_id)
        # approve-created AI assignment is superseded; reassign row is new+active.
        assert len(rows) == 2
        statuses = {status for _, status, _, _, _ in rows}
        assert {"ASSIGNED", "UNASSIGNED"} & statuses
        origins = {org for _, _, org, _, _ in rows}
        assert origins == {"AI_RECOMMENDATION", "OFFICER_OVERRIDE"}

        overrides = await _override_rows(cid)
        assert len(overrides) == 1
        assert overrides[0].override_type == "assignment"
        assert overrides[0].original_value == "First Worker"
        assert overrides[0].new_value == "Third Worker"

        a = await _audit_after("work_order.reassign", work_id)
        assert a.get("complaint_id") == cid
        assert a.get("work_order_id") == work_id
        assert str(a.get("previous_assignee_id")) == str(first_wid)
        assert a.get("previous_assignee_name") == "First Worker"
        assert str(a.get("new_assignee_id")) == str(third_wid)
        assert a.get("new_assignee_name") == "Third Worker"
        assert a.get("assignment_reason") == "not a good fit"
        assert a.get("assignment_source") == "OFFICER_OVERRIDE"
        assert a.get("is_ai_recommended") is False
        assert a.get("officer_decision") == "overridden"
        assert a.get("status") == "ASSIGNED"
        assert a.get("assigning_user_id")
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


@pytest.mark.asyncio
async def test_approve_audit_has_expected_payload(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-afull")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-afull-o"), RoleName.OFFICER)
    wid = await _seed_worker(email=_unique_email("hitl-afull-w"), name="Audit Worker")
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, otoken, cid)
        await client.post(
            f"{_WO}/{work_id}/approve", json={"note": "approved"}, headers=_auth(otoken)
        )
        a = await _audit_after("work_order.approve", work_id)
        assert a.get("complaint_id") == cid
        assert a.get("work_order_id") == work_id
        assert str(a.get("new_assignee_id")) == str(wid)
        assert a.get("new_assignee_name") == "Audit Worker"
        assert a.get("assignment_source") == "AI_RECOMMENDATION"
        assert a.get("is_ai_recommended") is True
        assert a.get("officer_decision") == "accepted"
        assert a.get("status") == "ASSIGNED"
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# Timeline merges work-order milestones
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_timeline_includes_work_order_events(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()
    email = _unique_email("hitl-tl")
    token = await _citizen_token(email)
    otoken = await _staff_token(_unique_email("hitl-tl-o"), RoleName.OFFICER)
    await _seed_worker(email=_unique_email("hitl-tl-w"), name="Timeline Worker")
    cid = await _create_complaint(client, token)
    try:
        work_id = await _dispatch(client, otoken, cid)
        await client.post(
            f"{_WO}/{work_id}/approve", json={"note": "go"}, headers=_auth(otoken)
        )
        tl = await client.get(f"{_BASE}/{cid}/timeline", headers=_auth(token))
        assert tl.status_code == 200, tl.text
        body = tl.json()
        assert body["work_order_events"]
        actions = {e["action"] for e in body["work_order_events"]}
        assert {"DISPATCH", "APPROVE"} <= actions
        approve = next(e for e in body["work_order_events"] if e["action"] == "APPROVE")
        assert approve["work_order_id"] == work_id
        assert approve["actor_name"] == "OFFICER HITL"
        assert approve["status"] == "ASSIGNED"
    finally:
        await _delete_complaint(cid)
        await _delete_user(email)


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_role_and_ward_rbac(client, monkeypatch):
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    await _clear_workers()

    citizen_email = _unique_email("hitl-rbac-c")
    citizen_token = await _citizen_token(citizen_email)
    otoken = await _staff_token(_unique_email("hitl-rbac-o"), RoleName.OFFICER)

    async with async_session_factory() as db:
        ward_b = await _create_second_ward(db)
        other_ward_email = _unique_email("hitl-rbac-wr")
        other_ward_token = await _staff_token(
            other_ward_email, RoleName.WARD_REPRESENTATIVE, ward_id=ward_b
        )

    worker_email = _unique_email("hitl-rbac-fw")
    await _seed_worker(email=worker_email, name="RBAC Worker")
    worker_token = await _worker_token(worker_email)

    cid = await _create_complaint(client, citizen_token)
    try:
        work_id = await _dispatch(client, otoken, cid)

        # Citizen: cannot approve (staff-only action).
        r = await client.post(
            f"{_WO}/{work_id}/approve", json={}, headers=_auth(citizen_token)
        )
        assert r.status_code == 403

        # Field worker: cannot approve (staff-only action).
        r = await client.post(
            f"{_WO}/{work_id}/approve", json={}, headers=_auth(worker_token)
        )
        assert r.status_code == 403

        # Ward rep from another ward: cannot approve.
        r = await client.post(
            f"{_WO}/{work_id}/approve", json={}, headers=_auth(other_ward_token)
        )
        assert r.status_code in (403, 404)

        # Officer: can approve.
        r = await client.post(
            f"{_WO}/{work_id}/approve", json={"note": "ok"}, headers=_auth(otoken)
        )
        assert r.status_code == 200, r.text
    finally:
        await _delete_complaint(cid)
        await _delete_user(citizen_email)
        await _delete_user(other_ward_email)
        await _delete_user(worker_email)
        async with async_session_factory() as db:
            ward = await db.scalar(select(Ward).where(Ward.code.like("HITL-%")))
            if ward is not None:
                await db.delete(ward)
                await db.commit()
