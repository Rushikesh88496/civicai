"""Tests for the AI Evidence Verification (Vision) Agent (Part 8).

Covers the LangGraph ``START→Vision→Validate→Persist→END`` flow against a real
(live dev) database with a *fake* AI backend, so no Groq network calls or real
API key are used. Scenarios: valid pothole / water-leak images (evidence
detected), an unrelated image (mismatch), a low-confidence result, an invalid /
missing / non-image attachment, a hard Groq failure (run marked FAILED, complaint
preserved) and a missing API key. Regression coverage runs against the complaint
vision endpoints too.
"""

import io
import uuid

import pytest
from PIL import Image as PILImage
from sqlalchemy import select

from app.agents.vision_agent import DEFAULT_MAX_VALIDATION_RETRIES, VisionAgent
from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import AgentRun, Complaint, ComplaintMedia, User
from app.models.enums import AgentStatus, ComplaintStatus, MediaType, TriageSeverity
from app.schemas.vision import VisionInput, VisionOutput
from app.services import auth_service
from tests.helpers import any_active_ward_id, any_officer_token

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeAI:
    """Drop-in AIService fake for vision calls. ``responses`` is a list of either
    a VisionOutput or an exception, cycled in order (last repeats)."""

    def __init__(self, responses: list, callable_fail=None):
        self._responses = responses
        self._callable_fail = callable_fail  # optional; when set, raises before cycling
        self.calls = 0
        self.schema = None
        self.last_content = None

    async def structured_vision_completion(self, content, schema, **kwargs):
        self.calls += 1
        self.schema = schema
        self.last_content = content
        if self._callable_fail is not None:
            raise self._callable_fail(self)
        outcome = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _out(
    detected: bool = True,
    issue: str = "pothole",
    severity: TriageSeverity = TriageSeverity.HIGH,
    confidence: float = 0.9,
    mismatch: bool = False,
    human_review: bool = False,
) -> VisionOutput:
    return VisionOutput(
        visual_evidence_detected=detected,
        detected_issue=issue,
        severity=severity,
        confidence=confidence,
        evidence_description=f"Visible {issue} in the attached photo.",
        mismatch_detected=mismatch,
        human_review_required=human_review,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (64, 64), color=(120, 80, 40)).save(buf, format="JPEG")
    return buf.getvalue()


async def _citizen_token(email: str) -> str:
    from app.schemas.auth import RegisterIn

    async with async_session_factory() as db:
        await auth_service.register_user(
            db, RegisterIn(
                    email=email,
                    password=_PASSWORD,
                    full_name="Vision Citizen",
                    ward_id=await any_active_ward_id(db),
                )
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _create_complaint(client, token: str, *, desc: str = None, count_images: int = 1) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    media_ids = []
    for _ in range(count_images):
        r = await client.post(
            f"{_BASE}/media",
            files={"file": ("p.jpg", _jpeg_bytes(), "image/jpeg")},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        media_ids.append(r.json()["id"])
    body = {
        "description": desc or "Deep pothole on the main road near the school.",
        "category": "ROAD",
        "media_ids": media_ids,
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


def _agent(ai) -> VisionAgent:
    return VisionAgent(ai=ai, max_validation_retries=DEFAULT_MAX_VALIDATION_RETRIES)


async def _storage_keys(complaint_id: str) -> list[str]:
    async with async_session_factory() as db:
        result = await db.execute(
            select(ComplaintMedia.storage_key)
            .where(
                ComplaintMedia.complaint_id == uuid.UUID(complaint_id),
                ComplaintMedia.media_type == MediaType.IMAGE,
            )
            .order_by(ComplaintMedia.created_at)
        )
        return list(result.scalars().all())


async def _run_agent(ai, complaint_id: str, **input_kw) -> tuple[AgentRun, "VisionOutput | None"]:
    run: AgentRun = None
    result = None
    keys = []
    if "image_keys" in input_kw:
        keys = input_kw.pop("image_keys")
    else:
        keys = await _storage_keys(complaint_id)
    description = input_kw.pop("description", "Deep pothole on the main road.")
    category = input_kw.pop("category", "ROAD")
    async with async_session_factory() as db:
        input_data = VisionInput(
            description=description,
            category=category,
            image_keys=keys,
        )
        run = await _agent(ai).run(db, complaint_id=uuid.UUID(complaint_id), input_data=input_data)
        result = (
            VisionOutput.model_validate(run.structured_result) if run.structured_result else None
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
# Unit tests: evidence scenarios
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_vision_pothole_image_evidence_detected(client):
    from app.models.enums import AgentStatus as St

    email = _unique_email("vis-pothole")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, desc="Deep pothole near school.")

    run, result = await _run_agent(FakeAI([_out(issue="pothole")]), complaint_id)
    assert run.status == St.SUCCEEDED
    assert result.visual_evidence_detected is True
    assert result.detected_issue == "pothole"
    assert result.human_review_required is False

    _, complaint = await _fetch_run(complaint_id)
    assert complaint.status == ComplaintStatus.EVIDENCE_VERIFIED

    await _delete_user(email)


@pytest.mark.asyncio
async def test_vision_water_leak_evidence_detected(client):
    email = _unique_email("vis-water")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, desc="Leaking pipeline on Elm street.")

    run, result = await _run_agent(FakeAI([_out(issue="water leak")]), complaint_id)
    assert run.status == AgentStatus.SUCCEEDED
    assert result.visual_evidence_detected is True
    assert result.detected_issue == "water leak"
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Unit tests: mismatch / low confidence
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_vision_unrelated_image_flags_mismatch(client):
    email = _unique_email("vis-unrel")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, desc="Sinkhole on the sidewalk.")

    run, result = await _run_agent(FakeAI([_out(detected=False, mismatch=True)]), complaint_id)
    assert run.status == AgentStatus.SUCCEEDED
    assert result.mismatch_detected is True
    assert result.visual_evidence_detected is False
    assert result.human_review_required is True
    # The complaint is NOT closed because of a mismatch.
    _, complaint = await _fetch_run(complaint_id)
    assert complaint is not None
    assert complaint.status != ComplaintStatus.CLOSED
    await _delete_user(email)


@pytest.mark.asyncio
async def test_vision_low_confidence_requires_review(client):
    email = _unique_email("vis-lowconf")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token)

    run, result = await _run_agent(
        FakeAI([_out(confidence=0.25, human_review=False)]), complaint_id
    )
    assert run.status == AgentStatus.SUCCEEDED
    # low confidence forces human_review even when the model didn't flag it.
    assert result.human_review_required is True
    _, complaint = await _fetch_run(complaint_id)
    assert complaint.status == ComplaintStatus.EVIDENCE_VERIFIED
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Unit tests: invalid / missing / non-image evidence
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_vision_invalid_image_marks_failed(client):
    email = _unique_email("vis-invimg")
    token = await _citizen_token(email)

    # Upload then overwrite the stored bytes with corrupt data via direct DB.
    complaint_id = await _create_complaint(client, token)
    keys = await _storage_keys(complaint_id)
    key = keys[0]
    from app.storage import get_storage

    get_storage().upload(key, b"this is not an image", "image/jpeg")

    run, result = await _run_agent(FakeAI([_out()]), complaint_id)
    assert run.status == AgentStatus.FAILED
    assert result is None
    assert "valid" in (run.error or "")
    _, complaint = await _fetch_run(complaint_id)
    assert complaint is not None
    await _delete_user(email)


@pytest.mark.asyncio
async def test_vision_missing_image_marks_failed(client):
    email = _unique_email("vis-noimg")
    token = await _citizen_token(email)

    complaint_id = await _create_complaint(client, token, count_images=0)
    run, result = await _run_agent(FakeAI([_out()]), complaint_id)
    assert run.status == AgentStatus.FAILED
    assert result is None
    assert "No image" in (run.error or "")
    _, complaint = await _fetch_run(complaint_id)
    assert complaint is not None
    assert complaint.status != ComplaintStatus.EVIDENCE_VERIFIED
    await _delete_user(email)


@pytest.mark.asyncio
async def test_vision_unsupported_media_marks_failed(client):
    email = _unique_email("vis-video")
    token = await _citizen_token(email)

    headers = {"Authorization": f"Bearer {token}"}
    r = await client.post(
        f"{_BASE}/media",
        files={"file": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    media_id = r.json()["id"]
    body = {
        "description": "A bubbling water leakage on the corner.",
        "category": "WATER",
        "media_ids": [media_id],
        "location": {"latitude": 18.5, "longitude": 73.0, "address": "Corner", "source": "manual"},
    }
    r = await client.post(_BASE, json=body, headers=headers)
    assert r.status_code == 201, r.text
    complaint_id = r.json()["id"]

    run, result = await _run_agent(FakeAI([_out()]), complaint_id)
    # No IMAGE media → the agent fails cleanly (unsupported evidence).
    assert run.status == AgentStatus.FAILED
    assert result is None
    assert "No image" in (run.error or "")
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Unit tests: provider failure / missing key
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_vision_groq_failure_marks_failed_and_preserves_complaint(client):
    from app.services.ai_service import AIConnectionError

    email = _unique_email("vis-fail")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token)

    fake = FakeAI([AIConnectionError("cannot reach groq")])
    run, result = await _run_agent(fake, complaint_id)
    assert run.status == AgentStatus.FAILED
    assert result is None
    # Complaint survives and is NOT advanced to EVIDENCE_VERIFIED.
    _, complaint = await _fetch_run(complaint_id)
    assert complaint is not None
    assert complaint.status != ComplaintStatus.EVIDENCE_VERIFIED
    # Retry allowed → a second run can succeed.
    run2, result2 = await _run_agent(FakeAI([_out(issue="pothole")]), complaint_id)
    assert run2.status == AgentStatus.SUCCEEDED
    assert result2 is not None
    await _delete_user(email)


@pytest.mark.asyncio
async def test_vision_missing_api_key_marks_failed(client):
    from app.core.config import Settings
    from app.services.ai_service import AIService

    email = _unique_email("vis-nokey")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token)

    real_missing = AIService(
        settings=Settings(GROQ_API_KEY="", GROQ_MODEL="fake-model"),
        client=None,
    )
    run, result = await _run_agent(real_missing, complaint_id)
    assert run.status == AgentStatus.FAILED
    assert "GROQ" in (run.error or "")
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# API integration: run vision endpoint + access control
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_run_vision_success(client, monkeypatch):
    email = _unique_email("vis-api")
    token = await _citizen_token(email)
    otoken = await any_officer_token(_unique_email("vis-api-officer"))
    complaint_id = await _create_complaint(client, token, desc="Water main burst.")

    from app.services.vision_service import VisionAgent as _AgentCls

    fake = FakeAI([_out(issue="water leak", severity=TriageSeverity.CRITICAL)])
    monkeypatch.setattr("app.services.vision_service._agent", lambda: _AgentCls(ai=fake))

    resp = await client.post(
        f"{_BASE}/{complaint_id}/vision",
        headers={"Authorization": f"Bearer {otoken}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == AgentStatus.SUCCEEDED.value
    assert data["result"]["visual_evidence_detected"] is True
    assert data["result"]["detected_issue"] == "water leak"
    assert data["retry_allowed"] is True
    assert data["run_id"]

    get = await client.get(
        f"{_BASE}/{complaint_id}/vision-result",
        headers={"Authorization": f"Bearer {otoken}"},
    )
    assert get.status_code == 200
    assert get.json()["agent"] == "vision"
    assert get.json()["structured_result"]["detected_issue"] == "water leak"

    await _delete_user(email)


@pytest.mark.asyncio
async def test_api_run_vision_requires_auth(client):
    resp = await client.post(f"{_BASE}/{uuid.uuid4()}/vision")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_vision_requires_access(client):
    owner_email = _unique_email("vis-ow")
    other_email = _unique_email("vis-oth")
    owner_token = await _citizen_token(owner_email)
    other_token = await _citizen_token(other_email)
    complaint_id = await _create_complaint(client, owner_token)

    resp = await client.post(
        f"{_BASE}/{complaint_id}/vision",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403, resp.text

    await _delete_user(owner_email)
    await _delete_user(other_email)
