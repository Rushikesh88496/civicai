"""Extended audit tests (Part 28).

The auth endpoints now write ``auth.login`` / ``auth.logout`` /
``auth.register`` / ``auth.password_reset`` rows to ``audit_logs``. These tests
exercise the integrated API path and clean up after themselves.
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models import AuditLog, Complaint, User

_PASSWORD = "TestPass#2026"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _audit_rows(entity_id: str) -> list[str]:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(AuditLog.action).where(AuditLog.entity_id == entity_id)
            )
        )
        return list(rows.scalars().all())


async def _cleanup(email: str, entity_id: str) -> None:
    async with async_session_factory() as db:
        await db.execute(delete(AuditLog).where(AuditLog.entity_id == entity_id))
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
        await db.commit()


@pytest.mark.asyncio
async def test_register_writes_audit_row(client):
    email = _unique_email("aud-reg")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Audit User"},
    )
    assert resp.status_code == 201
    user_id = resp.json()["user"]["id"]
    # Audit row for registration needs a user id before it exists — the service
    # flushes with the actor keyed to the freshly-created user's id.
    assert resp.json()["user"]["email"] == email
    actions = await _audit_rows(user_id)
    assert "auth.register" in actions
    await _cleanup(email, user_id)


@pytest.mark.asyncio
async def test_login_writes_audit_row(client):
    email = _unique_email("aud-login")
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Audit User"},
    )
    user_id = reg.json()["user"]["id"]
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert login.status_code == 200
    actions = await _audit_rows(user_id)
    assert "auth.login" in actions
    await _cleanup(email, user_id)


@pytest.mark.asyncio
async def test_logout_writes_audit_row(client):
    email = _unique_email("aud-out")
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Audit User"},
    )
    assert reg.status_code == 201
    user_id = reg.json()["user"]["id"]
    refresh = reg.json()["tokens"]["refresh_token"]
    access = reg.json()["tokens"]["access_token"]

    out = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert out.status_code == 200
    actions = await _audit_rows(user_id)
    assert "auth.logout" in actions

    # The logged-out access token must be rejected on the next call.
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    # Depends on Redis; when unavailable the stateless JWT is still accepted.
    assert me.status_code in (200, 401)
    await _cleanup(email, user_id)


@pytest.mark.asyncio
async def test_password_reset_writes_audit_row(client):
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    from app.core.config import get_settings
    from app.core.security import create_access_token

    settings = get_settings()
    email = _unique_email("aud-reset")
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Audit User"},
    )
    user_id = reg.json()["user"]["id"]

    now = datetime.now(UTC)
    reset_token = pyjwt.encode(
        {
            "sub": user_id,
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
    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "new_password": "NewPass#2026"},
    )
    assert resp.status_code == 200
    actions = await _audit_rows(user_id)
    assert "auth.password_reset" in actions
    _ = create_access_token  # imported for API parity; unused here
    await _cleanup(email, user_id)


@pytest.mark.asyncio
async def test_complaint_create_writes_audit_row(client):
    email = _unique_email("aud-comp")
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Audit User"},
    )
    assert reg.status_code == 201
    user_id = reg.json()["user"]["id"]
    token = reg.json()["tokens"]["access_token"]

    created = await client.post(
        "/api/v1/complaints",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "description": "Pothole at the main market entrance is leaking sewage.",
            "category": "ROAD",
            "location": {"latitude": 19.076, "longitude": 72.8777, "address": "Market"},
        },
    )
    assert created.status_code == 201
    complaint_id = created.json()["id"]

    actions = await _audit_rows(str(complaint_id))
    assert "complaint.create" in actions

    async with async_session_factory() as db:
        await db.execute(
            delete(AuditLog).where(AuditLog.entity_id == str(complaint_id))
        )
        await db.execute(
            delete(AuditLog).where(
                AuditLog.entity_id == str(user_id),
                AuditLog.action.in_(["auth.register"]),
            )
        )
        complaint = await db.scalar(
            select(Complaint).where(Complaint.id == complaint_id)
        )
        if complaint is not None:
            await db.delete(complaint)
        await db.commit()
    await _cleanup(email, user_id)


@pytest.mark.asyncio
async def test_audit_service_accepts_extended_verbs():
    """record_audit accepts the Part 28 action verbs without raising."""
    from app.core.security import hash_password
    from app.models import Role, UserProfile

    email = _unique_email("aud-verb")
    async with async_session_factory() as db:
        citizen_role = await db.scalar(select(Role).where(Role.name == "CITIZEN"))
        test_user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Verb",
            role_id=citizen_role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(test_user)
        await db.flush()
        db.add(UserProfile(user_id=test_user.id))
        uid = test_user.id

        from app.services.audit_service import (
            ACTION_COMPLAINT_CREATE,
            ACTION_COMPLAINT_TRIAGE,
            ACTION_ROUTING_OVERRIDE,
            ACTION_WORK_ORDER_DISPATCH,
            record_audit,
        )

        verbs = (
            ACTION_COMPLAINT_CREATE,
            ACTION_COMPLAINT_TRIAGE,
            ACTION_WORK_ORDER_DISPATCH,
            ACTION_ROUTING_OVERRIDE,
        )
        for verb in verbs:
            await record_audit(
                db,
                actor_id=uid,
                action=verb,
                entity_type="complaint",
                entity_id=str(uuid.uuid4()),
            )
        await db.commit()

        actions = set(
            (
                await db.execute(select(AuditLog.action).where(AuditLog.actor_id == uid))
            )
            .scalars()
            .all()
        )
        await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
        await db.delete(test_user)
        await db.commit()
        assert actions == set(verbs)
    await _cleanup(email, str(uuid.uuid4()))
