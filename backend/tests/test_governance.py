"""AI Governance API tests (Part 28): decision log, evidence, overrides.

These run against the live development database and clean up after themselves.
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    AIDecisionLog,
    AuditLog,
    Complaint,
    EvidenceCheck,
    HumanOverride,
    Role,
    User,
    UserProfile,
)
from app.models.enums import (
    ComplaintCategory,
    ComplaintPriority,
    ComplaintStatus,
    RoleName,
)

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/governance"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _make_user(db, email: str, role_name: str) -> User:
    role = await db.scalar(select(Role).where(Role.name == role_name))
    user = User(
        email=email,
        password_hash=hash_password(_PASSWORD),
        full_name="Gov Test",
        role_id=role.id,
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id))
    await db.flush()
    return user


@pytest.fixture
async def governance_scope(client):
    """A complaint plus a citizen owner and an OFFICER (staff) caller."""
    emails = [_unique_email("gov-cit"), _unique_email("gov-off")]
    complaint_id = None
    async with async_session_factory() as db:
        citizen = await _make_user(db, emails[0], RoleName.CITIZEN.value)
        officer = await _make_user(db, emails[1], RoleName.OFFICER.value)
        await db.commit()
        complaint = Complaint(
            user_id=citizen.id,
            category=ComplaintCategory.ROAD,
            title="Broken road near station",
            priority=ComplaintPriority.MEDIUM,
            status=ComplaintStatus.OPEN,
        )
        db.add(complaint)
        await db.commit()
        complaint_id = complaint.id

    citizen_token = create_access_token(str(citizen.id), RoleName.CITIZEN.value)
    officer_token = create_access_token(str(officer.id), RoleName.OFFICER.value)
    yield {
        "complaint_id": str(complaint_id),
        "citizen": emails[0],
        "officer": emails[1],
        "citizen_token": citizen_token,
        "officer_token": officer_token,
    }

    # Teardown: governance rows, audit rows, complaint, then users.
    async with async_session_factory() as db:
        await db.execute(delete(HumanOverride).where(HumanOverride.complaint_id == complaint_id))
        await db.execute(delete(EvidenceCheck).where(EvidenceCheck.complaint_id == complaint_id))
        await db.execute(delete(AIDecisionLog).where(AIDecisionLog.complaint_id == complaint_id))
        await db.execute(delete(AuditLog).where(AuditLog.entity_id == str(complaint_id)))
        await db.execute(delete(Complaint).where(Complaint.id == complaint_id))
        for email in emails:
            user = await db.scalar(select(User).where(User.email == email))
            if user is not None:
                await db.execute(delete(HumanOverride).where(HumanOverride.user_id == user.id))
                await db.execute(delete(AuditLog).where(AuditLog.actor_id == user.id))
                await db.delete(user)
        await db.commit()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _list_decision_ids(db, complaint_id) -> list:
    rows = await db.execute(
        select(AIDecisionLog.id).where(AIDecisionLog.complaint_id == complaint_id)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_governance_requires_auth(client, governance_scope):
    cid = governance_scope["complaint_id"]
    assert (await client.get(f"{_BASE}/complaints/{cid}/decisions")).status_code == 401
    assert (await client.get(f"{_BASE}/complaints/{cid}/evidence")).status_code == 401
    assert (await client.get(f"{_BASE}/complaints/{cid}/overrides")).status_code == 401


@pytest.mark.asyncio
async def test_governance_forbids_citizen(client, governance_scope):
    cid = governance_scope["complaint_id"]
    headers = _auth(governance_scope["citizen_token"])
    assert (
        await client.get(f"{_BASE}/complaints/{cid}/decisions", headers=headers)
    ).status_code == 403
    post = await client.post(
        f"{_BASE}/complaints/{cid}/overrides",
        headers=headers,
        json={"override_type": "priority", "reason": "nope"},
    )
    assert post.status_code == 403


@pytest.mark.asyncio
async def test_decisions_empty_then_seeded(client, governance_scope):
    cid = governance_scope["complaint_id"]
    headers = _auth(governance_scope["officer_token"])

    empty = await client.get(f"{_BASE}/complaints/{cid}/decisions", headers=headers)
    assert empty.status_code == 200
    assert empty.json() == []

    async with async_session_factory() as db:
        from app.services.ai_governance_service import log_ai_decision

        await log_ai_decision(
            db,
            complaint_id=uuid.UUID(cid),
            agent_name="triage",
            model_name="test-model",
            prompt_version="triage.v1",
            confidence=0.8,
            result={"category": "ROAD"},
        )
        await db.commit()

    listed = await client.get(f"{_BASE}/complaints/{cid}/decisions", headers=headers)
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["agent_name"] == "triage"
    assert body[0]["confidence"] == 0.8


@pytest.mark.asyncio
async def test_evidence_records_mismatch(client, governance_scope):
    cid = governance_scope["complaint_id"]
    headers = _auth(governance_scope["officer_token"])

    async with async_session_factory() as db:
        from app.services.ai_governance_service import log_ai_decision
        from app.services.evidence_validation_service import validate_category_claim

        decision = await log_ai_decision(
            db,
            complaint_id=uuid.UUID(cid),
            agent_name="triage",
            model_name="test-model",
            confidence=0.9,
        )
        await validate_category_claim(
            db,
            complaint_id=uuid.UUID(cid),
            decision_id=decision.id,
            claimed_category="ROAD",
            actual_category="WATER_LEAK",
        )
        await db.commit()

    ev = await client.get(f"{_BASE}/complaints/{cid}/evidence", headers=headers)
    assert ev.status_code == 200
    body = ev.json()
    assert len(body) == 1
    assert body[0]["is_match"] is False
    assert body[0]["discrepancy_pct"] == 100.0
    assert body[0]["claim_type"] == "category"


@pytest.mark.asyncio
async def test_override_round_trip(client, governance_scope):
    cid = governance_scope["complaint_id"]
    headers = _auth(governance_scope["officer_token"])

    post = await client.post(
        f"{_BASE}/complaints/{cid}/overrides",
        headers=headers,
        json={
            "override_type": "priority",
            "original_value": "P2",
            "new_value": "P1",
            "reason": "Visible hazard; escalate immediately.",
        },
    )
    assert post.status_code == 201
    override = post.json()
    assert override["override_type"] == "priority"
    assert override["original_value"] == "P2"
    assert override["new_value"] == "P1"
    assert override["complaint_id"] == cid

    lst = await client.get(f"{_BASE}/complaints/{cid}/overrides", headers=headers)
    assert lst.status_code == 200
    body = lst.json()
    assert len(body) == 1
    assert body[0]["reason"].startswith("Visible hazard")

    summary = await client.get(f"{_BASE}/complaints/{cid}/summary", headers=headers)
    assert summary.status_code == 200
    s = summary.json()
    assert s["decision_count"] == 0
    assert s["override_count"] == 1


@pytest.mark.asyncio
async def test_override_with_decision_marks_override(client, governance_scope):
    cid = governance_scope["complaint_id"]
    headers = _auth(governance_scope["officer_token"])

    async with async_session_factory() as db:
        from app.services.ai_governance_service import log_ai_decision

        decision = await log_ai_decision(
            db,
            complaint_id=uuid.UUID(cid),
            agent_name="triage",
            model_name="test-model",
            result={"recommended_action": "Inspect crew"},
        )
        await db.commit()
        decision_id = str(decision.id)

    post = await client.post(
        f"{_BASE}/complaints/{cid}/overrides",
        headers=headers,
        json={
            "override_type": "routing",
            "decision_id": decision_id,
            "new_value": "PARKS",
            "reason": "Wrong department; park ranger needed.",
        },
    )
    assert post.status_code == 201
    assert post.json()["original_value"] == "Inspect crew"

    async with async_session_factory() as db:
        stored = await db.get(AIDecisionLog, uuid.UUID(decision_id))
        assert stored is not None
        assert stored.is_override is True


@pytest.mark.asyncio
async def test_override_unknown_decision_404(client, governance_scope):
    cid = governance_scope["complaint_id"]
    headers = _auth(governance_scope["officer_token"])
    post = await client.post(
        f"{_BASE}/complaints/{cid}/overrides",
        headers=headers,
        json={
            "override_type": "priority",
            "decision_id": str(uuid.uuid4()),
            "reason": "dangling reference",
        },
    )
    assert post.status_code == 404


@pytest.mark.asyncio
async def test_summary_reports_mismatches(client, governance_scope):
    cid = governance_scope["complaint_id"]
    headers = _auth(governance_scope["officer_token"])

    async with async_session_factory() as db:
        from app.services.ai_governance_service import log_ai_decision
        from app.services.evidence_validation_service import validate_category_claim
        from app.services.override_service import record_override

        decision = await log_ai_decision(
            db,
            complaint_id=uuid.UUID(cid),
            agent_name="triage",
            model_name="m",
        )
        await validate_category_claim(
            db,
            complaint_id=uuid.UUID(cid),
            decision_id=decision.id,
            claimed_category="ROAD",
            actual_category="GARBAGE",
        )
        await record_override(
            db,
            complaint_id=uuid.UUID(cid),
            override_type="priority",
            original_value="P2",
            new_value="P1",
            reason="hazard",
        )
        await db.commit()

    summary = await client.get(f"{_BASE}/complaints/{cid}/summary", headers=headers)
    assert summary.status_code == 200
    s = summary.json()
    assert s["decision_count"] == 1
    assert s["evidence_check_count"] == 1
    assert s["override_count"] == 1
    assert s["has_mismatches"] is True


@pytest.mark.asyncio
async def test_missing_complaint_404(client, governance_scope):
    headers = _auth(governance_scope["officer_token"])
    ghost = str(uuid.uuid4())
    assert (
        await client.get(f"{_BASE}/complaints/{ghost}/decisions", headers=headers)
    ).status_code == 404
