"""Tests for real GPS complaint location (Part 33).

Cover: real GPS coordinates persist latitude/longitude + PostGIS point +
accuracy; GPS-denied manual fallback persists a *real* manual point with
``geopoint_denied``; fake placeholder (0,0) coordinates and manual entries that
carry device accuracy are rejected; the read-back detail returns ``accuracy_m``.

These run against the live development database and clean up after themselves.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import Complaint, ComplaintLocation, User
from app.services.auth_service import register_user
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"

# Real coordinates *inside* the reference WARD-1 (Kondhwa) operational polygon
# so geographic ward detection resolves a ward. Kept away from the polygon edges
# because ST_Contains excludes points on the boundary.
_GPS_LAT = 18.4634
_GPS_LON = 73.8912


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
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="GPS Test Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _load_complaint(complaint_id: uuid.UUID) -> Complaint:
    async with async_session_factory() as db:
        return await db.scalar(
            select(Complaint)
            .where(Complaint.id == complaint_id)
            .options(selectinload(Complaint.complaint_location), selectinload(Complaint.ward))
        )


@pytest.mark.asyncio
async def test_gps_complaint_persists_real_coordinates_and_accuracy(client):
    email = _unique_email("gps-real")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        _BASE,
        headers=headers,
        json={
            "description": "Deep pothole blocking the whole lane near the market.",
            "category": "ROAD",
            "location": {
                "latitude": _GPS_LAT,
                "longitude": _GPS_LON,
                "address": "Near Market Street",
                "source": "gps",
                "geopoint_denied": False,
                "accuracy_m": 15.74,
            },
        },
    )
    assert resp.status_code == 201, resp.text
    complaint_id = uuid.UUID(resp.json()["id"])

    complaint = await _load_complaint(complaint_id)
    assert complaint is not None
    loc = complaint.complaint_location
    assert loc is not None
    assert loc.source == "gps"
    assert loc.geopoint_denied is False
    assert loc.latitude == pytest.approx(_GPS_LAT)
    assert loc.longitude == pytest.approx(_GPS_LON)
    assert loc.accuracy_m == pytest.approx(15.7)

    # PostGIS POINT stored (X = longitude, Y = latitude).
    async with async_session_factory() as db:
        geom_text = await db.scalar(
            select(func.ST_AsText(ComplaintLocation.geom)).where(
                ComplaintLocation.complaint_id == complaint_id
            )
        )
    assert geom_text is not None
    assert "POINT(" in geom_text
    assert "73.8912" in geom_text
    assert "18.4634" in geom_text

    # Geographic ward detection from the actual point (WARD-1 Kondhwa polygon).
    assert complaint.ward is not None
    assert complaint.ward.code == "WARD-1"

    await _delete_user(email)


@pytest.mark.asyncio
async def test_gps_denied_manual_fallback_requires_real_coordinates(client):
    """A GPS-denied manual fallback persists a real manually placed point."""
    email = _unique_email("gps-denied")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        _BASE,
        headers=headers,
        json={
            "description": "Streetlight flickering outside the school gate.",
            "category": "STREET_LIGHTING",
            "location": {
                "latitude": 18.4719,
                "longitude": 73.8886,
                "address": "Placed on the map",
                "source": "manual",
                "geopoint_denied": True,
            },
        },
    )
    assert resp.status_code == 201, resp.text
    complaint_id = uuid.UUID(resp.json()["id"])

    complaint = await _load_complaint(complaint_id)
    assert complaint.complaint_location is not None
    assert complaint.complaint_location.source == "manual"
    assert complaint.complaint_location.geopoint_denied is True
    assert complaint.complaint_location.latitude == pytest.approx(18.4719)
    assert complaint.complaint_location.longitude == pytest.approx(73.8886)
    # No device accuracy on manual entries.
    assert complaint.complaint_location.accuracy_m is None

    await _delete_user(email)


@pytest.mark.asyncio
async def test_fake_zero_zero_coordinates_rejected(client):
    """The platform never stores fake/replacement coordinates like (0,0)."""
    email = _unique_email("gps-zero")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        _BASE,
        headers=headers,
        json={
            "description": "A description that would otherwise be valid.",
            "category": "OTHER",
            "location": {"latitude": 0, "longitude": 0, "source": "gps"},
        },
    )
    assert resp.status_code == 422, resp.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_out_of_range_coordinates_rejected(client):
    email = _unique_email("gps-range")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        _BASE,
        headers=headers,
        json={
            "description": "A description that would otherwise be valid.",
            "category": "OTHER",
            "location": {"latitude": 95.0, "longitude": 77.5, "source": "gps"},
        },
    )
    assert resp.status_code == 422, resp.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_manual_entry_with_accuracy_rejected(client):
    """accuracy_m is a device measurement — it must not ride on manual points."""
    email = _unique_email("gps-manualacc")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        _BASE,
        headers=headers,
        json={
            "description": "A description that would otherwise be valid.",
            "category": "OTHER",
            "location": {
                "latitude": 18.4620,
                "longitude": 73.8677,
                "source": "manual",
                "geopoint_denied": True,
                "accuracy_m": 12.0,
            },
        },
    )
    assert resp.status_code == 422, resp.text

    await _delete_user(email)


@pytest.mark.asyncio
async def test_detail_readback_returns_accuracy_and_origin(client):
    """GET /complaints/{id} round-trips accuracy_m + source back to the UI."""
    email = _unique_email("gps-readback")
    token = await _citizen_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        _BASE,
        headers=headers,
        json={
            "description": "Drain overflow near the bus stop.",
            "category": "DRAINAGE",
            "location": {
                "latitude": 18.4363,
                "longitude": 73.8965,
                "address": "Bus stop",
                "source": "gps",
                "geopoint_denied": False,
                "accuracy_m": 9.0,
            },
        },
    )
    assert create.status_code == 201, create.text
    complaint_id = create.json()["id"]

    detail = await client.get(f"{_BASE}/{complaint_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    loc = detail.json()["complaint_location"]
    assert loc is not None
    assert loc["source"] == "gps"
    assert loc["geopoint_denied"] is False
    assert loc["latitude"] == pytest.approx(18.4363)
    assert loc["longitude"] == pytest.approx(73.8965)
    assert loc["accuracy_m"] == pytest.approx(9.0)

    await _delete_user(email)
