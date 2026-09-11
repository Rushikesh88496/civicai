"""Tests for the multimodal complaint submission flow (Part 4).

Cover: complete submission with GPS, invalid/empty inputs, multiple file
uploads, GPS-denied (manual) location, unsupported/oversized files, and
storage (network) failure handling.

These run against the live development database and clean up after themselves.
"""

import io
import uuid

import pytest
from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import Complaint, User
from app.models.enums import RoleName
from app.services.auth_service import register_user
from tests.helpers import any_active_ward_id

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
            db, RegisterIn(
                    email=email,
                    password=_PASSWORD,
                    full_name="Citizen Test",
                    ward_id=await any_active_ward_id(db),
                )
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), RoleName.CITIZEN.value)


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (64, 64), color=(120, 30, 90)).save(buf, format="JPEG")
    return buf.getvalue()


def _image_bytes(content_type: str) -> bytes:
    """Return valid image bytes for a given content type."""
    buf = io.BytesIO()
    if content_type == "image/png":
        PILImage.new("RGB", (32, 32), color=(10, 80, 120)).save(buf, format="PNG")
    elif content_type == "image/webp":
        PILImage.new("RGB", (32, 32), color=(220, 180, 40)).save(buf, format="WEBP")
    elif content_type == "image/gif":
        PILImage.new("RGB", (32, 32), color=(40, 200, 90)).save(buf, format="GIF")
    else:
        PILImage.new("RGB", (64, 64), color=(120, 30, 90)).save(buf, format="JPEG")
    return buf.getvalue()


def _mp4_bytes() -> bytes:
    # Minimal payload whose bytes start with the MP4/QuickTime signature
    # (0x000000) + a box size, followed by 'ftyp'. Only the signature is
    # checked server-side, so this is enough for a valid upload.
    return b"\x00\x00\x00\x18ftypisom" + bytes(range(0, 64))


@pytest.mark.asyncio
async def test_upload_and_submit_complete_with_gps(client):
    email = _unique_email("comp-gps")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    files = {
        "file": ("photo.jpg", _jpeg_bytes(), "image/jpeg"),
    }
    up = await client.post(f"{_BASE}/media", files=files, headers=headers)
    assert up.status_code == 201, up.text
    media = up.json()
    assert media["media_type"] == "IMAGE"
    assert media["size_bytes"] > 0

    payload = {
        "description": "Deep pothole blocking the whole lane.",
        "category": "ROAD",
        "media_ids": [media["id"]],
        "location": {
            "latitude": 18.5204,
            "longitude": 73.8567,
            "address": "Near Market Street, Downtown",
            "source": "gps",
            "geopoint_denied": False,
            # Device-reported GPS horizontal accuracy in metres (Part 31).
            "accuracy_m": 12.34,
        },
    }
    resp = await client.post(_BASE, json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "SUBMITTED"
    assert data["category"] == "ROAD"
    assert data["media"], "created complaint should include uploaded media"
    assert data["media"][0]["id"] == media["id"]

    # The media row is now attached and a geometry+accuracy point was stored.
    async with async_session_factory() as db:
        complaint = await db.scalar(
            select(Complaint)
            .where(Complaint.id == uuid.UUID(data["id"]))
            .options(selectinload(Complaint.media), selectinload(Complaint.complaint_location))
        )
        assert complaint is not None
        assert len(complaint.media) == 1
        assert complaint.complaint_location is not None
        assert complaint.complaint_location.source == "gps"
        assert complaint.complaint_location.geopoint_denied is False
        assert complaint.complaint_location.accuracy_m == pytest.approx(12.3)

    await _delete_user(email)


@pytest.mark.asyncio
async def test_submit_empty_description_rejected(client):
    email = _unique_email("comp-empty")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        _BASE,
        json={"description": "   ", "category": "ROAD"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_submit_invalid_category_rejected(client):
    email = _unique_email("comp-badcat")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        _BASE,
        json={"description": "A valid short description.", "category": "NOT_A_CATEGORY"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_upload_multiple_images(client):
    email = _unique_email("comp-multi")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    ids = []
    for name in ("a.jpg", "b.png", "c.jpg"):
        content_type = "image/png" if name.endswith("png") else "image/jpeg"
        up = await client.post(
            f"{_BASE}/media",
            files={"file": (name, _image_bytes(content_type), content_type)},
            headers=headers,
        )
        assert up.status_code == 201, up.text
        ids.append(up.json()["id"])
    assert len(ids) == 3

    # Submit all three on one complaint.
    resp = await client.post(
        _BASE,
        json={
            "description": "Multiple photos of the same issue.",
            "category": "GARBAGE",
            "media_ids": ids,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert len(data["media"]) == 3

    await _delete_user(email)


@pytest.mark.asyncio
async def test_submit_location_gps_denied_manual(client):
    email = _unique_email("comp-denied")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "description": "Streetlight flickering outside the school gate.",
        "category": "STREET_LIGHTING",
        "location": {
            "latitude": 12.9716,
            "longitude": 77.5946,
            "address": "Typed manually",
            "source": "manual",
            "geopoint_denied": True,
        },
    }
    resp = await client.post(_BASE, json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()

    async with async_session_factory() as db:
        complaint = await db.scalar(
            select(Complaint)
            .where(Complaint.id == uuid.UUID(data["id"]))
            .options(selectinload(Complaint.complaint_location))
        )
        assert complaint.complaint_location is not None
        assert complaint.complaint_location.geopoint_denied is True
        assert complaint.complaint_location.source == "manual"
        # Manual coordinates carry no device accuracy (Part 31).
        assert complaint.complaint_location.accuracy_m is None

    await _delete_user(email)


@pytest.mark.asyncio
async def test_upload_rejects_invalid_coordinates(client):
    email = _unique_email("comp-badgeo")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "description": "Description is long enough to pass.",
        "category": "WATER_LEAK",
        "location": {"latitude": 95.0, "longitude": 77.5946, "source": "gps"},
    }
    resp = await client.post(_BASE, json=payload, headers=headers)
    assert resp.status_code == 422, resp.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_file_type(client):
    email = _unique_email("comp-unsup")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    bad = await client.post(
        f"{_BASE}/media",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        headers=headers,
    )
    assert bad.status_code == 400, bad.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_upload_rejects_mismatched_image_content(client):
    email = _unique_email("comp-mismatch")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        f"{_BASE}/media",
        files={"file": ("fake.jpg", b"not a real image at all", "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_upload_rejects_oversized_image(client, monkeypatch):
    email = _unique_email("comp-big")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    # Override the module's settings so the image limit is tiny (1 byte): any
    # real image is then rejected on size before content inspection.
    import app.services.complaint_service as cs

    class _Tiny:
        MAX_IMAGE_MB = 0
        MAX_VIDEO_MB = 0
        ALLOWED_IMAGE_TYPES = "image/jpeg,image/png,image/webp,image/gif"
        ALLOWED_VIDEO_TYPES = "video/mp4,video/webm,video/quicktime"
        STORAGE_BACKEND = "local"
        STORAGE_LOCAL_DIR = "uploads_test"
        STORAGE_BUCKET = "civicagent-uploads"
        S3_ENDPOINT_URL = "http://localhost:9000"
        S3_PUBLIC_BASE_URL = ""

    monkeypatch.setattr(cs, "get_settings", lambda: _Tiny())

    resp = await client.post(
        f"{_BASE}/media",
        files={"file": ("big.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "limit" in resp.json()["detail"]

    await _delete_user(email)


@pytest.mark.asyncio
async def test_upload_network_storage_failure(client, monkeypatch):
    """A storage backend failure must surface as a 500, not a silent success."""
    email = _unique_email("comp-net-fail")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    import app.services.complaint_service as cs

    def _backend_down(*args, **kwargs):
        raise OSError("backend unreachable (simulated network failure)")

    monkeypatch.setattr(cs, "get_storage", _backend_down)

    resp = await client.post(
        f"{_BASE}/media",
        files={"file": ("photo.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 500, resp.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_upload_short_video(client):
    email = _unique_email("comp-video")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    up = await client.post(
        f"{_BASE}/media",
        files={"file": ("clip.mp4", _mp4_bytes(), "video/mp4")},
        headers=headers,
    )
    assert up.status_code == 201, up.text
    media = up.json()
    assert media["media_type"] == "VIDEO"
    assert media["content_type"] == "video/mp4"

    # Attach it to a complaint so the video flows through submission too.
    resp = await client.post(
        _BASE,
        json={
            "description": "Short video showing the issue at the site.",
            "category": "DRAINAGE",
            "media_ids": [media["id"]],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["media"][0]["media_type"] == "VIDEO"

    await _delete_user(email)


@pytest.mark.asyncio
async def test_upload_and_submit_requires_auth(client):
    resp = await client.post(f"{_BASE}/media", files={"file": ("a.jpg", b"x", "image/jpeg")})
    assert resp.status_code == 401

    resp = await client.post(_BASE, json={"description": "No auth here.", "category": "ROAD"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_and_submit_forbids_non_citizen(client):
    from app.core.security import hash_password
    from app.models import Role, UserProfile

    email = _unique_email("officer-submit")
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Officer Submit",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        token = create_access_token(str(user.id), RoleName.OFFICER.value)

    resp = await client.post(
        f"{_BASE}/media",
        files={"file": ("a.jpg", _jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text

    await _delete_user(email)
