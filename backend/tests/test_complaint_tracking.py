"""Tests for complaint tracking: detail + timeline endpoints (Part 5).

Cover: valid detail fetch (full fields), invalid-complaint 404, ownership
RBAC (a citizen cannot read another citizen's complaint), unauthenticated 401,
the initial SUBMITTED timeline event on creation, and that a status change
appends a new event and updates the complaint's current status.

These run against the live development database and clean up after themselves.
"""

import io
import uuid

import pytest
from PIL import Image as PILImage
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import Role, User, UserProfile
from app.models.enums import ComplaintStatus, RoleName
from app.schemas.complaint import ComplaintDetailOut
from app.services import complaint_tracking_service
from app.services.auth_service import register_user

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _citizen_token(email: str) -> str:
    from app.schemas.auth import RegisterIn

    async with async_session_factory() as db:
        await register_user(
            db, RegisterIn(email=email, password=_PASSWORD, full_name="Citizen Tracker")
        )
        user = await db.scalar(select(User).where(User.email == email))
        role_name = await db.scalar(select(Role.name).where(Role.id == user.role_id))
    return create_access_token(str(user.id), role_name or RoleName.CITIZEN.value)


async def _staff_token(email: str, role: RoleName) -> str:
    async with async_session_factory() as db:
        role_row = await db.scalar(select(Role).where(Role.name == role.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Staff Tracker",
            role_id=role_row.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        uid = str(user.id)
    return create_access_token(uid, role.value)


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (64, 64), color=(70, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


async def _create_complaint(client, token: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"{_BASE}/media",
        files={"file": ("photo.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    media_id = resp.json()["id"]

    resp = await client.post(
        _BASE,
        json={
            "description": "Broken traffic signal at the main junction.",
            "category": "ROAD",
            "media_ids": [media_id],
            "location": {
                "latitude": 18.5204,
                "longitude": 73.8567,
                "address": "Main Junction",
                "source": "gps",
                "geopoint_denied": False,
            },
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_complaint_detail_returns_full_fields(client):
    email = _unique_email("trk-detail")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}
    complaint_id = await _create_complaint(client, token)

    resp = await client.get(f"{_BASE}/{complaint_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == complaint_id
    assert data["status"] == "SUBMITTED"
    assert data["category"] == "ROAD"
    assert data["description"].startswith("Broken traffic signal")
    assert data["media"], "detail should include attached media"
    assert data["complaint_location"]["source"] == "gps"
    assert "created_at" in data
    assert "priority" in data

    await _delete_user(email)


@pytest.mark.asyncio
async def test_complaint_detail_invalid_id_404(client):
    email = _unique_email("trk-invalid")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get(f"{_BASE}/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404, resp.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_complaint_detail_forbids_other_citizen(client):
    owner_email = _unique_email("trk-owner")
    other_email = _unique_email("trk-other")
    owner_token = await _citizen_token(owner_email)
    other_token = await _citizen_token(other_email)

    complaint_id = await _create_complaint(client, owner_token)

    resp = await client.get(
        f"{_BASE}/{complaint_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403, resp.text

    await _delete_user(owner_email)
    await _delete_user(other_email)


@pytest.mark.asyncio
async def test_complaint_detail_requires_auth(client):
    resp = await client.get(f"{_BASE}/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_complaint_timeline_initial_event_and_ordering(client):
    email = _unique_email("trk-timeline")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}
    complaint_id = await _create_complaint(client, token)

    resp = await client.get(f"{_BASE}/{complaint_id}/timeline", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["complaint_id"] == complaint_id
    assert data["current_status"] == "SUBMITTED"
    assert data["events"], "a fresh complaint should have a SUBMITTED event"
    assert data["events"][0]["status"] == "SUBMITTED"
    assert data["events"][0]["note"] == "Complaint submitted by citizen."

    # Events are returned in chronological order.
    stamps = [e["recorded_at"] for e in data["events"]]
    assert stamps == sorted(stamps)

    await _delete_user(email)


@pytest.mark.asyncio
async def test_status_change_appends_history_and_updates_status(client):
    citizen_email = _unique_email("trk-cit")
    officer_email = _unique_email("trk-off")
    citizen_token = await _citizen_token(citizen_email)
    await _staff_token(officer_email, RoleName.OFFICER)

    complaint_id = await _create_complaint(client, citizen_token)

    # Officer transitions the complaint under review.
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == officer_email))
        status = await complaint_tracking_service.transition_complaint(
            db,
            user,
            uuid.UUID(complaint_id),
            ComplaintStatus.IN_PROGRESS,
            note="Investigation started by officer.",
        )
        assert isinstance(status, ComplaintDetailOut)
        assert status.status == ComplaintStatus.IN_PROGRESS

    # Timeline now shows both the initial and the transition event.
    resp = await client.get(
        f"{_BASE}/{complaint_id}/timeline",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["current_status"] == "IN_PROGRESS"
    assert len(data["events"]) == 2
    assert data["events"][-1]["status"] == "IN_PROGRESS"
    assert data["events"][-1]["note"] == "Investigation started by officer."

    # The citizen's own detail reflects the new status too.
    resp = await client.get(
        f"{_BASE}/{complaint_id}",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "IN_PROGRESS"

    await _delete_user(citizen_email)
    await _delete_user(officer_email)


@pytest.mark.asyncio
async def test_malformed_complaint_id_422(client):
    email = _unique_email("trk-malformed")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get(f"{_BASE}/not-a-uuid", headers=headers)
    assert resp.status_code == 422, resp.text

    await _delete_user(email)
