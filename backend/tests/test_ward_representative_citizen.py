"""Tests for "My Ward Representative" exposed to citizens.

A citizen's ward is always taken from the authenticated ``User.ward_id`` (set at
registration) and the representative is looked up in the database for that ward
only — the client can never ask for another ward. These tests verify:

- Citizen authentication (real register + login flow)
- API authorization (401 unauthenticated, 403 for every non-citizen role)
- All four reference ward mappings (WARD-1..4 → seeded representatives)
- Cross-ward isolation (a citizen only ever sees their own ward's rep)
- No-representative wards (null, not fabricated data)
- Payload privacy (only name/email/title/status — no secrets or internals)
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import Role, User, UserProfile, Ward, WardRepresentative
from app.models.enums import RepresentativeStatus, RoleName
from app.services.auth_service import register_user

_PASSWORD = "TestPass#2026"

# Source of truth mirror of backend/seed.py (the feature must never hardcode
# these in the API/frontend — only tests assert the seeded reality).
_MAPPING = {
    "WARD-1": ("Kobu Jadav", "kobu.jadav@example.com"),
    "WARD-2": ("Dheeraj Borse", "dheeraj.borse@example.com"),
    "WARD-3": ("Rushikesh Tapsale", "rushikesh.tapsale@example.com"),
    "WARD-4": ("Rajveer Rajput", "rajveer.rajput@example.com"),
}

_API = "/api/v1/citizen/my-ward-representative"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _reference_ward_id(ward_code: str) -> uuid.UUID | None:
    async with async_session_factory() as db:
        ward = await db.scalar(select(Ward).where(Ward.code == ward_code))
        return ward.id if ward is not None else None


async def _register_citizen(email: str, ward_id: uuid.UUID) -> str:
    """Register a citizen in a specific ward and mint an access token."""
    from app.schemas.auth import RegisterIn

    async with async_session_factory() as db:
        await register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Citizen Test",
                ward_id=ward_id,
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), RoleName.CITIZEN.value)


async def _register_citizen_via_api(client, email: str, ward_id: uuid.UUID) -> str:
    """Register + login through the real auth endpoints (citizen authentication)."""
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "full_name": "Citizen Test",
            "ward_id": str(ward_id),
        },
    )
    assert reg.status_code in (200, 201), reg.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert login.status_code == 200, login.text
    return login.json()["tokens"]["access_token"]


async def _role_user(email: str, role_name: str, ward_id=None) -> str:
    """Create a user of any role and return an access token for it."""
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == role_name))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Role Test",
            role_id=role.id,
            ward_id=ward_id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), role_name)


async def _make_ward_with_rep(code: str, full_name: str, email: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a fresh test ward bound to a fresh active representative."""
    async with async_session_factory() as db:
        ward = Ward(name=f"{code} Ward", code=code, description="test wr")
        db.add(ward)
        await db.flush()
        role = await db.scalar(select(Role).where(Role.name == RoleName.WARD_REPRESENTATIVE.value))
        rep = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=full_name,
            role_id=role.id,
            ward_id=ward.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(rep)
        await db.flush()
        db.add(UserProfile(user_id=rep.id))
        db.add(
            WardRepresentative(
                user_id=rep.id,
                ward_id=ward.id,
                title="Test Representative",
                status=RepresentativeStatus.ACTIVE,
            )
        )
        await db.commit()
        return ward.id, rep.id


async def _cleanup_ward_and_rep(ward_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        await db.execute(delete(WardRepresentative).where(WardRepresentative.ward_id == ward_id))
        await db.execute(delete(User).where(User.ward_id == ward_id))
        await db.execute(delete(Ward).where(Ward.id == ward_id))
        await db.commit()


def _assert_clean_rep_payload(rep: dict) -> None:
    """The representative payload exposes ONLY public contact fields."""
    assert set(rep.keys()) == {"name", "email", "title", "status"}


# ---------- Test setup ------------------------------------------------------ #


async def _ensure_reference_representatives() -> None:
    """Idempotently materialise the four seed representatives for the reference
    wards (WARD-1..WARD-4) when they are missing.

    The post-suite baseline reset wipes every non-admin user — including the
    seeded representatives — so a test run without a recent ``seed.py`` would
    otherwise see empty wards. This mirrors exactly what ``seed.py`` creates
    (same names/emails/titles/status) so the mapping tests stay deterministic
    without depending on external database state.
    """
    async with async_session_factory() as db:
        for ward_code, (full_name, email) in _MAPPING.items():
            ward = await db.scalar(select(Ward).where(Ward.code == ward_code))
            if ward is None:
                continue
            existing = await db.scalar(
                select(WardRepresentative).where(WardRepresentative.ward_id == ward.id)
            )
            if existing is not None:
                continue
            rep_user = await db.scalar(select(User).where(User.email == email))
            if rep_user is None:
                role = await db.scalar(
                    select(Role).where(Role.name == RoleName.WARD_REPRESENTATIVE.value)
                )
                rep_user = User(
                    email=email,
                    password_hash=hash_password(_PASSWORD),
                    full_name=full_name,
                    role_id=role.id,
                    ward_id=ward.id,
                    is_active=True,
                    is_email_verified=True,
                )
                db.add(rep_user)
                await db.flush()
                db.add(UserProfile(user_id=rep_user.id))
            db.add(
                WardRepresentative(
                    user_id=rep_user.id,
                    ward_id=ward.id,
                    title=f"{ward_code} Representative",
                    status=RepresentativeStatus.ACTIVE,
                )
            )
        await db.commit()


@pytest.fixture(autouse=True)
async def _reference_reps_present():
    await _ensure_reference_representatives()
    yield


# ---------- Authentication & authorization ---------------------------------- #


@pytest.mark.asyncio
async def test_endpoint_requires_auth(client):
    response = await client.get(_API)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_endpoint_forbids_non_citizen_roles(client):
    for role_name in (
        RoleName.OFFICER.value,
        RoleName.WARD_REPRESENTATIVE.value,
        RoleName.FIELD_WORKER.value,
        RoleName.ADMIN.value,
    ):
        email = _unique_email("authz")
        token = await _role_user(email, role_name)
        response = await client.get(_API, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403, role_name
        await _delete_user(email)


@pytest.mark.asyncio
async def test_citizen_authentication_flow(client):
    """A citizen authenticated through the real register+login flow can read
    their own ward representative."""
    ward_id = await _reference_ward_id("WARD-1")
    email = _unique_email("cit-auth")
    token = await _register_citizen_via_api(client, email, ward_id)

    response = await client.get(_API, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == "WARD-1"
    assert data["representative"]["name"] == "Kobu Jadav"
    await _delete_user(email)


# ---------- The four reference ward mappings -------------------------------- #


@pytest.mark.asyncio
async def test_all_four_ward_mappings(client):
    for ward_code, (rep_name, rep_email) in _MAPPING.items():
        ward_id = await _reference_ward_id(ward_code)
        assert ward_id is not None, f"reference ward {ward_code} missing"

        email = _unique_email(f"map-{ward_code.lower()}")
        token = await _register_citizen(email, ward_id)

        response = await client.get(_API, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, ward_code
        data = response.json()

        assert data["code"] == ward_code
        assert set(data.keys()) == {"code", "name", "description", "representative"}
        rep = data["representative"]
        assert rep is not None, ward_code
        _assert_clean_rep_payload(rep)
        assert rep["name"] == rep_name, ward_code
        assert rep["email"] == rep_email, ward_code
        assert rep["status"] == "ACTIVE", ward_code

        # The citizen dashboard carries the same ward + representative + status.
        dash = await client.get(
            "/api/v1/citizen/dashboard", headers={"Authorization": f"Bearer {token}"}
        )
        assert dash.status_code == 200
        dash_rep = dash.json()["ward"]["representative"]
        assert dash_rep["name"] == rep_name
        assert dash_rep["status"] == "ACTIVE"

        await _delete_user(email)


# ---------- Cross-ward isolation --------------------------------------------- #


@pytest.mark.asyncio
async def test_citizen_only_sees_own_ward_representative(client):
    """A citizen in ward A must never be able to see ward B's representative."""
    ward_a_id = await _reference_ward_id("WARD-1")
    ward_b_code = f"TC-WR-{uuid.uuid4().hex[:6]}"
    ward_b_id, _ = await _make_ward_with_rep(ward_b_code, "Bella Rep", _unique_email("rep-b"))

    citizen_a = _unique_email("iso-a")
    citizen_b = _unique_email("iso-b")
    token_a = await _register_citizen(citizen_a, ward_a_id)
    token_b = await _register_citizen(citizen_b, ward_b_id)

    try:
        r_a = await client.get(_API, headers={"Authorization": f"Bearer {token_a}"})
        r_b = await client.get(_API, headers={"Authorization": f"Bearer {token_b}"})
        assert r_a.status_code == 200
        assert r_b.status_code == 200

        rep_a = r_a.json()["representative"]["name"]
        rep_b = r_b.json()["representative"]["name"]
        assert rep_a == "Kobu Jadav"
        assert rep_b == "Bella Rep"
        assert rep_a != rep_b
        # Ward B is invisible to citizen A even when accidentally requested.
        assert r_a.json()["code"] == "WARD-1"
        assert r_b.json()["code"] == ward_b_code
    finally:
        await _delete_user(citizen_a)
        await _delete_user(citizen_b)
        await _cleanup_ward_and_rep(ward_b_id)


# ---------- No representative assigned ---------------------------------------- #


@pytest.mark.asyncio
async def test_no_representative_returns_empty_state(client):
    """A ward without a representative yields a null representative — never a
    fabricated one."""
    ward_code = f"TC-WR-{uuid.uuid4().hex[:6]}"
    async with async_session_factory() as db:
        ward = Ward(name=f"{ward_code} Ward", code=ward_code, description="test wr")
        db.add(ward)
        await db.commit()
        ward_id = ward.id

    email = _unique_email("norep")
    token = await _register_citizen(email, ward_id)
    try:
        response = await client.get(_API, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == ward_code
        assert data["representative"] is None

        dash = await client.get(
            "/api/v1/citizen/dashboard", headers={"Authorization": f"Bearer {token}"}
        )
        assert dash.status_code == 200
        assert dash.json()["ward"]["representative"] is None
    finally:
        await _delete_user(email)
        await _cleanup_ward_and_rep(ward_id)


# ---------- Privacy: no admin / internal / secret data ------------------------ #


@pytest.mark.asyncio
async def test_response_exposes_no_sensitive_information(client):
    ward_id = await _reference_ward_id("WARD-2")
    email = _unique_email("privacy")
    token = await _register_citizen(email, ward_id)
    try:
        response = await client.get(_API, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        raw = response.text

        # Representative payload carries only public identity fields.
        rep = response.json()["representative"]
        _assert_clean_rep_payload(rep)

        # No hashes, tokens, roles, admin surfaces, or internal AI fields.
        for forbidden in (
            "password",
            "password_hash",
            "access_token",
            "refresh_token",
            "tokens",
            "role_id",
            "role_name",
            "is_super_admin",
            "is_admin",
            "ai_",
            "internal",
            "ward_rep",
        ):
            assert forbidden not in raw, f"leaked field: {forbidden}"

        # The authenticated citizen's own ward is the only one ever returned.
        assert response.json()["code"] == "WARD-2"
    finally:
        await _delete_user(email)


# ---------- Reference-safety: a citizen with no ward gets a clean null --------- #


@pytest.mark.asyncio
async def test_citizen_without_ward_gets_null_and_404s_nothing(client):
    """Unaffiliated citizens (no ward) must not crash: they see null and nothing
    cross-ward — this mirrors the complaint lifecycle where a user may not have a
    ward yet."""
    email = _unique_email("nohome")
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.CITIZEN.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="No Ward Citizen",
            role_id=role.id,
            ward_id=None,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.commit()
        token = create_access_token(str(user.id), RoleName.CITIZEN.value)

    try:
        response = await client.get(_API, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["code"] is None
        assert data["representative"] is None
    finally:
        await _delete_user(email)
