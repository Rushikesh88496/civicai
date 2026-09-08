"""Tests for authentication and RBAC.

These run against the live development database. Each test cleans up the rows it
creates so the suite is safe to re-run.
"""

import uuid

import jwt
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token
from app.db.session import async_session_factory
from app.models import User
from app.models.enums import RoleName

settings = get_settings()

_PASSWORD = "TestPass#2026"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _user_role_name(email: str) -> str | None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            return None
        await db.refresh(user, attribute_names=["role"])
        return user.role.name


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


@pytest.fixture
async def registered_user(client):
    email = _unique_email("reg")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Test User"},
    )
    yield {"response": response, "email": email, "data": response.json()}
    await _delete_user(email)


@pytest.mark.asyncio
async def test_register_returns_tokens_and_citizen_role(registered_user, client):
    data = registered_user["data"]
    assert registered_user["response"].status_code == 201
    assert "access_token" in data["tokens"]
    assert "refresh_token" in data["tokens"]
    assert data["tokens"]["token_type"] == "bearer"
    assert data["user"]["email"] == registered_user["email"]
    assert data["user"]["role"]["name"] == RoleName.CITIZEN.value
    assert await _user_role_name(registered_user["email"]) == RoleName.CITIZEN.value


@pytest.mark.asyncio
async def test_password_is_not_stored_in_plaintext(registered_user):
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == registered_user["email"]))
        assert user is not None
        assert user.password_hash != _PASSWORD
        assert user.password_hash.startswith("$argon2")


@pytest.mark.asyncio
async def test_register_duplicate_email(registered_user, client):
    email = registered_user["email"]
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Other"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_register_rejects_weak_password(client):
    email = _unique_email("weak")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "onlylowercase", "full_name": "Weak"},
    )
    assert response.status_code == 422
    await _delete_user(email)


@pytest.mark.asyncio
async def test_register_rejects_invalid_email(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": _PASSWORD, "full_name": "Bad"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_wrong_password(client, registered_user):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": "WrongPass#1"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_wrong_email(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": _unique_email("nope"), "password": _PASSWORD},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    bad = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer bad"})
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_me_round_trip(client, registered_user):
    acc = registered_user["data"]["tokens"]["access_token"]
    headers = {"Authorization": f"Bearer {acc}"}
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    body = response.json()["user"]
    assert body["email"] == registered_user["email"]
    assert body["role"]["name"] == RoleName.CITIZEN.value


@pytest.mark.asyncio
async def test_refresh_rotation_rotates_token(client, registered_user):
    old_refresh = registered_user["data"]["tokens"]["refresh_token"]
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    new_refresh = body["refresh_token"]
    assert new_refresh != old_refresh

    # The used refresh token must be revoked.
    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reused.status_code == 401


@pytest.mark.asyncio
async def test_refresh_garbage_token(client):
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "junk"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client, registered_user):
    refresh = registered_user["data"]["tokens"]["refresh_token"]
    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert logout.status_code == 200

    refresh2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert refresh2.status_code == 401


@pytest.mark.asyncio
async def test_reset_password_revokes_sessions_and_allows_login(client, registered_user):
    email = registered_user["email"]

    # Generate a reset token the way the API would (password_reset type).
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    reset_token = jwt.encode(
        {
            "sub": registered_user["data"]["user"]["id"],
            "type": "password_reset",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    response = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "new_password": "NewPass#2026"},
    )
    assert response.status_code == 200

    # Old password must no longer work; new one must.
    old_login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "NewPass#2026"}
    )
    assert new_login.status_code == 200

    # Resetting password revokes outstanding refresh sessions. The access token
    # from the old login is a stateless JWT (valid until expiry), but the old
    # refresh token from registration must no longer refresh a session.
    old_refresh = registered_user["data"]["tokens"]["refresh_token"]
    refresh_after_reset = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert refresh_after_reset.status_code == 401


@pytest.mark.asyncio
async def test_forgot_password_returns_generic_message_for_unknown_email(client):
    response = await client.post(
        "/api/v1/auth/forgot-password", json={"email": _unique_email("ghost")}
    )
    assert response.status_code == 200
    assert "sent" in response.json()["message"].lower()
    # In production, no token returned.
    assert response.json()["reset_token"] is None


@pytest.mark.asyncio
async def test_update_profile(client, registered_user):
    acc = registered_user["data"]["tokens"]["access_token"]
    headers = {"Authorization": f"Bearer {acc}"}
    response = await client.patch(
        "/api/v1/auth/me/profile",
        headers=headers,
        json={"phone": "+1 555 0100", "city": "Portland"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1 555 0100"
    assert body["city"] == "Portland"


@pytest.mark.asyncio
async def test_access_token_rejected_as_refresh(client, registered_user):
    acc = registered_user["data"]["tokens"]["access_token"]
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": acc})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rbac_role_gate():
    """require_roles must reject a CITIZEN for an ADMIN-scope endpoint."""
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import require_roles
    from app.core.security import hash_password
    from app.models import Role, UserProfile

    app = FastAPI()

    @app.get("/admin-only", dependencies=[Depends(require_roles(RoleName.ADMIN.value))])
    async def _admin_only():
        return {"ok": True}

    # Part 27 promotes the seeded admin@example.com to SUPER_ADMIN, so this test
    # provisions its own ADMIN and CITIZEN users instead of relying on seed data.
    citizen_email = _unique_email("tc-rbac-citizen")
    admin_email = _unique_email("tc-rbac-admin")
    try:
        async with async_session_factory() as db:
            citizen_role = await db.scalar(select(Role).where(Role.name == RoleName.CITIZEN.value))
            admin_role = await db.scalar(select(Role).where(Role.name == RoleName.ADMIN.value))
            for email, role in ((citizen_email, citizen_role), (admin_email, admin_role)):
                user = User(
                    email=email,
                    password_hash=hash_password(_PASSWORD),
                    full_name="RBAC User",
                    role_id=role.id,
                    is_active=True,
                    is_email_verified=True,
                )
                db.add(user)
                await db.flush()
                db.add(UserProfile(user_id=user.id))
            await db.commit()

        async with async_session_factory() as db:
            citizen = await db.scalar(select(User).where(User.email == citizen_email))
            admin = await db.scalar(select(User).where(User.email == admin_email))
        assert citizen is not None and admin is not None

        citizen_tok = create_access_token(str(citizen.id), RoleName.CITIZEN.value)
        admin_tok = create_access_token(str(admin.id), RoleName.ADMIN.value)
        admin_refresh, _, _ = create_refresh_token(str(admin.id))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            citizen_resp = await client.get(
                "/admin-only", headers={"Authorization": f"Bearer {citizen_tok}"}
            )
            admin_resp = await client.get(
                "/admin-only", headers={"Authorization": f"Bearer {admin_tok}"}
            )
            no_token = await client.get("/admin-only")

        assert citizen_resp.status_code == 403
        assert admin_resp.status_code == 200
        assert no_token.status_code == 401
        _ = admin_refresh  # created for completeness; not sent anywhere
    finally:
        await _delete_user(citizen_email)
        await _delete_user(admin_email)
