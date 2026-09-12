"""Tests for the four reference wards and ward-required citizen registration.

CivicAgent ships with exactly four reference wards (WARD-1..WARD-4, the Pune
operational wards "Ward 1 — Kondhwa".."Ward 4 — Viman Nagar") installed by the
``b6c7d8e9f0a1`` migration. Registration requires the
citizen to pick one of them; the selection is validated server-side and surfaced
back on the profile (``GET /api/v1/auth/me``).

These run against the live development database (same convention as
``tests/test_auth.py``). Tests that create rows clean them up afterwards.
"""

import uuid

import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import User, Ward
from app.models.enums import RoleName

_PASSWORD = "TestPass#2026"

# code -> (expected display name, expected description suffix is free-form)
_REFERENCE_WARDS: list[tuple[str, str]] = [
    ("WARD-1", "Ward 1 — Kondhwa"),
    ("WARD-2", "Ward 2 — Kothrud"),
    ("WARD-3", "Ward 3 — Hadapsar"),
    ("WARD-4", "Ward 4 — Viman Nagar"),
]


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _reference_ward_id(code: str) -> uuid.UUID:
    async with async_session_factory() as db:
        ward = await db.scalar(select(Ward).where(Ward.code == code))
        if ward is None:
            pytest.fail(f"reference ward {code} missing from the database")
        return ward.id


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


def _register_payload(email: str, ward_id: uuid.UUID) -> dict:
    return {
        "email": email,
        "password": _PASSWORD,
        "full_name": "Ward Citizen",
        "ward_id": str(ward_id),
    }


@pytest.mark.asyncio
async def test_public_wards_endpoint_reference_set_and_baseline(client):
    response = await client.get("/api/v1/wards")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) >= 4
    by_code = {row["code"]: row for row in rows}
    for code, name in _REFERENCE_WARDS:
        ward = by_code.get(code)
        assert ward is not None, f"{code} missing from /api/v1/wards"
        assert ward["name"] == name
        assert ward["is_active"] is True
    extras = [
        row["code"]
        for row in rows
        if row["is_active"] and row["code"] not in dict(_REFERENCE_WARDS)
    ]
    if extras:
        pytest.skip(
            "dev database has leftover active test wards; run "
            "`.venv\\Scripts\\python -m scripts.reset_dev_data` to return to "
            "the reference baseline before asserting exactly four wards"
        )
        return
    assert len(rows) == 4
    assert {row["code"] for row in rows} == {code for code, _ in _REFERENCE_WARDS}
    assert [row["code"] for row in rows] == [code for code, _ in _REFERENCE_WARDS]


@pytest.mark.asyncio
@pytest.mark.parametrize("code,name", _REFERENCE_WARDS)
async def test_register_under_each_reference_ward(client, code, name):
    email = _unique_email("wardreg")
    ward_id = await _reference_ward_id(code)
    try:
        response = await client.post(
            "/api/v1/auth/register", json=_register_payload(email, ward_id)
        )
        assert response.status_code == 201
        data = response.json()
        user = data["user"]
        assert user["email"] == email
        assert user["role"]["name"] == RoleName.CITIZEN.value
        assert user["ward"]["code"] == code
        assert user["ward"]["name"] == name
        assert data["tokens"]["access_token"]
        assert data["tokens"]["refresh_token"]
    finally:
        await _delete_user(email)


@pytest.mark.asyncio
async def test_register_missing_ward_rejected(client):
    email = _unique_email("nomissward")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "No Ward"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_unknown_ward_rejected(client):
    email = _unique_email("badward")
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "full_name": "Bad Ward",
            "ward_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404
    await _delete_user(email)


@pytest.mark.asyncio
async def test_register_inactive_ward_rejected(client):
    email = _unique_email("inactward")
    async with async_session_factory() as db:
        ward = Ward(
            name=f"Inactive Ward {uuid.uuid4().hex[:6]}",
            code=f"INACT-{uuid.uuid4().hex[:6]}",
            description="test inactive ward",
            is_active=False,
        )
        db.add(ward)
        await db.flush()
        ward_id = ward.id
        await db.commit()
    try:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _PASSWORD,
                "full_name": "Inactive Ward",
                "ward_id": str(ward_id),
            },
        )
        assert response.status_code == 422
        await _delete_user(email)
    finally:
        async with async_session_factory() as db:
            ward = await db.get(Ward, ward_id)
            if ward is not None:
                await db.delete(ward)
                await db.commit()


@pytest.mark.asyncio
async def test_profile_and_login_show_registered_ward(client):
    email = _unique_email("wardprofile")
    ward_id = await _reference_ward_id("WARD-2")
    try:
        register_resp = await client.post(
            "/api/v1/auth/register", json=_register_payload(email, ward_id)
        )
        assert register_resp.status_code == 201
        access_token = register_resp.json()["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        assert me_resp.status_code == 200
        me_user = me_resp.json()["user"]
        assert me_user["ward"]["code"] == "WARD-2"
        assert me_user["ward"]["name"] == "Ward 2 — Kothrud"

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _PASSWORD},
        )
        assert login_resp.status_code == 200
        login_user = login_resp.json()["user"]
        assert login_user["ward"]["code"] == "WARD-2"
    finally:
        await _delete_user(email)
