"""Security hardening tests (Part 28): headers, CORS, rate limiting, blacklist.

These run against the live development database and clean up after themselves.
"""

import uuid

import pytest


@pytest.mark.asyncio
async def test_security_headers_applied(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "camera=()" in resp.headers.get("permissions-policy", "")
    assert resp.headers.get("x-xss-protection") == "0"
    assert "default-src 'self'" in resp.headers.get("content-security-policy", "")


@pytest.mark.asyncio
async def test_cors_allows_configured_origin(client):
    resp = await client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    preflight = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "authorization" in preflight.headers.get("access-control-allow-headers", "").lower()


@pytest.mark.asyncio
async def test_cors_rejects_unconfigured_origin(client):
    resp = await client.get("/api/v1/health", headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_rate_limiter_returns_429_json():
    """A fresh enabled limiter enforces its budget and returns structured 429s."""
    from fastapi import FastAPI, Request
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    from app.middleware.rate_limit import _rate_limit_handler

    limiter = Limiter(key_func=get_remote_address, default_limits=["100/hour"], enabled=True)

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    @app.get("/limited")
    @limiter.limit("2/minute")
    async def _limited(request: Request):
        return {"ok": True}

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        first = await ac.get("/limited")
        second = await ac.get("/limited")
        third = await ac.get("/limited")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    body = third.json()
    assert "detail" in body and "rate limit" in body["detail"].lower()


@pytest.mark.asyncio
async def test_blacklist_helpers_never_raise():
    """Blacklist functions degrade to no-ops / False when Redis is unavailable."""
    from app.core.blacklist import blacklist_token, is_blacklisted

    jti = uuid.uuid4().hex
    await blacklist_token(jti, 60)  # must not raise even if Redis is gone
    result = await is_blacklisted(jti)  # must not raise
    assert result in (True, False)


@pytest.mark.asyncio
async def test_unauthenticated_requests_still_secured(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.headers.get("x-frame-options") == "DENY"


@pytest.mark.asyncio
async def test_media_requires_signed_url_or_bearer(client):
    """/media files are gated (Part 28, 1F): only signed URLs / valid Bearer."""
    from sqlalchemy import delete, select

    from app.core.config import get_settings
    from app.core.media_signing import sign_media_token
    from app.core.security import create_access_token, hash_password
    from app.db.session import async_session_factory
    from app.models import AuditLog, Role, User, UserProfile

    settings = get_settings()
    key = f"complaints/{uuid.uuid4().hex}.png"
    payload = b"\x89PNG-test-media"

    from app.storage.local import LocalStorage

    storage = LocalStorage(settings)
    try:
        storage.upload(key, payload, "image/png")
    except Exception:
        pass  # dir may already exist; upload is idempotent for this key

    try:
        # 1) unsigned anonymous -> 403
        anon = await client.get(f"/media/{key}")
        assert anon.status_code == 403

        # 2) tampered token -> 403
        token = sign_media_token(key, secret=settings.JWT_SECRET, ttl_seconds=900)
        bad = await client.get(f"/media/{key}?token={token}x")
        assert bad.status_code == 403

        # 3) valid signed token -> 200
        ok = await client.get(f"/media/{key}?token={token}")
        assert ok.status_code == 200
        assert ok.content == payload

        # 4) valid Bearer access token -> 200
        email = f"med-{uuid.uuid4().hex[:10]}@example.com"
        async with async_session_factory() as db:
            citizen_role = await db.scalar(select(Role).where(Role.name == "CITIZEN"))
            user = User(
                email=email,
                password_hash=hash_password("TestPass#2026"),
                full_name="Media Gate",
                role_id=citizen_role.id,
                is_active=True,
                is_email_verified=True,
            )
            db.add(user)
            await db.flush()
            db.add(UserProfile(user_id=user.id))
            uid = user.id
            await db.commit()
        bearer = await client.get(
            f"/media/{key}",
            headers={"Authorization": f"Bearer {create_access_token(str(uid), 'CITIZEN')}"},
        )
        assert bearer.status_code == 200
        assert bearer.content == payload

        # 5) expired signed token -> 403
        old = sign_media_token(key, secret=settings.JWT_SECRET, ttl_seconds=900, now=1_700_000_000)
        expired = await client.get(f"/media/{key}?token={old}")
        assert expired.status_code == 403

        async with async_session_factory() as db:
            await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
            await db.delete(user)
            await db.commit()
    finally:
        storage.delete(key)
