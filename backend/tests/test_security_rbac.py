"""Cross-cutting RBAC matrix (Part 30).

Per-domain suites already assert 401/403 for their own routes. This module
asserts the whole role porch on a representative set of flagship endpoints in
one place, so an accidental privilege change in a shared dependency
(``require_roles``) cannot slip past piecemeal checks.

Naming/Layout:
- Data-driven matrix: for each endpoint the roles that must get 2xx; every
  other authenticated role must get 403 and anonymous must get 401.
- Authorization is verified against the LIVE role in the database, not the JWT
  role claim (fail-closed: a token claiming a higher role is denied).
- Mutation endpoints are asserted only for denial (403) — positives are covered
  by the domain suites.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, decode_token
from app.db.session import async_session_factory
from app.models import Department, FieldWorker, Role, User
from app.models.enums import RoleName, WorkerStatus
from tests.helpers import any_active_ward_id

_API = "/api/v1"
_PASSWORD = "TestPass#2026"

_ROLES = (
    RoleName.SUPER_ADMIN,
    RoleName.ADMIN,
    RoleName.OFFICER,
    RoleName.WARD_REPRESENTATIVE,
    RoleName.FIELD_WORKER,
    RoleName.CITIZEN,
)

# Endpoint -> roles that must receive 2xx. Every other authenticated role -> 403.
_CHECKED = {
    f"{_API}/auth/me": set(_ROLES),
    f"{_API}/geo/wards": set(_ROLES),
    f"{_API}/citizen/dashboard": {RoleName.CITIZEN},
    f"{_API}/analytics/overview": {
        RoleName.OFFICER,
        RoleName.ADMIN,
        RoleName.WARD_REPRESENTATIVE,
    },
    f"{_API}/hotspots/status": {
        RoleName.OFFICER,
        RoleName.ADMIN,
        RoleName.WARD_REPRESENTATIVE,
    },
    f"{_API}/hotspots/predictions": {
        RoleName.OFFICER,
        RoleName.ADMIN,
        RoleName.WARD_REPRESENTATIVE,
    },
    f"{_API}/infrastructure/predictions": {RoleName.OFFICER, RoleName.ADMIN},
    f"{_API}/admin/summary": {RoleName.SUPER_ADMIN},
    f"{_API}/worker/dashboard": {RoleName.FIELD_WORKER},
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _register(client, email: str) -> None:
    async with async_session_factory() as db:
        ward_id = await any_active_ward_id(db)
    r = await client.post(
        f"{_API}/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "full_name": "RBAC User",
            "ward_id": str(ward_id),
        },
    )
    assert r.status_code == 201, r.text


async def _set_role(email: str, role: RoleName) -> uuid.UUID:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        role_row = await db.scalar(select(Role).where(Role.name == role.value))
        assert role_row is not None
        user.role_id = role_row.id
        await db.commit()
        return user.id


async def _add_worker_profile(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        dept = await db.scalar(select(Department).order_by(Department.code).limit(1))
        assert dept is not None
        db.add(
            FieldWorker(
                user_id=user.id,
                department_id=dept.id,
                status=WorkerStatus.ACTIVE,
                skill_tags=[],
                equipment=[],
            )
        )
        await db.commit()


@pytest.fixture
async def rbac_tokens(client):
    """One registered user per role with a token minted for that role."""
    emails = {role: _unique_email(f"rbac-{role.value.lower()[:8]}") for role in _ROLES}
    for email in emails.values():
        await _register(client, email)

    user_ids = {}
    for role, email in emails.items():
        if role != RoleName.CITIZEN:
            user_ids[role] = await _set_role(email, role)
        else:
            async with async_session_factory() as db:
                user = await db.scalar(select(User).where(User.email == email))
                user_ids[role] = user.id
    await _add_worker_profile(emails[RoleName.FIELD_WORKER])

    tokens = {role: create_access_token(str(user_ids[role]), role.value) for role in _ROLES}
    yield tokens

    async with async_session_factory() as db:
        for email in emails.values():
            user = await db.scalar(select(User).where(User.email == email))
            if user is not None:
                await db.delete(user)
        await db.commit()


@pytest.mark.asyncio
async def test_anonymous_is_rejected_over_matrix(client):
    for path in _CHECKED:
        r = await client.get(path)
        assert r.status_code == 401, f"{path} anonymous: got {r.status_code}"


@pytest.mark.asyncio
async def test_role_matrix_get_posture(client, rbac_tokens):
    for path, allowed in _CHECKED.items():
        for role in _ROLES:
            expected = 200 if role in allowed else 403
            r = await client.get(path, headers=_auth(rbac_tokens[role]))
            assert r.status_code == expected, (
                f"{path} as {role.value}: got {r.status_code}, want {expected}"
            )


@pytest.mark.asyncio
async def test_mutation_denials_for_denied_roles(client, rbac_tokens):
    # POST /hotspots/train — city roles only (OFFICER/ADMIN).
    for role in _ROLES:
        if role in (RoleName.OFFICER, RoleName.ADMIN):
            continue
        r = await client.post(f"{_API}/hotspots/train", json={}, headers=_auth(rbac_tokens[role]))
        assert r.status_code == 403, f"hotspots/train as {role.value}: got {r.status_code}"

    # POST /admin/users — SUPER_ADMIN only.
    for role in _ROLES:
        if role == RoleName.SUPER_ADMIN:
            continue
        r = await client.post(f"{_API}/admin/users", json={}, headers=_auth(rbac_tokens[role]))
        assert r.status_code == 403, f"admin/users as {role.value}: got {r.status_code}"


@pytest.mark.asyncio
async def test_role_claim_is_not_authoritative(client, rbac_tokens):
    # A token claiming SUPER_ADMIN is useless when the user's DB role is CITIZEN.
    impostor = _liar_token(rbac_tokens[RoleName.CITIZEN], RoleName.SUPER_ADMIN.value)
    r = await client.get(f"{_API}/admin/summary", headers=_auth(impostor))
    assert r.status_code == 403, r.text

    # Conversely, a CITIZEN claim does not downgrade a real SUPER_ADMIN.
    humble = _liar_token(rbac_tokens[RoleName.SUPER_ADMIN], RoleName.CITIZEN.value)
    r = await client.get(f"{_API}/admin/summary", headers=_auth(humble))
    assert r.status_code == 200, r.text


def _liar_token(token: str, claimed_role: str) -> str:
    """Re-mint a token for the same user with a deliberately wrong role claim."""
    claims = decode_token(token, "access")
    return create_access_token(claims["sub"], claimed_role)
