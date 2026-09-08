"""Tests for the citizen dashboard endpoint.

These run against the live development database and clean up after themselves.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import Complaint, User, Ward
from app.models.enums import ComplaintCategory, ComplaintPriority, ComplaintStatus, RoleName
from app.services.auth_service import register_user

_PASSWORD = "TestPass#2026"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _citizen_token_and_user(email: str) -> tuple[str, User]:
    """Register a fresh citizen and mint a valid access token for them."""
    from app.schemas.auth import RegisterIn

    async with async_session_factory() as db:
        await register_user(
            db,
            RegisterIn(email=email, password=_PASSWORD, full_name="Citizen Test"),
        )
        user = await db.scalar(select(User).where(User.email == email))
    token = create_access_token(str(user.id), RoleName.CITIZEN.value)
    return token, user


async def _add_complaints(email: str, *, count: int = 3, ward_code: str | None = None) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        ward = None
        if ward_code is not None:
            ward = await db.scalar(select(Ward).where(Ward.code == ward_code))
            user.ward_id = ward.id
        for i in range(count):
            db.add(
                Complaint(
                    user_id=user.id,
                    ward_id=user.ward_id,
                    category=ComplaintCategory.ROAD,
                    title=f"Complaint {i}",
                    priority=ComplaintPriority.MEDIUM,
                    status=ComplaintStatus.OPEN if i % 2 == 0 else ComplaintStatus.RESOLVED,
                    created_at=datetime.now(UTC) - timedelta(days=i),
                    updated_at=datetime.now(UTC) - timedelta(days=i),
                )
            )
        await db.commit()


@pytest.fixture
async def empty_citizen(client):
    email = _unique_email("cit-empty")
    token, _ = await _citizen_token_and_user(email)
    yield {"email": email, "token": token}
    await _delete_user(email)


@pytest.fixture
async def citizen_with_data(client):
    email = _unique_email("cit-data")
    token, _ = await _citizen_token_and_user(email)
    await _add_complaints(email, count=3, ward_code="W-001")
    yield {"email": email, "token": token}
    await _delete_user(email)


@pytest.mark.asyncio
async def test_dashboard_requires_auth(client):
    response = await client.get("/api/v1/citizen/dashboard")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_forbids_non_citizen(client):
    from app.core.security import hash_password
    from app.models import Role, UserProfile

    email = _unique_email("officer-dash")
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Officer Dash",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        token = create_access_token(str(user.id), RoleName.OFFICER.value)

    response = await client.get(
        "/api/v1/citizen/dashboard", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    await _delete_user(email)


@pytest.mark.asyncio
async def test_dashboard_new_citizen_all_zero(empty_citizen, client):
    token = empty_citizen["token"]
    response = await client.get(
        "/api/v1/citizen/dashboard", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["complaints"] == {
        "total": 0,
        "open": 0,
        "in_progress": 0,
        "resolved": 0,
        "escalated": 0,
    }
    assert data["recent_complaints"] == []
    assert data["ward"]["code"] is None


@pytest.mark.asyncio
async def test_dashboard_with_data(citizen_with_data, client):
    token = citizen_with_data["token"]
    response = await client.get(
        "/api/v1/citizen/dashboard", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["complaints"]["total"] == 3
    assert data["complaints"]["open"] == 2
    assert data["complaints"]["resolved"] == 1
    assert len(data["recent_complaints"]) == 3
    assert data["ward"]["code"] == "W-001"
    assert data["ward"]["name"] == "Downtown"


@pytest.mark.asyncio
async def test_dashboard_only_returns_own_data(client):
    """A citizen must never see another citizen's complaints."""
    a_token, _ = await _citizen_token_and_user(_unique_email("iso-a"))
    b_email = _unique_email("iso-b")
    await _citizen_token_and_user(b_email)
    await _add_complaints(b_email, count=2, ward_code="W-002")

    response = await client.get(
        "/api/v1/citizen/dashboard", headers={"Authorization": f"Bearer {a_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["complaints"]["total"] == 0
    assert data["recent_complaints"] == []

    await _delete_user(b_email)
