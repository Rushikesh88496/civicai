"""Tests for the AI Triage Agent (Part 7).

Covers the LangGraph ``START→Triage→Validate→Persist→END`` flow against a real
(live dev) database with a *fake* AI backend, so no Groq network calls or real
API key are used. Scenarios: road / water / garbage / flood complaints, an
ambiguous low-confidence result, invalid model JSON (retry then fallback to
human review), a hard Groq failure (run marked FAILED, complaint preserved) and
a missing API key. Regression coverage runs against the complaint endpoints too.
"""

import io
import uuid

import pytest
from PIL import Image as PILImage
from sqlalchemy import select

from app.agents.triage_agent import DEFAULT_MAX_VALIDATION_RETRIES, TriageAgent
from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import AgentRun, Complaint, User
from app.models.enums import (
    AgentStatus,
    ComplaintCategory,
    ComplaintStatus,
    TriageSeverity,
    TriageUrgency,
)
from app.schemas.triage import TriageInput, TriageOutput
from app.services import auth_service
from tests.helpers import any_active_ward_id, any_officer_token

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeAI:
    """Drop-in AIService fake. ``responses`` is a list of either a TriageOutput
    or an exception to raise on that call, cycled in order (last repeats)."""

    def __init__(self, responses: list):
        self._responses = responses
        self.calls = 0
        self.schema = None

    async def structured_completion(self, messages, schema, **kwargs):
        self.calls += 1
        self.schema = schema
        outcome = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _out(
    category: ComplaintCategory = ComplaintCategory.ROAD,
    severity: TriageSeverity = TriageSeverity.MEDIUM,
    urgency: TriageUrgency = TriageUrgency.MEDIUM,
    summary: str = "Issue requires attention.",
    confidence: float = 0.9,
    human_review: bool = False,
) -> TriageOutput:
    return TriageOutput(
        category=category,
        severity=severity,
        urgency=urgency,
        infrastructure_type="road surface",
        summary=summary,
        confidence=confidence,
        recommended_action="Dispatch the responsible crew.",
        human_review_required=human_review,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (64, 64), color=(70, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


async def _citizen_token(email: str) -> str:
    from app.schemas.auth import RegisterIn

    async with async_session_factory() as db:
        await auth_service.register_user(
            db, RegisterIn(
                    email=email,
                    password=_PASSWORD,
                    full_name="Triage Citizen",
                    ward_id=await any_active_ward_id(db),
                )
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _create_complaint(client, token: str, category: str = "ROAD", desc: str = None) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    r = await client.post(
        f"{_BASE}/media",
        files={"file": ("p.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    media_id = r.json()["id"]
    body = {
        "description": desc or "Deep pothole on the main road near the school.",
        "category": category,
        "media_ids": [media_id],
        "location": {
            "latitude": 18.5204,
            "longitude": 73.8567,
            "address": "Main Road",
            "source": "gps",
            "geopoint_denied": False,
        },
    }
    r = await client.post(_BASE, json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


def _agent(ai) -> TriageAgent:
    return TriageAgent(ai=ai, max_validation_retries=DEFAULT_MAX_VALIDATION_RETRIES)


async def _run_agent(ai, complaint_id: str, **input_kw) -> tuple[AgentRun, "TriageOutput | None"]:
    run: AgentRun = None
    result = None
    async with async_session_factory() as db:
        input_data = TriageInput(
            description=input_kw.pop("description", "Deep pothole on the main road."),
            category=input_kw.pop("category", ComplaintCategory.ROAD),
            location=input_kw.pop("location", "Main Road"),
            language=input_kw.pop("language", "en"),
        )
        run = await _agent(ai).run(db, complaint_id=uuid.UUID(complaint_id), input_data=input_data)
        result = (
            TriageOutput.model_validate(run.structured_result) if run.structured_result else None
        )
    return run, result


async def _fetch_run(complaint_id: str):
    async with async_session_factory() as db:
        run = await db.scalar(
            select(AgentRun)
            .where(AgentRun.complaint_id == uuid.UUID(complaint_id))
            .order_by(AgentRun.started_at.desc())
        )
        complaint = await db.get(Complaint, uuid.UUID(complaint_id))
        return run, complaint


# --------------------------------------------------------------------------- #
# Unit tests: category scenarios
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_triage_road_complaint(client):
    from app.models.enums import AgentStatus as St

    email = _unique_email("trg-road")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, "ROAD")

    run, result = await _run_agent(
        FakeAI([_out(category=ComplaintCategory.ROAD, severity=TriageSeverity.HIGH)]),
        complaint_id,
        category=ComplaintCategory.ROAD,
    )
    assert run.status == St.SUCCEEDED
    assert result.category == ComplaintCategory.ROAD
    assert result.severity == TriageSeverity.HIGH

    _, complaint = await _fetch_run(complaint_id)
    assert complaint.status == ComplaintStatus.PRIORITIZED

    await _delete_user(email)


@pytest.mark.asyncio
async def test_triage_water_complaint(client):
    email = _unique_email("trg-water")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, "WATER")

    run, result = await _run_agent(
        FakeAI([_out(category=ComplaintCategory.WATER, severity=TriageSeverity.CRITICAL)]),
        complaint_id,
        category=ComplaintCategory.WATER,
    )
    assert run.status == AgentStatus.SUCCEEDED
    assert result.category == ComplaintCategory.WATER
    assert result.severity == TriageSeverity.CRITICAL
    await _delete_user(email)


@pytest.mark.asyncio
async def test_triage_garbage_complaint(client):
    email = _unique_email("trg-garb")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, "GARBAGE")

    run, result = await _run_agent(
        FakeAI([_out(category=ComplaintCategory.GARBAGE, summary="Overflowing bin.")]),
        complaint_id,
        category=ComplaintCategory.GARBAGE,
    )
    assert run.status == AgentStatus.SUCCEEDED
    assert result.category == ComplaintCategory.GARBAGE
    await _delete_user(email)


@pytest.mark.asyncio
async def test_triage_flood_complaint(client):
    email = _unique_email("trg-flood")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, "FLOODING")

    run, result = await _run_agent(
        FakeAI([_out(category=ComplaintCategory.FLOODING, severity=TriageSeverity.CRITICAL)]),
        complaint_id,
        category=ComplaintCategory.FLOODING,
    )
    assert run.status == AgentStatus.SUCCEEDED
    assert result.category == ComplaintCategory.FLOODING
    await _delete_user(email)


@pytest.mark.asyncio
async def test_triage_ambiguous_flagged_for_human_review(client):
    """Low-confidence output flags the complaint for human review while still
    persisting a valid (schema-safe) result."""
    email = _unique_email("trg-ambig")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, "OTHER")

    run, result = await _run_agent(
        FakeAI([_out(confidence=0.3, human_review=True)]),
        complaint_id,
        category=ComplaintCategory.OTHER,
    )
    assert run.status == AgentStatus.SUCCEEDED
    assert result.human_review_required is True
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Unit tests: invalid output / provider failure / missing key
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_triage_invalid_json_retries_then_succeeds(client):
    from app.services.ai_service import AIStructuredParsingError

    email = _unique_email("trg-inv-retry")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, "ROAD")

    valid = _out(category=ComplaintCategory.ROAD)
    fake = FakeAI(
        [
            AIStructuredParsingError("bad json attempt 1"),
            AIStructuredParsingError("bad json 2"),
            valid,
        ]
    )
    run, result = await _run_agent(fake, complaint_id, category=ComplaintCategory.ROAD)
    assert run.status == AgentStatus.SUCCEEDED
    # First two calls failed validation, the third succeeded.
    assert fake.calls == 3
    assert result.category == ComplaintCategory.ROAD
    await _delete_user(email)


@pytest.mark.asyncio
async def test_triage_invalid_json_exhausted_human_review(client):
    from app.services.ai_service import AIStructuredParsingError

    email = _unique_email("trg-inv-exhaust")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, "ROAD")

    fake = FakeAI([AIStructuredParsingError("always invalid")])
    run, result = await _run_agent(fake, complaint_id, category=ComplaintCategory.ROAD)
    # After exhausting the retry budget the agent falls back to a valid
    # human-review result and still persists it.
    assert run.status == AgentStatus.SUCCEEDED
    assert fake.calls == DEFAULT_MAX_VALIDATION_RETRIES
    assert result.human_review_required is True
    assert result.confidence == 0.0
    assert "review" in result.summary.lower()
    await _delete_user(email)


@pytest.mark.asyncio
async def test_triage_groq_failure_marks_failed_and_preserves_complaint(client):
    from app.services.ai_service import AIConnectionError

    email = _unique_email("trg-fail")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, "ROAD")

    fake = FakeAI([AIConnectionError("cannot reach groq")])
    run, result = await _run_agent(fake, complaint_id, category=ComplaintCategory.ROAD)
    assert run.status == AgentStatus.FAILED
    assert result is None
    # Complaint survives and is NOT advanced to PRIORITIZED.
    _, complaint = await _fetch_run(complaint_id)
    assert complaint is not None
    assert complaint.status != ComplaintStatus.PRIORITIZED
    # A retry is allowed and a new run can be created.
    run2, _ = await _run_agent(
        FakeAI([_out(category=ComplaintCategory.ROAD)]),
        complaint_id,
        category=ComplaintCategory.ROAD,
    )
    assert run2.status == AgentStatus.SUCCEEDED
    await _delete_user(email)


@pytest.mark.asyncio
async def test_triage_missing_api_key_marks_failed(client):
    from app.core.config import Settings
    from app.services.ai_service import AIService

    email = _unique_email("trg-nokey")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, "ROAD")

    real_missing = AIService(
        settings=Settings(GROQ_API_KEY="", GROQ_MODEL="fake-model"),
        client=None,
    )
    run, result = await _run_agent(
        real_missing,
        complaint_id,
        category=ComplaintCategory.ROAD,
    )
    assert run.status == AgentStatus.FAILED
    assert "GROQ" in (run.error or "")
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# API integration: run triage endpoint + access control
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_run_triage_success(client, monkeypatch):
    email = _unique_email("trg-api")
    token = await _citizen_token(email)
    otoken = await any_officer_token(_unique_email("trg-api-officer"))
    complaint_id = await _create_complaint(client, token, "ROAD")

    from app.services.triage_service import TriageAgent as _AgentCls

    fake = FakeAI([_out(category=ComplaintCategory.ROAD, severity=TriageSeverity.HIGH)])
    monkeypatch.setattr(
        "app.services.triage_service._agent",
        lambda: _AgentCls(ai=fake),
    )

    resp = await client.post(
        f"{_BASE}/{complaint_id}/triage",
        json={"language": "en"},
        headers={"Authorization": f"Bearer {otoken}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == AgentStatus.SUCCEEDED.value
    assert data["result"]["category"] == "ROAD"
    assert data["retry_allowed"] is True
    assert data["run_id"]

    await _delete_user(email)


@pytest.mark.asyncio
async def test_api_run_triage_requires_auth(client):
    resp = await client.post(f"{_BASE}/{uuid.uuid4()}/triage", json={"language": "en"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_ai_triage_requires_access(client):
    owner_email = _unique_email("trg-ow")
    other_email = _unique_email("trg-oth")
    owner_token = await _citizen_token(owner_email)
    other_token = await _citizen_token(other_email)
    complaint_id = await _create_complaint(client, owner_token)

    # Officers-only: even the complaint owner (a citizen) gets 403.
    owner_resp = await client.get(
        f"{_BASE}/{complaint_id}/ai-triage",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_resp.status_code == 403, owner_resp.text

    resp = await client.get(
        f"{_BASE}/{complaint_id}/ai-triage",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403, resp.text

    await _delete_user(owner_email)
    await _delete_user(other_email)
