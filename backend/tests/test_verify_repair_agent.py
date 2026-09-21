"""Tests for the AI Resolution Verification Agent + API (Part 19).

Exercises the ``START → Verify → Validate → Persist → END`` LangGraph against a
real (live dev) database with a *fake* AI backend so no Groq network calls or a
real API key are used. Covered scenarios:

* **Agent unit** — successful ``VERIFIED``, the deterministic unchanged-photo
  pixel-diff guard (no AI call), low confidence → ``NEEDS_HUMAN_REVIEW``,
  critical-priority (P1) human-approval rule, missing photo → FAILED.
* **API** — staff can run on a ``COMPLETED`` order, read the latest result,
  review via ``CONFIRM_VERIFIED`` / ``REQUIRES_FOLLOWUP``; RBAC (401/403/409)
  and read access for staff / assigned worker / complaint owner.

Helpers reuse the Part 18 field-worker seeding so the work order has real BEFORE
/ AFTER photos stored in object storage for the agent to read.
"""

import io
import uuid
from datetime import UTC, datetime

import pytest
from PIL import Image as PILImage
from sqlalchemy import delete, select

from app.agents.verify_repair_agent import VerifyRepairAgent
from app.core.config import get_settings
from app.core.security import create_access_token, decode_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    AuditLog,
    Complaint,
    ComplaintMedia,
    Department,
    FieldWorker,
    Notification,
    Role,
    User,
    UserProfile,
    WorkOrder,
    WorkOrderPhoto,
    WorkOrderVerification,
)
from app.models.enums import (
    ComplaintStatus,
    MediaType,
    RoleName,
    VerificationStatus,
    WorkerStatus,
    WorkOrderStatus,
)
from app.schemas.verification import VerificationInput
from app.services import auth_service
from app.services.audit_service import (
    ACTION_WORK_ORDER_EVIDENCE_VIEWED,
    ACTION_WORK_ORDER_RESOLUTION_CONFIRMED,
    ACTION_WORK_ORDER_VERIFICATION_COMPLETED,
    ACTION_WORK_ORDER_VERIFICATION_STARTED,
)
from app.storage import get_storage
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_COMPLAINTS = "/api/v1/complaints"
_VERIFY = "/api/v1/work-orders"
_SETTINGS = get_settings()
_LAT = 18.4634
_LON = 73.8912


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeAI:
    """Drop-in AIService fake for the verify agent's vision call.

    ``responses`` is a list of ``VerificationOutput`` objects or exceptions,
    cycled in order (last repeats). ``callable_fail`` is optional: when set it
    raises before cycling each call. ``preflight_exc`` (optional) makes the
    pre-flight ``ensure_vision_ready`` raise on every attempt so model/config
    failures can be exercised without touching the vision call.
    """

    def __init__(self, responses: list, callable_fail=None, preflight_exc=None):
        self._responses = responses
        self._callable_fail = callable_fail
        self._preflight_exc = preflight_exc
        self.calls = 0

    async def ensure_vision_ready(self, model=None):
        if self._preflight_exc is not None:
            raise self._preflight_exc

    async def structured_vision_completion(self, content, schema, **kwargs):
        self.calls += 1
        if self._callable_fail is not None:
            raise self._callable_fail(self)
        outcome = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _out(
    *,
    status: VerificationStatus = VerificationStatus.VERIFIED,
    confidence: float = 0.95,
    evidence: str = "AFTER shows the pothole is filled with fresh asphalt.",
    remaining: str = "",
    review: bool = False,
) -> "object":
    from app.schemas.verification import VerificationOutput

    return VerificationOutput(
        repair_evidence=evidence,
        remaining_issue=remaining,
        confidence=confidence,
        verification_status=status,
        issue_fixed=(status == VerificationStatus.VERIFIED),
        human_review_required=review,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _png_bytes(color: tuple = (120, 80, 40)) -> bytes:
    """A real 64x64 PNG so Pillow's verify() succeeds."""
    buf = io.BytesIO()
    PILImage.new("RGB", (64, 64), color=color).save(buf, format="PNG")
    return buf.getvalue()


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            auth_service.RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Verify Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _staff_token(email: str, role: RoleName = RoleName.OFFICER) -> str:
    async with async_session_factory() as db:
        r = await db.scalar(select(Role).where(Role.name == role.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Verify Officer",
            role_id=r.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), role.value)


async def _seed_worker(email: str) -> tuple[str, str]:
    """Return the worker's FIELD_WORKER token and FieldWorker id."""
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Verify Worker",
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
            skill_tags=["collections"],
            equipment=["garbage-truck"],
        )
        db.add(fw)
        await db.commit()
        return (
            create_access_token(str(user.id), RoleName.FIELD_WORKER.value),
            str(fw.id),
        )


async def _seed_completed_order(
    citizen_token: str,
    worker_id: str,
    *,
    priority: str = "P2_HIGH",
    before_color: tuple = (70, 60, 50),
    after_color: tuple = (200, 220, 90),
    complaint_status: ComplaintStatus = ComplaintStatus.RESOLVED,
) -> tuple[str, str, str]:
    """Seed a COMPLETED work order with BEFORE + AFTER photos.

    Returns ``(order_id, complaint_id, citizen_token)``.
    """
    uid = uuid.UUID(decode_token(citizen_token, "access")["sub"])
    async with async_session_factory() as db:
        # Complaint
        complaint = Complaint(
            description="Deep pothole on the main road near the school.",
            title="ROAD: Deep pothole on the main road near the school.",
            category="ROAD",
            status=complaint_status,
            user_id=uid,
        )
        db.add(complaint)
        await db.flush()

        # Work order
        order = WorkOrder(
            complaint_id=complaint.id,
            department="ROAD",
            priority=priority,
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

        # BEFORE photo
        b_png = _png_bytes(before_color)
        b_key = f"verify-test-{order.id}-before.png"
        get_storage().upload(b_key, b_png, "image/png")
        db.add(
            WorkOrderPhoto(
                work_order_id=order.id,
                worker_id=worker_id,
                category="BEFORE",
                original_filename="before.png",
                storage_key=b_key,
                content_type="image/png",
                size_bytes=len(b_png),
                allowed=True,
            )
        )

        # AFTER photo
        a_png = _png_bytes(after_color)
        a_key = f"verify-test-{order.id}-after.png"
        get_storage().upload(a_key, a_png, "image/png")
        db.add(
            WorkOrderPhoto(
                work_order_id=order.id,
                worker_id=worker_id,
                category="AFTER",
                original_filename="after.png",
                storage_key=a_key,
                content_type="image/png",
                size_bytes=len(a_png),
                allowed=True,
            )
        )

        await db.commit()
        return str(order.id), str(complaint.id), citizen_token


def _agent(fake_ai=None, **kwargs) -> VerifyRepairAgent:
    return VerifyRepairAgent(ai=fake_ai, **kwargs)


async def _order_with_photos(order_id: str, db):
    from sqlalchemy.orm import selectinload

    return await db.scalar(
        select(WorkOrder)
        .options(selectinload(WorkOrder.photos))
        .where(WorkOrder.id == uuid.UUID(order_id))
    )


async def _latest_verification(order_id: str) -> WorkOrderVerification | None:
    async with async_session_factory() as db:
        return await db.scalar(
            select(WorkOrderVerification)
            .where(WorkOrderVerification.work_order_id == uuid.UUID(order_id))
            .order_by(WorkOrderVerification.created_at.desc())
            .limit(1)
        )


async def _cleanup() -> None:
    from app.models import WorkerAssignment

    async with async_session_factory() as db:
        await db.execute(delete(Notification))
        await db.execute(delete(WorkOrderPhoto))
        await db.execute(delete(WorkOrderVerification))
        await db.execute(delete(WorkerAssignment))
        await db.execute(delete(WorkOrder))
        fws = (await db.execute(select(FieldWorker))).scalars().all()
        for fw in fws:
            await db.delete(fw)
        rrole = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        if rrole is not None:
            for u in (
                (await db.execute(select(User).where(User.role_id == rrole.id))).scalars().all()
            ):
                await db.delete(u)
        await db.commit()


@pytest.fixture(autouse=True)
async def _leave_db_clean():
    yield
    await _cleanup()


# --------------------------------------------------------------------------- #
# Agent unit: outcomes
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_verify_success_verified(client):
    """Successful VERIFIED outcome: run completes, verification row persists."""
    citizen = await _citizen_token(_unique_email("vf-ok-cit"))
    wtoken, wid = await _seed_worker(_unique_email("vf-ok-worker"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    # Feed a successful VERIFIED result through the agent
    fake = FakeAI([_out(status=VerificationStatus.VERIFIED, confidence=0.94)])
    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        before_photo = next(p for p in order.photos if p.category == "BEFORE")
        after_photo = next(p for p in order.photos if p.category == "AFTER")
        input_data = VerificationInput(
            complaint_description="Deep pothole on the main road near the school.",
            category="ROAD",
            before_key=before_photo.storage_key,
            after_key=after_photo.storage_key,
            before_photo_id=before_photo.id,
            after_photo_id=after_photo.id,
            priority_bucket=order.priority,
        )
        run = await VerifyRepairAgent(ai=fake).run(
            db,
            work_order_id=uuid.UUID(order_id),
            complaint_id=uuid.UUID(cid),
            input_data=input_data,
        )

    assert run.status.value == "SUCCEEDED"
    verification = await _latest_verification(order_id)
    assert verification is not None
    assert verification.verification_status == VerificationStatus.VERIFIED
    assert verification.human_review_required is False
    assert verification.repair_evidence == "AFTER shows the pothole is filled with fresh asphalt."
    assert verification.source == "groq"


@pytest.mark.asyncio
async def test_verify_unchanged_photo_pixel_diff(client):
    """Same byte content → pixel-diff guard triggers, no AI call, NOT_RESOLVED."""
    wtoken, wid = await _seed_worker(_unique_email("vf-unchanged-worker"))
    citizen = await _citizen_token(_unique_email("vf-unchanged-cit"))
    # Use the SAME color for both photos so thumbnails match
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(100, 100, 100),
        after_color=(100, 100, 100),
    )

    fake = FakeAI([])
    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        before_photo = next(p for p in order.photos if p.category == "BEFORE")
        after_photo = next(p for p in order.photos if p.category == "AFTER")
        input_data = VerificationInput(
            complaint_description="Deep pothole on the main road.",
            category="ROAD",
            before_key=before_photo.storage_key,
            after_key=after_photo.storage_key,
            before_photo_id=before_photo.id,
            after_photo_id=after_photo.id,
            priority_bucket="P3_MEDIUM",
        )
        await VerifyRepairAgent(ai=fake).run(
            db,
            work_order_id=uuid.UUID(order_id),
            complaint_id=uuid.UUID(cid),
            input_data=input_data,
        )

    # AI was never called
    assert fake.calls == 0
    verification = await _latest_verification(order_id)
    assert verification is not None
    assert verification.verification_status == VerificationStatus.NOT_RESOLVED
    assert verification.source == "pixel-diff"
    assert verification.confidence == 1.0
    assert verification.human_review_required is True


@pytest.mark.asyncio
async def test_verify_missing_photo_marks_failed(client):
    """Missing AFTER photo → run FAILED, no verification row persisted."""
    wtoken, wid = await _seed_worker(_unique_email("vf-nophoto-worker"))
    citizen = await _citizen_token(_unique_email("vf-nophoto-cit"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    fake = FakeAI([_out()])
    async with async_session_factory() as db:
        input_data = VerificationInput(
            complaint_description="Deep pothole on the main road.",
            category="ROAD",
            before_key=None,  # missing both
            after_key=None,
            priority_bucket="P2_HIGH",
        )
        run = await VerifyRepairAgent(ai=fake).run(
            db,
            work_order_id=uuid.UUID(order_id),
            complaint_id=uuid.UUID(cid),
            input_data=input_data,
        )

    assert run.status.value == "FAILED"
    assert fake.calls == 0
    assert "evidence photo" in (run.error or "").lower()
    assert await _latest_verification(order_id) is None


@pytest.mark.asyncio
async def test_verify_low_confidence_forces_human_review(client):
    """Low confidence → NEEDS_HUMAN_REVIEW regardless of model verdict."""
    wtoken, wid = await _seed_worker(_unique_email("vf-lowconf-worker"))
    citizen = await _citizen_token(_unique_email("vf-lowconf-cit"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    fake = FakeAI(
        [
            _out(status=VerificationStatus.VERIFIED, confidence=0.2, review=False),
        ]
    )
    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        before_photo = next(p for p in order.photos if p.category == "BEFORE")
        after_photo = next(p for p in order.photos if p.category == "AFTER")
        input_data = VerificationInput(
            complaint_description="Deep pothole on the main road.",
            category="ROAD",
            before_key=before_photo.storage_key,
            after_key=after_photo.storage_key,
            before_photo_id=before_photo.id,
            after_photo_id=after_photo.id,
            priority_bucket="P2_HIGH",
        )
        run = await VerifyRepairAgent(ai=fake).run(
            db,
            work_order_id=uuid.UUID(order_id),
            complaint_id=uuid.UUID(cid),
            input_data=input_data,
        )

    assert run.status.value == "SUCCEEDED"
    verification = await _latest_verification(order_id)
    assert verification is not None
    # Low confidence forces NEEDS_HUMAN_REVIEW
    assert verification.verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW
    assert verification.human_review_required is True


@pytest.mark.asyncio
async def test_verify_json_validate_failed_routes_to_human_review(client):
    """Server-side JSON rejection retries, then persists a NEEDS_HUMAN_REVIEW
    fallback (never a FAILED-with-no-verdict)."""
    from app.services.ai_service import AIAPIError

    wtoken, wid = await _seed_worker(_unique_email("vf-jvl-worker"))
    citizen = await _citizen_token(_unique_email("vf-jvl-cit"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    fake = FakeAI(
        [
            AIAPIError("Groq API error: json_validate_failed", code="json_validate_failed"),
        ]
    )
    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        before_photo = next(p for p in order.photos if p.category == "BEFORE")
        after_photo = next(p for p in order.photos if p.category == "AFTER")
        input_data = VerificationInput(
            complaint_description="Deep pothole on the main road.",
            category="ROAD",
            before_key=before_photo.storage_key,
            after_key=after_photo.storage_key,
            before_photo_id=before_photo.id,
            after_photo_id=after_photo.id,
            priority_bucket="P2_HIGH",
        )
        run = await VerifyRepairAgent(ai=fake).run(
            db,
            work_order_id=uuid.UUID(order_id),
            complaint_id=uuid.UUID(cid),
            input_data=input_data,
        )

    # Retried through the whole budget (1 + (max_retries - 1)) calls then fell back.
    assert fake.calls == 2
    assert run.status.value == "SUCCEEDED"
    verification = await _latest_verification(order_id)
    assert verification is not None
    assert verification.verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW
    assert verification.human_review_required is True


def test_verify_schema_normalizes_model_verdicts():
    """Model aliases (NOT_VERIFIED / RESOLVED / PARTIAL / UNKNOWN) are coerced to
    their closest canonical status; unrecognized values stay NEEDS_HUMAN_REVIEW."""
    from app.schemas.verification import VerificationOutput

    cases = [
        (
            {"verification_status": "NOT_VERIFIED", "confidence": 0.9},
            VerificationStatus.NOT_RESOLVED,
        ),
        ({"verification_status": "RESOLVED", "confidence": 0.9}, VerificationStatus.VERIFIED),
        (
            {"verification_status": "PARTIAL", "confidence": 0.6},
            VerificationStatus.PARTIALLY_RESOLVED,
        ),
        (
            {"verification_status": "UNCLEAR", "confidence": 0.4},
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        ),
        (
            {"verification_status": "gibberish", "confidence": 0.5},
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        ),
        ({"verification_status": "VERIFIED", "confidence": 0.95}, VerificationStatus.VERIFIED),
    ]
    for payload, expected in cases:
        out = VerificationOutput(**payload)
        assert out.verification_status == expected, payload
    # confidence is optional and defaults to the low side (safe for gates)
    assert VerificationOutput(verification_status="VERIFIED").confidence == 0.0


@pytest.mark.asyncio
async def test_verify_critical_p1_always_review(client):
    """P1_CRITICAL order → human_review_required=True even with high confidence."""
    wtoken, wid = await _seed_worker(_unique_email("vf-p1-worker"))
    citizen = await _citizen_token(_unique_email("vf-p1-cit"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        priority="P1_CRITICAL",
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    fake = FakeAI(
        [
            _out(status=VerificationStatus.VERIFIED, confidence=0.95, review=False),
        ]
    )
    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        before_photo = next(p for p in order.photos if p.category == "BEFORE")
        after_photo = next(p for p in order.photos if p.category == "AFTER")
        input_data = VerificationInput(
            complaint_description="Deep pothole on the main road.",
            category="ROAD",
            before_key=before_photo.storage_key,
            after_key=after_photo.storage_key,
            before_photo_id=before_photo.id,
            after_photo_id=after_photo.id,
            priority_bucket="P1_CRITICAL",
        )
        run = await VerifyRepairAgent(ai=fake).run(
            db,
            work_order_id=uuid.UUID(order_id),
            complaint_id=uuid.UUID(cid),
            input_data=input_data,
        )

    assert run.status.value == "SUCCEEDED"
    verification = await _latest_verification(order_id)
    assert verification is not None
    # Critical P1 enforces review even with high confidence VERIFIED
    assert verification.human_review_required is True
    assert verification.verification_status == VerificationStatus.VERIFIED


@pytest.mark.asyncio
async def test_verify_config_settings():
    """Config smoke test: VERIFICATION_* settings are sane."""
    s = get_settings()
    assert s.VERIFICATION_LOW_CONFIDENCE == 0.55
    assert s.VERIFICATION_VERIFIED_MIN_CONFIDENCE == 0.75
    assert s.VERIFICATION_HUMAN_REVIEW_CRITICAL is True


# --------------------------------------------------------------------------- #
# API: auth required
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_auth_required(client):
    url = "/api/v1/work-orders/00000000-0000-0000-0000-000000000000"
    assert (await client.post(f"{url}/verify")).status_code == 401
    assert (await client.get(f"{url}/verification")).status_code == 401
    assert (await client.post(f"{url}/verification/review")).status_code == 401


@pytest.mark.asyncio
async def test_api_citizen_cannot_run_verify(client):
    citizen = await _citizen_token(_unique_email("vf-api-rbac"))
    r = await client.post(
        f"{_VERIFY}/00000000-0000-0000-0000-000000000000/verify",
        headers=_auth(citizen),
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_api_nonexistent_order_returns_404(client):
    otoken = await _staff_token(_unique_email("vf-api-404"))
    for method, path in [
        ("POST", "/verify"),
        ("GET", "/verification"),
    ]:
        r = await client.request(
            method,
            f"{_VERIFY}/00000000-0000-0000-0000-000000000000{path}",
            headers=_auth(otoken),
        )
        assert r.status_code == 404, r.text
    r = await client.post(
        f"{_VERIFY}/00000000-0000-0000-0000-000000000000/verification/review",
        json={"decision": "CONFIRM_VERIFIED"},
        headers=_auth(otoken),
    )
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# API: staff-only verify + review
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_staff_run_verify_and_review(client, monkeypatch):
    """Staff runs verify → gets result → confirms → verification reviewed."""
    citizen = await _citizen_token(_unique_email("vf-api-staff"))
    otoken = await _staff_token(_unique_email("vf-api-staff-officer"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-staff-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    fake = FakeAI(
        [
            _out(status=VerificationStatus.PARTIALLY_RESOLVED, confidence=0.8, review=True),
        ]
    )
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(ai=fake),
    )

    # Run verification
    r = await client.post(
        f"{_VERIFY}/{order_id}/verify",
        headers=_auth(otoken),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SUCCEEDED"
    assert body["result"] is not None
    assert body["result"]["verification_status"] == "PARTIALLY_RESOLVED"
    assert body["result"]["human_review_required"] is True

    # Read back the verification
    r2 = await client.get(
        f"{_VERIFY}/{order_id}/verification",
        headers=_auth(otoken),
    )
    assert r2.status_code == 200
    v = r2.json()
    assert v["verification_status"] == "PARTIALLY_RESOLVED"
    assert v["human_review_required"] is True

    # Review: confirm verified
    r3 = await client.post(
        f"{_VERIFY}/{order_id}/verification/review",
        json={"decision": "CONFIRM_VERIFIED", "note": "Looks good on site."},
        headers=_auth(otoken),
    )
    assert r3.status_code == 200, r3.text
    rev = r3.json()
    assert rev["reopened"] is False
    assert rev["work_order_status"] == WorkOrderStatus.COMPLETED.value
    assert rev["verification"]["verification_status"] == VerificationStatus.VERIFIED.value
    assert rev["verification"]["human_review_required"] is False
    assert rev["verification"]["review_note"] == "Looks good on site."

    # The assigned worker is notified of the AI result and the confirmed resolution.
    notif_w = await client.get("/api/v1/notifications", headers=_auth(wtoken))
    types_w = [n["notification_type"] for n in notif_w.json().get("items", [])]
    assert "AI_VERIFICATION_RESULT" in types_w
    assert "WORK_RESOLVED" in types_w


@pytest.mark.asyncio
async def test_api_review_reopens_order(client, monkeypatch):
    """REQUIRES_FOLLOWUP → order COMPLETED→IN_PROGRESS, complaint IN_PROGRESS."""
    citizen = await _citizen_token(_unique_email("vf-api-reopen"))
    otoken = await _staff_token(_unique_email("vf-api-reopen-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-reopen-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    fake = FakeAI(
        [
            _out(status=VerificationStatus.PARTIALLY_RESOLVED, confidence=0.7, review=True),
        ]
    )
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(ai=fake),
    )

    # Run
    r = await client.post(
        f"{_VERIFY}/{order_id}/verify",
        headers=_auth(otoken),
    )
    assert r.status_code == 200

    # Reopen
    r2 = await client.post(
        f"{_VERIFY}/{order_id}/verification/review",
        json={
            "decision": "REQUIRES_FOLLOWUP",
            "note": "Repaired area is uneven — redo needed.",
        },
        headers=_auth(otoken),
    )
    assert r2.status_code == 200, r2.text
    rev = r2.json()
    assert rev["reopened"] is True
    assert rev["work_order_status"] == WorkOrderStatus.IN_PROGRESS.value
    assert rev["verification"]["verification_status"] == VerificationStatus.NOT_RESOLVED.value

    # Work order is now IN_PROGRESS
    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        assert order.status == WorkOrderStatus.IN_PROGRESS
        assert order.completed_at is None
        # Complaint went back to IN_PROGRESS
        complaint = await db.get(Complaint, uuid.UUID(cid))
        assert complaint.status == ComplaintStatus.IN_PROGRESS

    # Worker and owner received WORK_ORDER_REOPENED notifications
    notif_r = await client.get(
        "/api/v1/notifications",
        headers=_auth(wtoken),
    )
    types = [n["notification_type"] for n in notif_r.json().get("items", [])]
    assert "WORK_ORDER_REOPENED" in types
    notif_c = await client.get(
        "/api/v1/notifications",
        headers=_auth(citizen),
    )
    types_c = [n["notification_type"] for n in notif_c.json().get("items", [])]
    assert "WORK_ORDER_REOPENED" in types_c


@pytest.mark.asyncio
async def test_api_review_requests_rework(client, monkeypatch):
    """REQUEST_REWORK → RETURNED_FOR_REWORK, rework_reason set, worker notified."""
    citizen = await _citizen_token(_unique_email("vf-api-rework"))
    otoken = await _staff_token(_unique_email("vf-api-rework-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-rework-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    fake = FakeAI(
        [
            _out(status=VerificationStatus.PARTIALLY_RESOLVED, confidence=0.7, review=True),
        ]
    )
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(ai=fake),
    )

    # Run verification (needs human review).
    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    assert r.json()["result"]["human_review_required"] is True

    # Officer requests rework.
    r2 = await client.post(
        f"{_VERIFY}/{order_id}/verification/review",
        json={"decision": "REQUEST_REWORK", "note": "Pothole not fully refilled."},
        headers=_auth(otoken),
    )
    assert r2.status_code == 200, r2.text
    rev = r2.json()
    assert rev["reopened"] is False
    assert rev["rework_requested"] is True
    assert rev["work_order_status"] == WorkOrderStatus.RETURNED_FOR_REWORK.value
    assert rev["verification"]["verification_status"] == VerificationStatus.NOT_RESOLVED.value

    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        assert order.status == WorkOrderStatus.RETURNED_FOR_REWORK
        assert order.rework_reason == "Pothole not fully refilled."
        # Evidence timestamps are KEPT until the worker restarts the rework.
        assert order.completed_at is not None
        # Complaint returned IN_PROGRESS (the seeded order was already RESOLVED).
        assert (await db.get(Complaint, uuid.UUID(cid))).status == ComplaintStatus.IN_PROGRESS
        from app.models import WorkOrderStatusHistory

        history = (
            (
                await db.execute(
                    select(WorkOrderStatusHistory).where(
                        WorkOrderStatusHistory.work_order_id == uuid.UUID(order_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "REWORK_REQUESTED" in [h.action for h in history]

    # Worker → REWORK_REQUESTED; complaint owner → WORK_ORDER_REOPENED.
    notif_w = await client.get("/api/v1/notifications", headers=_auth(wtoken))
    types_w = [n["notification_type"] for n in notif_w.json().get("items", [])]
    assert "REWORK_REQUESTED" in types_w
    notif_c = await client.get("/api/v1/notifications", headers=_auth(citizen))
    types_c = [n["notification_type"] for n in notif_c.json().get("items", [])]
    assert "WORK_ORDER_REOPENED" in types_c

    # Verification cannot be re-run on a returned-for-rework order (409).
    r3 = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r3.status_code == 409, r3.text


@pytest.mark.asyncio
async def test_api_double_review_returns_409(client, monkeypatch):
    """Reviewing an already-reviewed verification → 409."""
    citizen = await _citizen_token(_unique_email("vf-api-2x"))
    otoken = await _staff_token(_unique_email("vf-api-2x-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-2x-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    fake = FakeAI(
        [
            _out(status=VerificationStatus.VERIFIED, confidence=0.95, review=True),
        ]
    )
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(ai=fake),
    )

    await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    r = await client.post(
        f"{_VERIFY}/{order_id}/verification/review",
        json={"decision": "CONFIRM_VERIFIED"},
        headers=_auth(otoken),
    )
    assert r.status_code == 200

    # Second review on the same verification → 409
    r2 = await client.post(
        f"{_VERIFY}/{order_id}/verification/review",
        json={"decision": "CONFIRM_VERIFIED"},
        headers=_auth(otoken),
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_api_worker_cannot_run_verify_only_read(client, monkeypatch):
    """Assigned field worker can read verification but not run it."""
    citizen = await _citizen_token(_unique_email("vf-api-wk-read"))
    otoken = await _staff_token(_unique_email("vf-api-wk-read-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-wk-read-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    fake = FakeAI(
        [
            _out(status=VerificationStatus.VERIFIED, confidence=0.95),
        ]
    )
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(ai=fake),
    )
    # Staff runs verify
    await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))

    # Worker can read (GET) but not POST
    r = await client.get(
        f"{_VERIFY}/{order_id}/verification",
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "VERIFIED"

    r2 = await client.post(
        f"{_VERIFY}/{order_id}/verify",
        headers=_auth(wtoken),
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_api_complaint_owner_cannot_read(client, monkeypatch):
    """Verification is staff-only: officer reads, complaint owner is denied."""
    citizen = await _citizen_token(_unique_email("vf-api-owner"))
    otoken = await _staff_token(_unique_email("vf-api-owner-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-owner-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    fake = FakeAI(
        [
            _out(status=VerificationStatus.VERIFIED, confidence=0.95),
        ]
    )
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(ai=fake),
    )
    await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))

    # Officer reads successfully
    o = await client.get(
        f"{_VERIFY}/{order_id}/verification",
        headers=_auth(otoken),
    )
    assert o.status_code == 200, o.text
    assert o.json()["verification_status"] == "VERIFIED"

    # Complaint owner is denied
    r = await client.get(
        f"{_VERIFY}/{order_id}/verification",
        headers=_auth(citizen),
    )
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- #
# Part 30: officer-only resolution review (no AI auto-resolve)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_ai_verified_does_not_auto_resolve(client, monkeypatch):
    """A high-confidence AI VERIFIED is advisory — the complaint
    stays open until an officer reviews."""
    citizen = await _citizen_token(_unique_email("vf-api-nor"))
    otoken = await _staff_token(_unique_email("vf-api-nor-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-nor-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
        complaint_status=ComplaintStatus.IN_PROGRESS,
    )

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI([_out(status=VerificationStatus.VERIFIED, confidence=0.97, review=False)])
        ),
    )

    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["verification_status"] == "VERIFIED"
    assert result["human_review_required"] is False

    # Nothing resolved: order stays as-is and the complaint is NOT auto-resolved.
    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        assert order.status == WorkOrderStatus.COMPLETED
        complaint = await db.get(Complaint, uuid.UUID(cid))
        assert complaint.status == ComplaintStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_api_officer_review_confirms_ai_verified(client, monkeypatch):
    """Officer CONFIRM_VERIFIED after an AI VERIFIED completes order + resolves complaint."""
    citizen = await _citizen_token(_unique_email("vf-api-rc"))
    otoken = await _staff_token(_unique_email("vf-api-rc-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-rc-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
        complaint_status=ComplaintStatus.IN_PROGRESS,
    )

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI([_out(status=VerificationStatus.VERIFIED, confidence=0.96, review=False)])
        ),
    )

    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    assert r.json()["result"]["human_review_required"] is False

    # The officer still makes the call — and it is accepted (no gate on the AI flag).
    r2 = await client.post(
        f"{_VERIFY}/{order_id}/verification/review",
        json={"decision": "CONFIRM_VERIFIED", "note": "Confirmed after on-site check."},
        headers=_auth(otoken),
    )
    assert r2.status_code == 200, r2.text
    rev = r2.json()
    assert rev["reopened"] is False
    assert rev["rework_requested"] is False
    assert rev["work_order_status"] == WorkOrderStatus.COMPLETED.value
    assert rev["verification"]["reviewed_at"] is not None
    assert rev["verification"]["review_note"] == "Confirmed after on-site check."
    assert rev["verification"]["human_review_required"] is False

    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        assert order.status == WorkOrderStatus.COMPLETED
        complaint = await db.get(Complaint, uuid.UUID(cid))
        assert complaint.status == ComplaintStatus.RESOLVED


@pytest.mark.asyncio
async def test_api_run_verify_requires_before_photo(client):
    """Missing resolution evidence → 422 (the AI cannot be run without both photos)."""
    citizen = await _citizen_token(_unique_email("vf-api-ev422"))
    otoken = await _staff_token(_unique_email("vf-api-ev422-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-ev422-wk"))
    uid = uuid.UUID(decode_token(citizen, "access")["sub"])

    # A COMPLETED order with NO evidence photos (seed variant without photos).
    async with async_session_factory() as db:
        complaint = Complaint(
            description="Pothole reported but the worker never attached photos.",
            title="ROAD: Pothole reported but never photographed.",
            category="ROAD",
            status=ComplaintStatus.IN_PROGRESS,
            user_id=uid,
        )
        db.add(complaint)
        await db.flush()
        order = WorkOrder(
            complaint_id=complaint.id,
            department="ROAD",
            priority="P2_HIGH",
            location_lat=_LAT,
            location_lon=_LON,
            address="Test location",
            status=WorkOrderStatus.COMPLETED,
            worker_id=wid,
            sla_hours=24,
            created_by=None,
            completed_at=datetime.now(UTC),
        )
        db.add(order)
        await db.commit()
        order_id = str(order.id)

    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Before photo is required."


@pytest.mark.asyncio
async def test_api_evidence_bundle_and_rbac(client, monkeypatch):
    """Evidence endpoint returns the full review bundle; only staff may read it."""
    citizen = await _citizen_token(_unique_email("vf-api-ev"))
    otoken = await _staff_token(_unique_email("vf-api-ev-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-ev-wk"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    # Attach an original complaint photo so it flows into the bundle + AI input.
    async with async_session_factory() as db:
        complaint = await db.get(Complaint, uuid.UUID(cid))
        key = f"ev-test-{uuid.uuid4().hex}-original.png"
        get_storage().upload(key, _png_bytes(), "image/png")
        db.add(
            ComplaintMedia(
                complaint_id=complaint.id,
                user_id=complaint.user_id,
                media_type=MediaType.IMAGE,
                original_filename="original.png",
                storage_key=key,
                content_type="image/png",
                size_bytes=len(_png_bytes()),
            )
        )
        await db.commit()

    r = await client.get(f"{_VERIFY}/{order_id}/evidence", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    bundle = r.json()
    assert bundle["order_id"] == order_id
    assert bundle["order_status"] == "COMPLETED"
    assert bundle["complaint_id"] == cid
    assert bundle["complaint_title"].startswith("ROAD:")
    assert bundle["complaint_category"] == "ROAD"
    assert len(bundle["complaint_media"]) == 1
    assert bundle["complaint_media"][0]["media_type"] == "IMAGE"
    assert bundle["complaint_media"][0]["url"]
    assert bundle["worker_id"] is not None
    assert bundle["worker_name"] == "Verify Worker"
    assert bundle["completed_at"] is not None
    assert len(bundle["before_photos"]) == 1
    assert bundle["before_photos"][0]["category"] == "BEFORE"
    assert bundle["before_photos"][0]["uploaded_by_name"] == "Verify Worker"
    assert bundle["before_photos"][0]["url"]
    assert len(bundle["after_photos"]) == 1
    assert bundle["after_photos"][0]["category"] == "AFTER"

    # Staff-only: worker and complaint owner are denied.
    assert (
        await client.get(f"{_VERIFY}/{order_id}/evidence", headers=_auth(wtoken))
    ).status_code == 403
    assert (
        await client.get(f"{_VERIFY}/{order_id}/evidence", headers=_auth(citizen))
    ).status_code == 403

    # With the complaint photo attached, verification still runs (original key resolved).
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI([_out(status=VerificationStatus.VERIFIED, confidence=0.9)])
        ),
    )
    rrun = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert rrun.status_code == 200, rrun.text


@pytest.mark.asyncio
async def test_api_audit_trail_for_verify_review_evidence(client, monkeypatch):
    """Each verify / evidence-view / review step lands an auditable officer trail."""
    citizen = await _citizen_token(_unique_email("vf-api-aud"))
    otoken = await _staff_token(_unique_email("vf-api-aud-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-api-aud-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI(
                [_out(status=VerificationStatus.PARTIALLY_RESOLVED, confidence=0.8, review=True)]
            )
        ),
    )

    assert (
        await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    ).status_code == 200
    assert (
        await client.get(f"{_VERIFY}/{order_id}/evidence", headers=_auth(otoken))
    ).status_code == 200
    rev = await client.post(
        f"{_VERIFY}/{order_id}/verification/review",
        json={"decision": "CONFIRM_VERIFIED", "note": "Cleared."},
        headers=_auth(otoken),
    )
    assert rev.status_code == 200, rev.text

    async with async_session_factory() as db:
        rows = (
            (await db.execute(select(AuditLog).where(AuditLog.entity_id == str(order_id))))
            .scalars()
            .all()
        )
        actions = [a.action for a in rows]
        assert ACTION_WORK_ORDER_VERIFICATION_STARTED in actions
        assert ACTION_WORK_ORDER_VERIFICATION_COMPLETED in actions
        assert ACTION_WORK_ORDER_EVIDENCE_VIEWED in actions
        assert ACTION_WORK_ORDER_RESOLUTION_CONFIRMED in actions
        confirmed = next(a for a in rows if a.action == ACTION_WORK_ORDER_RESOLUTION_CONFIRMED)
        assert confirmed.after["decision"] == "CONFIRM_VERIFIED"
        assert confirmed.after["actor_role"] == RoleName.OFFICER.value
        assert all(a.after.get("actor_role") == RoleName.OFFICER.value for a in rows)


# --------------------------------------------------------------------------- #
# Provider failures: distinguish rate-limit / unavailable / analysis-failed
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_rate_limit_returns_retryable_provider_state(client, monkeypatch):
    """A Groq 429 does NOT look like 'verification failed': the response carries
    ai_status=PROVIDER_RATE_LIMITED, an explicit Retry-After hint, no result,
    and the response must not expose internal request IDs."""
    from app.services.ai_service import AIRateLimitError

    citizen = await _citizen_token(_unique_email("vf-rl-cit"))
    otoken = await _staff_token(_unique_email("vf-rl-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-rl-wk"))
    order_id, cid, _ = await _seed_completed_order(
        citizen,
        wid,
        before_color=(70, 60, 50),
        after_color=(200, 220, 90),
    )

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI([AIRateLimitError("Groq rate limited", retry_after_seconds=30.0)])
        ),
    )

    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["ai_status"] == "PROVIDER_RATE_LIMITED"
    assert body["retry_allowed"] is True
    assert body["retry_after_seconds"] == 30.0
    assert body["result"] is None
    assert body["message"]
    assert "rate limited" in body["message"].lower()
    # No internal request ID leaks into the officer-visible error.
    assert "request" not in (body["error"] or "").lower()

    # Provider failure is NOT an evidence failure: photos remain intact and no
    # verification verdict was persisted (nothing was faked).
    async with async_session_factory() as db:
        order = await _order_with_photos(order_id, db)
        assert len(order.photos) == 2
    assert await _latest_verification(order_id) is None


@pytest.mark.asyncio
async def test_api_provider_unavailable_is_retryable(client, monkeypatch):
    """Connection/timeout failures map to PROVIDER_UNAVAILABLE (retryable, not
    a rejection of the evidence)."""
    from app.services.ai_service import AIConnectionError

    citizen = await _citizen_token(_unique_email("vf-pu-cit"))
    otoken = await _staff_token(_unique_email("vf-pu-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-pu-wk"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI([AIConnectionError("cannot reach groq")]),
        ),
    )
    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["ai_status"] == "PROVIDER_UNAVAILABLE"
    assert body["retry_allowed"] is True
    assert body["result"] is None
    assert "temporarily unavailable" in body["message"].lower()
    assert await _latest_verification(order_id) is None


@pytest.mark.asyncio
async def test_api_analysis_failure_is_clearly_failed_but_retryable(client, monkeypatch):
    """A non-rate-limit provider error is ANALYSIS_FAILED — still retryable and
    not misclassified as a rate limit."""
    from app.services.ai_service import AIAPIError

    citizen = await _citizen_token(_unique_email("vf-af-cit"))
    otoken = await _staff_token(_unique_email("vf-af-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-af-wk"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI([AIAPIError("provider returned 500", code="server_error")])
        ),
    )
    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["ai_status"] == "ANALYSIS_FAILED"
    assert body["retry_allowed"] is True
    assert body["result"] is None
    assert await _latest_verification(order_id) is None


@pytest.mark.asyncio
async def test_api_rate_limit_preserves_prior_success(client, monkeypatch):
    """A rate-limit on a later retry must NOT erase a previously successful
    verification result."""
    from app.services.ai_service import AIRateLimitError

    citizen = await _citizen_token(_unique_email("vf-prior-cit"))
    otoken = await _staff_token(_unique_email("vf-prior-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-prior-wk"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    # First call succeeds, second call hits a rate limit.
    fake = FakeAI(
        [
            _out(status=VerificationStatus.VERIFIED, confidence=0.96, review=False),
            AIRateLimitError("Groq rate limited", retry_after_seconds=45.0),
        ]
    )
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(ai=fake),
    )

    r1 = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "SUCCEEDED"
    assert r1.json()["result"]["verification_status"] == "VERIFIED"

    r2 = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "FAILED"
    assert body["ai_status"] == "PROVIDER_RATE_LIMITED"
    assert body["retry_after_seconds"] == 45.0

    # The earlier successful verification is NOT overwritten by the failed run.
    v = await _latest_verification(order_id)
    assert v is not None
    assert v.verification_status == VerificationStatus.VERIFIED
    assert v.confidence == 0.96


@pytest.mark.asyncio
async def test_api_model_not_found_is_not_retryable(client, monkeypatch):
    """An unserved model id maps to MODEL_NOT_FOUND and must NOT invite a retry
    (the configuration has to change first)."""
    from app.services.ai_service import AIModelNotFoundError

    citizen = await _citizen_token(_unique_email("vf-mnf-cit"))
    otoken = await _staff_token(_unique_email("vf-mnf-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-mnf-wk"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI(
                [],
                preflight_exc=AIModelNotFoundError("groq has no model 'x'"),
            ),
        ),
    )
    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["ai_status"] == "MODEL_NOT_FOUND"
    assert body["retry_allowed"] is False
    assert body["result"] is None
    assert "VISION_MODEL" in body["message"]
    assert await _latest_verification(order_id) is None


@pytest.mark.asyncio
async def test_api_model_access_denied_is_not_retryable(client, monkeypatch):
    """A model the account cannot use maps to MODEL_ACCESS_DENIED (config change
    required, no retry loop)."""
    from app.services.ai_service import AIModelAccessDeniedError

    citizen = await _citizen_token(_unique_email("vf-mad-cit"))
    otoken = await _staff_token(_unique_email("vf-mad-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-mad-wk"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI([], preflight_exc=AIModelAccessDeniedError("denied")),
        ),
    )
    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["ai_status"] == "MODEL_ACCESS_DENIED"
    assert body["retry_allowed"] is False
    assert body["result"] is None


@pytest.mark.asyncio
async def test_api_configuration_error_is_not_retryable(client, monkeypatch):
    """A missing/invalid API key maps to CONFIGURATION and is not retryable."""
    from app.services.ai_service import AIConfigurationError

    citizen = await _citizen_token(_unique_email("vf-cfg-cit"))
    otoken = await _staff_token(_unique_email("vf-cfg-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-cfg-wk"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI([], preflight_exc=AIConfigurationError("no key")),
        ),
    )
    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["ai_status"] == "CONFIGURATION"
    assert body["retry_allowed"] is False
    assert "configured" in body["message"].lower()


@pytest.mark.asyncio
async def test_api_transient_preflight_failure_defers_to_real_call(client, monkeypatch):
    """A transient rate-limit during the pre-flight must NOT fail the run: the
    agent defers and the real call either succeeds or classifies the error."""
    from app.schemas.verification import VerificationOutput
    from app.services.ai_service import AIRateLimitError

    citizen = await _citizen_token(_unique_email("vf-tpr-cit"))
    otoken = await _staff_token(_unique_email("vf-tpr-off"))
    wtoken, wid = await _seed_worker(_unique_email("vf-tpr-wk"))
    order_id, cid, _ = await _seed_completed_order(citizen, wid)

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(
            ai=FakeAI(
                [
                    VerificationOutput(
                        repair_evidence="Asphalt patch visible.",
                        remaining_issue="",
                        confidence=0.97,
                        verification_status=VerificationStatus.VERIFIED,
                        issue_fixed=True,
                        human_review_required=False,
                    )
                ],
                preflight_exc=AIRateLimitError("rate limited", retry_after_seconds=5.0),
            ),
        ),
    )
    r = await client.post(f"{_VERIFY}/{order_id}/verify", headers=_auth(otoken))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SUCCEEDED"
    assert body["ai_status"] == "COMPLETED"
    assert body["result"]["verification_status"] == "VERIFIED"
