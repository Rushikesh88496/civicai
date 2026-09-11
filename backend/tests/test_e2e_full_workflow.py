"""PART 30 — End-to-end platform workflow test.

Chains the complete citizen lifecycle through the live (dev) API stack and the
real shared database, in a single request-driven flow:

    register → login → submit complaint (image + GPS) → triage → vision →
    duplicate detection → context enrichment → priority → routing → dispatch
    (officer review) → work order → worker assign/accept → check-in → start →
    before photo → repair (notes) → after photo → complete → AI verification →
    human review → citizen notification → citizen feedback → analytics update.

LLM/embedding backends are faked exactly as the rest of the suite does (no Groq
or ONNX model downloads), but *every HTTP endpoint*, persistence layer, state
transition, RBAC gate and notification are real. See test_ai_operations.py for
the Groq wiring / schema-validation / fallback checks.
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.agents.correlation_agent import CorrelationAgent
from app.agents.triage_agent import TriageAgent
from app.agents.verify_repair_agent import VerifyRepairAgent
from app.agents.vision_agent import VisionAgent
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    Complaint,
    Department,
    FieldWorker,
    Role,
    User,
    UserProfile,
    WorkerAssignment,
    WorkOrder,
    WorkOrderPhoto,
)
from app.models.enums import (
    AgentStatus,
    ComplaintCategory,
    ComplaintStatus,
    RoleName,
    TriageSeverity,
    TriageUrgency,
    VerificationStatus,
    WorkerStatus,
    WorkOrderStatus,
)
from app.schemas.triage import TriageOutput
from app.schemas.verification import VerificationOutput
from app.schemas.vision import VisionOutput
from app.services.embedding_service import EmbeddingService
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_API = "/api/v1"
_LAT = 17.4327
_LON = 78.3885
_SETTINGS = get_settings()


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeTriageAI:
    async def structured_completion(self, messages, schema, **kwargs):
        return TriageOutput(
            category=ComplaintCategory.GARBAGE,
            severity=TriageSeverity.HIGH,
            urgency=TriageUrgency.HIGH,
            infrastructure_type="waste bin",
            summary="Overflowing garbage bin collected.",
            confidence=0.93,
            recommended_action="Route to waste crew.",
        )


class FakeVisionAI:
    async def structured_vision_completion(self, content, schema, **kwargs):
        return VisionOutput(
            visual_evidence_detected=True,
            detected_issue="garbage pile",
            severity=TriageSeverity.HIGH,
            confidence=0.91,
            evidence_description="Visible garbage pile in the attached photo.",
            mismatch_detected=False,
            human_review_required=False,
        )


class FakeVerifyAI:
    async def structured_vision_completion(self, content, schema, **kwargs):
        return VerificationOutput(
            repair_evidence="AFTER photo shows the area cleared of garbage.",
            remaining_issue="",
            confidence=0.94,
            verification_status=VerificationStatus.VERIFIED,
            issue_fixed=True,
            human_review_required=True,
        )


class FakeEmbedder:
    """Deterministic 384-dim embedder (no ONNX download)."""

    model = "test-shingle"

    def embed(self, text: str) -> list[float]:
        return [float(hash(text.strip().lower()) % 1000) / 1000.0] * 384


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _valid_png(color: tuple[int, int, int, int] = (0, 0, 0, 255)) -> bytes:
    """Deterministic solid-color PNG (default black).

    BEFORE / AFTER photos must differ so the verify agent's pixel-identical
    short-circuit is not triggered and the (faked) vision call actually runs.
    """
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGBA", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


async def _staff_token(email: str, role: RoleName) -> str:
    async with async_session_factory() as db:
        r = await db.scalar(select(Role).where(Role.name == role.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=f"{role.value} e2e",
            role_id=r.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), role.value)


async def _seed_worker(email: str) -> str:
    """Create an active WASTE worker at the complaint coords; return token."""
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="E2E Worker",
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
        db.add(
            FieldWorker(
                user_id=user.id,
                department_id=dept.id,
                status=WorkerStatus.ACTIVE,
                home_latitude=_LAT,
                home_longitude=_LON,
                skill_tags=["waste-audit", "collections"],
                equipment=["garbage-truck"],
            )
        )
        await db.commit()
        return create_access_token(str(user.id), RoleName.FIELD_WORKER.value)


async def _clear_workers() -> None:
    """Empty the worker pool (and per-run e2e data) so dispatch is deterministic."""
    async with async_session_factory() as db:
        # Delete work orders + complaints first: their children (status history,
        # assignments, photos, verifications, ratings, media, ...) cascade, which
        # also releases the NOT NULL worker + RESTRICT actor FKs on users.
        await db.execute(delete(WorkerAssignment))
        await db.execute(delete(WorkOrder))
        await db.execute(delete(Complaint))
        fws = (await db.execute(select(FieldWorker))).scalars().all()
        for fw in fws:
            await db.delete(fw)
        role = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        users = (await db.execute(select(User).where(User.role_id == role.id))).scalars().all()
        for u in users:
            await db.delete(u)
        await db.execute(delete(WorkOrderPhoto))
        await db.commit()


async def _register_via_api(client, email: str) -> dict:
    async with async_session_factory() as db:
        ward_id = await any_active_ward_id(db)
    r = await client.post(
        f"{_API}/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "full_name": "E2E Citizen",
            "ward_id": str(ward_id),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _notification_types(client, token: str) -> set[str]:
    r = await client.get(f"{_API}/notifications", headers=_auth(token))
    assert r.status_code == 200, r.text
    return {n["notification_type"] for n in r.json().get("items", [])}


@pytest.fixture(autouse=True)
async def _e2e_cleanup():
    yield
    _ = delete(WorkOrderPhoto)  # referenced by order cleanup below


# --------------------------------------------------------------------------- #
# The full happy-path workflow
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_full_citizen_to_analytics_workflow(client, monkeypatch):
    await _clear_workers()

    # --- Agents: fake AI/embedding backends, real everything else ------------
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    monkeypatch.setattr(
        "app.services.triage_service._agent", lambda: TriageAgent(ai=FakeTriageAI())
    )
    monkeypatch.setattr(
        "app.services.vision_service._agent", lambda: VisionAgent(ai=FakeVisionAI())
    )
    monkeypatch.setattr(
        "app.services.correlation_service._agent",
        lambda: CorrelationAgent(embedding_service=EmbeddingService(embedder=FakeEmbedder())),
    )
    monkeypatch.setattr(
        "app.services.verify_repair_service._agent", lambda: VerifyRepairAgent(ai=FakeVerifyAI())
    )

    # --- 1. Citizen registers (real auth endpoint) -----------------------------
    citizen_email = _unique_email("e2e-citizen")
    reg = await _register_via_api(client, citizen_email)
    citizen_token = reg["tokens"]["access_token"]

    # --- 2. Citizen logs in (real auth endpoint) --------------------------------
    login = await client.post(
        f"{_API}/auth/login",
        json={"email": citizen_email, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    citizen_token = login.json()["tokens"]["access_token"]

    # --- 3. Image upload --------------------------------------------------------
    up = await client.post(
        f"{_API}/complaints/media",
        files={"file": ("garbage.png", _valid_png(), "image/png")},
        headers=_auth(citizen_token),
    )
    assert up.status_code == 201, up.text
    media_id = up.json()["id"]

    # --- 4. Submit complaint with GPS -------------------------------------------
    comp = await client.post(
        f"{_API}/complaints",
        json={
            "description": "Overflowing garbage bin near the bus stop for several days.",
            "category": "GARBAGE",
            "media_ids": [media_id],
            "location": {
                "latitude": _LAT,
                "longitude": _LON,
                "address": "12 Main Road",
                "source": "gps",
                "geopoint_denied": False,
            },
        },
        headers=_auth(citizen_token),
    )
    assert comp.status_code == 201, comp.text
    cid = comp.json()["id"]
    assert comp.json()["status"] == "SUBMITTED"
    assert comp.json()["media"][0]["id"] == media_id
    assert comp.json()["location"] == "12 Main Road"

    # Citizen notified on submission
    assert "COMPLAINT_RECEIVED" in await _notification_types(client, citizen_token)

    # Officer who runs/reviews the operational pipeline
    officer_token = await _staff_token(_unique_email("e2e-officer"), RoleName.OFFICER)

    # --- 5-10. AI + deterministic agents ----------------------------------------
    triage = await client.post(f"{_API}/complaints/{cid}/triage", headers=_auth(officer_token))
    assert triage.status_code == 200, triage.text
    assert triage.json()["status"] == AgentStatus.SUCCEEDED.value

    vision = await client.post(f"{_API}/complaints/{cid}/vision", headers=_auth(officer_token))
    assert vision.status_code == 200, vision.text
    assert vision.json()["status"] == AgentStatus.SUCCEEDED.value
    assert vision.json()["result"]["visual_evidence_detected"] is True

    corr = await client.post(f"{_API}/complaints/{cid}/correlate", headers=_auth(officer_token))
    assert corr.status_code == 200, corr.text
    assert corr.json()["status"] == AgentStatus.SUCCEEDED.value

    ctx = await client.post(f"{_API}/complaints/{cid}/context", headers=_auth(officer_token))
    assert ctx.status_code == 200, ctx.text
    assert ctx.json()["status"] == AgentStatus.SUCCEEDED.value

    prio = await client.post(f"{_API}/complaints/{cid}/priority", headers=_auth(officer_token))
    assert prio.status_code == 200, prio.text
    assert prio.json()["status"] == AgentStatus.SUCCEEDED.value

    route = await client.post(f"{_API}/complaints/{cid}/routing", headers=_auth(officer_token))
    assert route.status_code == 200, route.text
    assert route.json()["status"] == AgentStatus.SUCCEEDED.value
    assert route.json()["result"]["primary_department"] == "WASTE"

    # Complaint advanced through the agent stages
    detail = await client.get(f"{_API}/complaints/{cid}", headers=_auth(citizen_token))
    assert detail.status_code == 200
    assert detail.json()["status"] == ComplaintStatus.EVIDENCE_VERIFIED.value

    # Priorities persisted as history
    ph = await client.get(f"{_API}/complaints/{cid}/priority-history", headers=_auth(officer_token))
    assert ph.status_code == 200
    assert len(ph.json()["entries"]) >= 1

    # --- 11. Dispatch → draft work order -----------------------------------------
    worker_token = await _seed_worker(_unique_email("e2e-worker"))

    disp = await client.post(f"{_API}/complaints/{cid}/dispatch", headers=_auth(officer_token))
    assert disp.status_code == 201, disp.text
    wid = disp.json()["work_order_id"]
    assert disp.json()["status"] == "SUCCEEDED"
    recommended = disp.json()["result"]["recommendation"]["recommended_worker_id"]
    assert recommended

    # Citizen notified of work order
    assert "WORK_ORDER_CREATED" in await _notification_types(client, citizen_token)

    # --- 12. Officer review: approve → ASSIGNED ----------------------------------
    ap = await client.post(
        f"{_API}/work-orders/{wid}/approve", json={"note": "go"}, headers=_auth(officer_token)
    )
    assert ap.status_code == 200, ap.text
    assert ap.json()["work_order"]["status"] == WorkOrderStatus.ASSIGNED.value

    # Citizen + worker notified of assignment
    assert "WORKER_ASSIGNED" in await _notification_types(client, citizen_token)

    # --- 13. Worker lifecycle ------------------------------------------------------
    dash = await client.get(f"{_API}/worker/dashboard", headers=_auth(worker_token))
    assert dash.status_code == 200
    assigned = dash.json().get("assigned", [])
    assert any(j["id"] == wid for j in assigned)

    acc = await client.post(
        f"{_API}/worker/orders/{wid}/accept",
        json={"note": "On my way", "client_ref": "e2e-accept"},
        headers=_auth(worker_token),
    )
    assert acc.status_code == 200, acc.text

    checkin = await client.post(
        f"{_API}/worker/orders/{wid}/check-in",
        json={"activity_type": "EN_ROUTE", "client_ref": "e2e-enroute"},
        headers=_auth(worker_token),
    )
    assert checkin.status_code == 200, checkin.text

    start = await client.post(
        f"{_API}/worker/orders/{wid}/start",
        json={"client_ref": "e2e-start"},
        headers=_auth(worker_token),
    )
    assert start.status_code == 200, start.text
    assert start.json()["work_order"]["status"] == WorkOrderStatus.IN_PROGRESS.value

    # Complaint advanced to IN_PROGRESS
    detail = await client.get(f"{_API}/complaints/{cid}", headers=_auth(citizen_token))
    assert detail.json()["status"] == ComplaintStatus.IN_PROGRESS.value

    # Before photo
    before = await client.post(
        f"{_API}/worker/orders/{wid}/photos",
        files={"file": ("before.png", _valid_png(), "image/png")},
        data={"category": "BEFORE", "client_ref": "e2e-before"},
        headers=_auth(worker_token),
    )
    assert before.status_code == 200, before.text
    assert before.json()["work_order"]["has_before_photo"] is True

    notes = await client.post(
        f"{_API}/worker/orders/{wid}/notes",
        json={
            "notes": "Cleared the overflowing bin, next pickup scheduled.",
            "client_ref": "e2e-note",
        },
        headers=_auth(worker_token),
    )
    assert notes.status_code == 200, notes.text

    # After photo
    after = await client.post(
        f"{_API}/worker/orders/{wid}/photos",
        files={"file": ("after.png", _valid_png((255, 255, 255, 255)), "image/png")},
        data={"category": "AFTER", "client_ref": "e2e-after"},
        headers=_auth(worker_token),
    )
    assert after.status_code == 200, after.text
    assert after.json()["work_order"]["has_after_photo"] is True

    finish = await client.post(
        f"{_API}/worker/orders/{wid}/finish",
        json={"notes": "Repair complete.", "client_ref": "e2e-finish"},
        headers=_auth(worker_token),
    )
    assert finish.status_code == 200, finish.text
    assert finish.json()["work_order"]["status"] == WorkOrderStatus.WORK_COMPLETED.value

    # The worker finishing work must NOT resolve the complaint (resolution is
    # confirmed by the verification stage, not the worker).
    detail = await client.get(f"{_API}/complaints/{cid}", headers=_auth(citizen_token))
    assert detail.json()["status"] == ComplaintStatus.IN_PROGRESS.value
    assert "WORK_ORDER_COMPLETED" not in await _notification_types(client, citizen_token)

    evid = await client.post(
        f"{_API}/worker/orders/{wid}/submit-evidence",
        json={"notes": "Before/after photos attached.", "client_ref": "e2e-submit-evidence"},
        headers=_auth(worker_token),
    )
    assert evid.status_code == 200, evid.text
    assert evid.json()["work_order"]["status"] == WorkOrderStatus.EVIDENCE_SUBMITTED.value
    assert evid.json()["work_order"]["evidence_submitted_at"] is not None

    # Still not resolved until the verification stage confirms it.
    detail = await client.get(f"{_API}/complaints/{cid}", headers=_auth(citizen_token))
    assert detail.json()["status"] == ComplaintStatus.IN_PROGRESS.value
    assert "WORK_ORDER_COMPLETED" not in await _notification_types(client, citizen_token)
    assert "REPAIR_STARTED" in await _notification_types(client, citizen_token)

    # --- 14. Resolution verification + human review ----------------------------
    ver = await client.post(f"{_API}/work-orders/{wid}/verify", headers=_auth(officer_token))
    assert ver.status_code == 200, ver.text
    assert ver.json()["status"] == "SUCCEEDED"
    assert ver.json()["result"]["verification_status"] == VerificationStatus.VERIFIED.value

    rev = await client.post(
        f"{_API}/work-orders/{wid}/verification/review",
        json={"decision": "CONFIRM_VERIFIED", "note": "Confirmed on site."},
        headers=_auth(officer_token),
    )
    assert rev.status_code == 200, rev.text
    assert rev.json()["reopened"] is False
    assert rev.json()["verification"]["verification_status"] == VerificationStatus.VERIFIED.value

    # Confirmation is what resolves the complaint + completes the order.
    detail = await client.get(f"{_API}/complaints/{cid}", headers=_auth(citizen_token))
    assert detail.json()["status"] == ComplaintStatus.RESOLVED.value
    assert "WORK_ORDER_COMPLETED" in await _notification_types(client, citizen_token)

    rev_detail = await client.get(f"{_API}/worker/orders/{wid}", headers=_auth(worker_token))
    assert rev_detail.json()["work_order"]["status"] == WorkOrderStatus.COMPLETED.value
    history = {h["action"] for h in rev_detail.json()["status_history"]}
    assert "RESOLUTION_CONFIRMED" in history

    # --- 15. Citizen feedback ----------------------------------------------------
    rate = await client.post(
        f"{_API}/complaints/{cid}/rating",
        json={"rating": 5, "comment": "Fast resolution, great work."},
        headers=_auth(citizen_token),
    )
    assert rate.status_code == 201, rate.text

    # Double rating rejected (domain rule)
    rate2 = await client.post(
        f"{_API}/complaints/{cid}/rating",
        json={"rating": 4},
        headers=_auth(citizen_token),
    )
    assert rate2.status_code == 409

    # --- 16. Analytics reflects the full journey -------------------------------
    ov = await client.get(f"{_API}/analytics/overview", headers=_auth(officer_token))
    assert ov.status_code == 200, ov.text
    kpis = ov.json()["kpis"]
    assert kpis["total_complaints"] >= 1
    assert kpis["satisfaction_count"] >= 1
    assert 1 <= kpis["satisfaction_avg"] <= 5

    # Complaint timeline shows the status journey
    tl = await client.get(f"{_API}/complaints/{cid}/timeline", headers=_auth(citizen_token))
    assert tl.status_code == 200
    statuses = [e["status"] for e in tl.json().get("events", [])]
    assert ComplaintStatus.SUBMITTED.value in statuses
    assert ComplaintStatus.RESOLVED.value in statuses


# --------------------------------------------------------------------------- #
# Reopen path: REQUIRES_FOLLOWUP reopens the order and notifies both parties
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_verification_reopen_cycle(client, monkeypatch):
    """Happy path with a follow-up: verify → REQUIRES_FOLLOWUP → redo → verify."""
    await _clear_workers()
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_URL", "")
    monkeypatch.setattr(_SETTINGS, "ROUTING_API_KEY", "")
    responses = {
        "first": VerificationOutput(
            repair_evidence="Partial cleanup only.",
            remaining_issue="Bin still overflowing.",
            confidence=0.7,
            verification_status=VerificationStatus.PARTIALLY_RESOLVED,
            issue_fixed=False,
            human_review_required=True,
        ),
        "second": VerificationOutput(
            repair_evidence="Area fully cleared.",
            remaining_issue="",
            confidence=0.96,
            verification_status=VerificationStatus.VERIFIED,
            issue_fixed=True,
            human_review_required=True,
        ),
    }
    state = {"i": 0}

    class ReopenVerifyAI:
        async def structured_vision_completion(self, content, schema, **kwargs):
            out = responses["first" if state["i"] == 0 else "second"]
            state["i"] += 1
            return out

    monkeypatch.setattr(
        "app.services.verify_repair_service._agent",
        lambda: VerifyRepairAgent(ai=ReopenVerifyAI()),
    )

    citizen_email = _unique_email("e2e-reopen")
    reg = await _register_via_api(client, citizen_email)
    citizen_token = reg["tokens"]["access_token"]
    comp = await client.post(
        f"{_API}/complaints",
        json={
            "description": "Pothole on the main road needs repaving.",
            "category": "ROAD",
            "media_ids": [],
            "location": {
                "latitude": _LAT,
                "longitude": _LON,
                "address": "Main Road",
                "source": "gps",
                "geopoint_denied": False,
            },
        },
        headers=_auth(citizen_token),
    )
    cid = comp.json()["id"]
    worker_token = await _seed_worker(_unique_email("e2e-reopen-worker"))
    officer_token = await _staff_token(_unique_email("e2e-reopen-officer"), RoleName.OFFICER)

    disp = await client.post(f"{_API}/complaints/{cid}/dispatch", headers=_auth(officer_token))
    wid = disp.json()["work_order_id"]
    await client.post(
        f"{_API}/work-orders/{wid}/approve",
        json={"note": "go"},
        headers=_auth(officer_token),
    )
    # Worker lifecycle: accept → GPS check-in → start (start is gated on check-in).
    await client.post(f"{_API}/worker/orders/{wid}/accept", json={}, headers=_auth(worker_token))
    await client.post(
        f"{_API}/worker/orders/{wid}/check-in",
        json={"activity_type": "ARRIVED", "client_ref": "reopen-cin"},
        headers=_auth(worker_token),
    )
    await client.post(f"{_API}/worker/orders/{wid}/start", headers=_auth(worker_token))
    for cat, color in (("BEFORE", (0, 0, 0, 255)), ("AFTER", (255, 255, 255, 255))):
        await client.post(
            f"{_API}/worker/orders/{wid}/photos",
            files={"file": (f"{cat.lower()}.png", _valid_png(color), "image/png")},
            data={"category": cat},
            headers=_auth(worker_token),
        )
    await client.post(
        f"{_API}/worker/orders/{wid}/finish",
        json={"client_ref": "reopen-finish-1"},
        headers=_auth(worker_token),
    )
    await client.post(
        f"{_API}/worker/orders/{wid}/submit-evidence",
        json={"client_ref": "reopen-evidence-1"},
        headers=_auth(worker_token),
    )

    # First verification requires follow-up
    ver1 = await client.post(f"{_API}/work-orders/{wid}/verify", headers=_auth(officer_token))
    assert ver1.status_code == 200
    assert ver1.json()["result"]["human_review_required"] is True

    rev1 = await client.post(
        f"{_API}/work-orders/{wid}/verification/review",
        json={"decision": "REQUIRES_FOLLOWUP", "note": "Redo needed."},
        headers=_auth(officer_token),
    )
    assert rev1.status_code == 200, rev1.text
    assert rev1.json()["reopened"] is True
    assert rev1.json()["work_order_status"] == WorkOrderStatus.IN_PROGRESS.value

    # Both parties notified of the reopen
    assert "WORK_ORDER_REOPENED" in await _notification_types(client, citizen_token)
    assert "WORK_ORDER_REOPENED" in await _notification_types(client, worker_token)

    # Worker redoes the job (order was reopened to IN_PROGRESS, so no second start)
    await client.post(
        f"{_API}/worker/orders/{wid}/finish",
        json={"client_ref": "reopen-finish-2"},
        headers=_auth(worker_token),
    )
    await client.post(
        f"{_API}/worker/orders/{wid}/submit-evidence",
        json={"client_ref": "reopen-evidence-2"},
        headers=_auth(worker_token),
    )

    # Second verification confirms
    ver2 = await client.post(f"{_API}/work-orders/{wid}/verify", headers=_auth(officer_token))
    assert ver2.status_code == 200, ver2.text
    assert ver2.json()["result"]["verification_status"] == VerificationStatus.VERIFIED.value
    rev2 = await client.post(
        f"{_API}/work-orders/{wid}/verification/review",
        json={"decision": "CONFIRM_VERIFIED", "note": "All good."},
        headers=_auth(officer_token),
    )
    assert rev2.status_code == 200
    assert rev2.json()["reopened"] is False
