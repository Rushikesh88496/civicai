"""PART 30 — AI pipeline verification.

Covers Groq integration wiring, schema validation, agent-run persistence
(agent logs), tool evidence (AIDecisionLog + EvidenceCheck), human-review
flags, and fallback handling when the provider fails.

All AI calls use the suite-standard fakes (no real Groq requests); the
provider wiring itself (config → Groq client) is asserted against
``app.services.ai_service``.
"""

import uuid

import pytest
from sqlalchemy import select

from app.agents.triage_agent import TriageAgent
from app.core.config import Settings
from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import AgentRun, AIDecisionLog, Complaint, EvidenceCheck, User
from app.models.enums import (
    AgentStatus,
    ComplaintCategory,
    ComplaintStatus,
    TriageSeverity,
    TriageUrgency,
)
from app.schemas.triage import TriageOutput
from app.services import auth_service
from app.services.ai_service import AIConnectionError
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_API = "/api/v1"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeTriageAI:
    def __init__(self, responses):
        self._responses = responses
        self.calls = 0

    async def structured_completion(self, messages, schema, **kwargs):
        self.calls += 1
        outcome = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _tri_out(**kw) -> TriageOutput:
    base = dict(
        category=ComplaintCategory.ROAD,
        severity=TriageSeverity.MEDIUM,
        urgency=TriageUrgency.MEDIUM,
        infrastructure_type="road surface",
        summary="Issue requires attention.",
        confidence=0.9,
        recommended_action="Dispatch crew.",
        human_review_required=False,
    )
    base.update(kw)
    return TriageOutput(**base)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            auth_service.RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="AI Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _officer_token(email: str) -> str:
    from app.core.security import hash_password
    from app.models import Role, UserProfile

    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == "OFFICER"))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="AI Officer",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), "OFFICER")


async def _complaint(client, token: str) -> str:
    r = await client.post(
        f"{_API}/complaints",
        json={
            "description": "Dangerous pothole on the main road.",
            "category": "ROAD",
            "media_ids": [],
            "location": {
                "latitude": 18.4634,
                "longitude": 73.8912,
                "address": "Main Road",
                "source": "gps",
                "geopoint_denied": False,
            },
        },
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# 1. Provider wiring (config → schema-constrained completion)
# --------------------------------------------------------------------------- #
def test_groq_provider_wiring(monkeypatch):
    """The Groq client builder is driven by config (key + retries + timeout) and
    returns ``None`` when no API key is configured."""
    captured = {}
    fake_client = object()

    def _fake_asyncgroq(**kw):
        captured.update(kw)
        return fake_client

    import app.services.ai_service as ai_service

    monkeypatch.setattr(ai_service, "AsyncGroq", _fake_asyncgroq)
    settings = Settings(
        GROQ_API_KEY="x-test-key-1234567890abcdef",
        GROQ_MODEL="acme/model",
        GROQ_MAX_RETRIES=2,
        GROQ_TIMEOUT_SECONDS=7.5,
    )
    client = ai_service._build_client(settings)
    assert client is fake_client
    assert captured["api_key"] == settings.GROQ_API_KEY
    assert captured["max_retries"] == 2
    assert captured["timeout"] == 7.5

    unconfigured = ai_service._build_client(Settings(GROQ_API_KEY="", GROQ_MODEL="x"))
    assert unconfigured is None


# --------------------------------------------------------------------------- #
# 2. Schema validation + agent log / evidence persistence
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_triage_schema_valid_run_logs_decision_and_evidence(client, monkeypatch):
    email = _unique_email("ai-schema")
    token = await _citizen_token(email)
    otoken = await _officer_token(_unique_email("ai-schema-officer"))
    cid = await _complaint(client, token)

    fake = FakeTriageAI([_tri_out(category=ComplaintCategory.ROAD, confidence=0.95)])
    monkeypatch.setattr("app.services.triage_service._agent", lambda: TriageAgent(ai=fake))

    r = await client.post(f"{_API}/complaints/{cid}/triage", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == AgentStatus.SUCCEEDED.value
    assert data["result"]["category"] == "ROAD"
    assert data["run_id"]

    # Complaint advanced only on a valid schema-conformant result
    async with async_session_factory() as db:
        complaint = await db.get(Complaint, uuid.UUID(cid))
        assert complaint.status == ComplaintStatus.PRIORITIZED

        # Agent run persisted (agent log)
        run = await db.scalar(
            select(AgentRun).where(
                AgentRun.id == uuid.UUID(data["run_id"]),
                AgentRun.complaint_id == uuid.UUID(cid),
            )
        )
        assert run is not None
        assert run.agent == "triage"
        assert run.status == AgentStatus.SUCCEEDED.value

        # AI decision logged with tool/evidence metadata
        decision = await db.scalar(
            select(AIDecisionLog).where(AIDecisionLog.complaint_id == uuid.UUID(cid))
        )
        assert decision is not None
        assert decision.agent_name == "triage"
        assert decision.prompt_version
        assert decision.confidence == 0.95

        # The category claim was cross-checked against ground truth
        check = await db.scalar(
            select(EvidenceCheck).where(EvidenceCheck.complaint_id == uuid.UUID(cid))
        )
        assert check is not None
        assert check.claim_type in {"category", "department"}
        assert check.is_match is True

    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        await db.delete(user)
        await db.commit()


# --------------------------------------------------------------------------- #
# 3. Fallback handling: provider failure marks the run FAILED, complaint intact
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_triage_provider_failure_routes_to_retry(client, monkeypatch):
    email = _unique_email("ai-ff")
    token = await _citizen_token(email)
    otoken = await _officer_token(_unique_email("ai-ff-officer"))
    cid = await _complaint(client, token)

    fake = FakeTriageAI([AIConnectionError("cannot reach groq")])
    monkeypatch.setattr("app.services.triage_service._agent", lambda: TriageAgent(ai=fake))

    async with async_session_factory() as db:
        complaint = await db.get(Complaint, uuid.UUID(cid))
        before_status = complaint.status

    r = await client.post(f"{_API}/complaints/{cid}/triage", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == AgentStatus.FAILED.value
    assert data["retry_allowed"] is True

    async with async_session_factory() as db:
        complaint = await db.get(Complaint, uuid.UUID(cid))
        # Complaint is preserved for retry — no partial/destructive update
        assert complaint.status == before_status
        run = await db.scalar(
            select(AgentRun).where(
                AgentRun.id == uuid.UUID(data["run_id"]),
                AgentRun.complaint_id == uuid.UUID(cid),
            )
        )
        assert run is not None
        assert run.status == AgentStatus.FAILED.value
        assert "groq" in (run.error or "").lower()

    # Retry with a healthy provider now succeeds (recovery path)
    fake2 = FakeTriageAI([_tri_out(category=ComplaintCategory.ROAD, confidence=0.9)])
    monkeypatch.setattr("app.services.triage_service._agent", lambda: TriageAgent(ai=fake2))

    r2 = await client.post(f"{_API}/complaints/{cid}/triage", headers=_auth(otoken))
    assert r2.status_code == 200
    assert r2.json()["status"] == AgentStatus.SUCCEEDED.value


# --------------------------------------------------------------------------- #
# 4. Missing API key produces a clear, recorded failure (never a crash)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_triage_missing_api_key_fails_cleanly(client, monkeypatch):
    email = _unique_email("ai-nokey")
    token = await _citizen_token(email)
    otoken = await _officer_token(_unique_email("ai-nokey-officer"))
    cid = await _complaint(client, token)

    # No fake AI: the real AIService hits its configuration guard.
    monkeypatch.setattr(
        "app.services.triage_service._agent",
        lambda: TriageAgent(settings=Settings(GROQ_API_KEY="", GROQ_MODEL="x")),
    )

    r = await client.post(f"{_API}/complaints/{cid}/triage", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == AgentStatus.FAILED.value
    assert "GROQ" in (r.json()["error"] or "").upper()


# --------------------------------------------------------------------------- #
# 5. Human-review flag is honored end-to-end (no complaint close)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_triage_low_confidence_flags_human_review(client, monkeypatch):
    email = _unique_email("ai-hr")
    token = await _citizen_token(email)
    otoken = await _officer_token(_unique_email("ai-hr-officer"))
    cid = await _complaint(client, token)

    fake = FakeTriageAI(
        [_tri_out(category=ComplaintCategory.ROAD, confidence=0.3, human_review_required=True)]
    )
    monkeypatch.setattr("app.services.triage_service._agent", lambda: TriageAgent(ai=fake))

    r = await client.post(f"{_API}/complaints/{cid}/triage", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["result"]["human_review_required"] is True
    async with async_session_factory() as db:
        complaint = await db.get(Complaint, uuid.UUID(cid))
        assert complaint.status in (
            ComplaintStatus.PRIORITIZED,
            ComplaintStatus.SUBMITTED,
        )
