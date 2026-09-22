"""Tests for the Super-Admin Panel (Part 27).

Covers:
  - Authorization: only SUPER_ADMIN may touch ``/api/v1/admin`` (others 403,
    anonymous 401)
  - Summary counts
  - User CRUD: create citizen + worker + representative profiles, list with
    search/role filter, update, disable self / other SUPER_ADMIN guards
  - Role CRUD: create, description update, disable guards (SUPER_ADMIN role and
    roles with active users cannot be disabled)
  - Ward / department CRUD (unique-code guards, active filter)
  - Field-worker / representative update
  - Complaint-category and priority-weight CRUD (key allow-list)
  - SLA rule create / update / delete
  - Secure configuration: responses never leak secret values (masked only),
    overrides stored Fernet-encrypted, clear reverts to env
  - Groq connectivity test schema
  - Audit trail: mutating actions append rows filterable by action/entity
"""

import uuid

import pytest_asyncio
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    Role,
    SystemSetting,
    User,
    UserProfile,
    Ward,
)

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/admin"
_TEST_SECRET = "sk-groq-test-panel-0123456789abcdef"

_created_user_ids: list[uuid.UUID] = []
_created_ward_codes: list[str] = []
_created_dept_codes: list[str] = []
_created_role_names: list[str] = []
_created_category_codes: list[str] = []
_created_weight_ids: list[uuid.UUID] = []
_created_sla_ids: list[uuid.UUID] = []


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_super_admin() -> str:
    """Create a SUPER_ADMIN user and return its access token."""
    email = _unique_email("sa")
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == "SUPER_ADMIN"))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Panel SA",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        _created_user_ids.append(user.id)
        return create_access_token(str(user.id), "SUPER_ADMIN")


async def _make_user(
    role_name: str,
    *,
    ward_code: str | None = None,
    email: str | None = None,
) -> tuple[uuid.UUID, str]:
    """Create a user with the given role. Returns (user_id, email)."""
    email = email or _unique_email(role_name.lower())
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == role_name))
        ward_id = None
        if ward_code:
            ward = await db.scalar(select(Ward).where(Ward.code == ward_code))
            ward_id = ward.id if ward else None
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=f"{role_name} Person",
            role_id=role.id,
            ward_id=ward_id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        _created_user_ids.append(user.id)
    return user.id, email


@pytest_asyncio.fixture(scope="module")
async def super_admin():
    token = await _make_super_admin()
    yield token


async def test_unauthenticated_returns_401(client):
    resp = await client.get(f"{_BASE}/summary")
    assert resp.status_code == 401


async def test_non_super_admin_gets_403(client, super_admin):
    # Create an ADMIN (not SUPER_ADMIN) user.
    _, admin_email = await _make_user("ADMIN")
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == admin_email))
        admin_token = create_access_token(str(user.id), "ADMIN")

    resp = await client.get(f"{_BASE}/summary", headers=_auth(admin_token))
    assert resp.status_code == 403

    resp2 = await client.get(f"{_BASE}/users", headers=_auth(admin_token))
    assert resp2.status_code == 403

    resp3 = await client.get(f"{_BASE}/config", headers=_auth(admin_token))
    assert resp3.status_code == 403


async def test_summary(client, super_admin):
    resp = await client.get(f"{_BASE}/summary", headers=_auth(super_admin))
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "users",
        "active_users",
        "roles",
        "wards",
        "departments",
        "field_workers",
        "representatives",
        "complaint_categories",
        "system_settings",
        "audit_logs",
    ):
        assert isinstance(body.get(key), int), key


# ---------- Users --------------------------------------------------------- #


async def test_user_create_list_search_filter(client, super_admin):
    # Create a citizen.
    resp = await client.post(
        f"{_BASE}/users",
        json={
            "email": _unique_email("cit"),
            "password": _PASSWORD,
            "full_name": "Cit Created",
            "role": "CITIZEN",
            "ward_code": "WARD-2",
            "is_email_verified": True,
        },
        headers=_auth(super_admin),
    )
    assert resp.status_code == 201, resp.text
    _created_user_ids.append(uuid.UUID(resp.json()["id"]))
    created_email = resp.json()["email"]

    # Create a field-worker with department.
    resp2 = await client.post(
        f"{_BASE}/users",
        json={
            "email": _unique_email("wk"),
            "password": _PASSWORD,
            "full_name": "Wk Created",
            "role": "FIELD_WORKER",
            "department_code": "SN",
            "specialty": "Sanitation",
            "worker_status": "ACTIVE",
            "skill_tags": ["cleaning"],
        },
        headers=_auth(super_admin),
    )
    assert resp2.status_code == 201, resp2.text
    _created_user_ids.append(uuid.UUID(resp2.json()["id"]))

    # Create a representative.
    resp3 = await client.post(
        f"{_BASE}/users",
        json={
            "email": _unique_email("rep"),
            "password": _PASSWORD,
            "full_name": "Rep Created",
            "role": "WARD_REPRESENTATIVE",
            "ward_code": "WARD-2",
            "rep_title": "Councillor",
        },
        headers=_auth(super_admin),
    )
    assert resp3.status_code == 201, resp3.text
    _created_user_ids.append(uuid.UUID(resp3.json()["id"]))

    # LIST: search for citizen by name.
    lst = await client.get(f"{_BASE}/users?search=Cit%20Created", headers=_auth(super_admin))
    assert lst.status_code == 200
    assert lst.json()["total"] >= 1
    assert any(u["email"] == created_email for u in lst.json()["items"])

    # LIST: filter by role.
    lst2 = await client.get(f"{_BASE}/users?role=CITIZEN", headers=_auth(super_admin))
    assert lst2.status_code == 200
    assert any(u["email"] == created_email for u in lst2.json()["items"])

    # GET one.
    uid = resp.json()["id"]
    got = await client.get(f"{_BASE}/users/{uid}", headers=_auth(super_admin))
    assert got.status_code == 200
    assert got.json()["full_name"] == "Cit Created"

    # UPDATE name.
    upd = await client.put(
        f"{_BASE}/users/{uid}",
        json={"full_name": "Cit Renamed"},
        headers=_auth(super_admin),
    )
    assert upd.status_code == 200
    assert upd.json()["full_name"] == "Cit Renamed"


async def test_user_disable_enable(client, super_admin):
    _, email = await _make_user("CITIZEN")
    uid = str((await _fetch_user(email)).id)

    resp = await client.patch(f"{_BASE}/users/{uid}/disable", headers=_auth(super_admin))
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp2 = await client.patch(f"{_BASE}/users/{uid}/enable", headers=_auth(super_admin))
    assert resp2.status_code == 200
    assert resp2.json()["is_active"] is True


async def test_admin_cannot_self_disable(client, super_admin):
    # Find the super admin's own user id.
    me = await client.get(f"{_BASE}/users?role=SUPER_ADMIN", headers=_auth(super_admin))
    my_id = me.json()["items"][0]["id"]
    resp = await client.patch(f"{_BASE}/users/{my_id}/disable", headers=_auth(super_admin))
    assert resp.status_code == 409


async def test_admin_cannot_disable_other_super_admin(client, super_admin):
    other_id, _ = await _make_user("SUPER_ADMIN")
    resp = await client.patch(f"{_BASE}/users/{other_id}/disable", headers=_auth(super_admin))
    assert resp.status_code == 409


async def test_create_user_rejects_weak_password(client, super_admin):
    resp = await client.post(
        f"{_BASE}/users",
        json={
            "email": _unique_email("wk"),
            "password": "short",
            "full_name": "W",
            "role": "CITIZEN",
        },
        headers=_auth(super_admin),
    )
    assert resp.status_code == 422


# ---------- Roles --------------------------------------------------------- #


async def test_role_crud_and_disable_guards(client, super_admin):
    rname = f"TC-ROLE-{uuid.uuid4().hex[:6].upper()}"
    resp = await client.post(
        f"{_BASE}/roles",
        json={"name": rname, "description": "test role"},
        headers=_auth(super_admin),
    )
    assert resp.status_code == 201, resp.text
    _created_role_names.append(rname)
    rid = resp.json()["id"]

    upd = await client.patch(
        f"{_BASE}/roles/{rid}",
        json={"description": "updated desc"},
        headers=_auth(super_admin),
    )
    assert upd.status_code == 200
    assert upd.json()["description"] == "updated desc"

    # Guard: cannot disable SUPER_ADMIN role.
    roles = (await client.get(f"{_BASE}/roles", headers=_auth(super_admin))).json()
    sa_id = next(r["id"] for r in roles if r["name"] == "SUPER_ADMIN")
    bad = await client.patch(
        f"{_BASE}/roles/{sa_id}", json={"is_active": False}, headers=_auth(super_admin)
    )
    assert bad.status_code == 409

    # Guard: cannot disable a role with active users (CITIZEN has seeded users).
    cit_id = next(r["id"] for r in roles if r["name"] == "CITIZEN")
    bad2 = await client.patch(
        f"{_BASE}/roles/{cit_id}", json={"is_active": False}, headers=_auth(super_admin)
    )
    assert bad2.status_code == 409


# ---------- Wards & Departments ------------------------------------------- #


async def test_ward_crud_and_unique_code_guard(client, super_admin):
    wcode = f"TCW{uuid.uuid4().hex[:4].upper()}"
    resp = await client.post(
        f"{_BASE}/wards",
        json={"name": "TC Ward", "code": wcode},
        headers=_auth(super_admin),
    )
    assert resp.status_code == 201, resp.text
    _created_ward_codes.append(wcode)
    wid = resp.json()["id"]

    dup = await client.post(
        f"{_BASE}/wards",
        json={"name": "Dup Ward", "code": wcode},
        headers=_auth(super_admin),
    )
    assert dup.status_code == 409

    upd = await client.patch(
        f"{_BASE}/wards/{wid}", json={"name": "TC Ward Renamed"}, headers=_auth(super_admin)
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "TC Ward Renamed"


async def test_department_crud(client, super_admin):
    dcode = f"TCD{uuid.uuid4().hex[:4].upper()}"
    resp = await client.post(
        f"{_BASE}/departments",
        json={"name": "TC Dept", "code": dcode},
        headers=_auth(super_admin),
    )
    assert resp.status_code == 201, resp.text
    _created_dept_codes.append(dcode)
    did = resp.json()["id"]

    dup = await client.post(
        f"{_BASE}/departments",
        json={"name": "Dup Dept", "code": dcode},
        headers=_auth(super_admin),
    )
    assert dup.status_code == 409

    # Inactive filter.
    await client.patch(
        f"{_BASE}/departments/{did}", json={"is_active": False}, headers=_auth(super_admin)
    )
    lst = await client.get(f"{_BASE}/departments?is_active=false", headers=_auth(super_admin))
    assert lst.status_code == 200
    inactive_codes = [d["code"] for d in lst.json()["items"]]
    assert dcode in inactive_codes


# ---------- Field Workers ------------------------------------------------- #


async def test_field_worker_update(client, super_admin):
    worker_id, _ = await _make_user("FIELD_WORKER")
    # _make_user does not create a FieldWorker profile; build one manually
    # (department_id is NOT NULL on the profile).
    async with async_session_factory() as db:
        from app.models import Department
        from app.models import FieldWorker as _FieldWorker

        dept = await db.scalar(select(Department).order_by(Department.created_at).limit(1))
        assert dept is not None
        _fw = _FieldWorker(user_id=worker_id, status="ACTIVE", department_id=dept.id)
        db.add(_fw)
        await db.commit()
        profile_id = _fw.id

    upd = await client.patch(
        f"{_BASE}/field-workers/{profile_id}",
        json={"status": "ON_LEAVE", "specialty": "Plumbing"},
        headers=_auth(super_admin),
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "ON_LEAVE"
    assert upd.json()["specialty"] == "Plumbing"


# ---------- Representatives ------------------------------------------------ #


async def test_representative_update(client, super_admin):
    rep_id, _ = await _make_user("WARD_REPRESENTATIVE", ward_code="WARD-1")
    # Ensure WardRepresentative profile exists.
    async with async_session_factory() as db:
        from app.models import WardRepresentative as _WardRep

        _wr = _WardRep(user_id=rep_id, ward_id=None, title="Councillor")
        ward = await db.scalar(select(Ward).where(Ward.code == "WARD-1"))
        _wr.ward_id = ward.id
        db.add(_wr)
        await db.commit()
        profile_id = _wr.id

    upd = await client.patch(
        f"{_BASE}/representatives/{profile_id}",
        json={"status": "SUSPENDED", "title": "Mayor"},
        headers=_auth(super_admin),
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "SUSPENDED"
    assert upd.json()["title"] == "Mayor"


# ---------- Complaint Categories ------------------------------------------ #


async def test_complaint_category_crud(client, super_admin):
    code = f"TC{uuid.uuid4().hex[:4].upper()}"
    resp = await client.post(
        f"{_BASE}/complaint-categories",
        json={"code": code, "label": "Test Cat", "sort_order": 7},
        headers=_auth(super_admin),
    )
    assert resp.status_code == 201, resp.text
    _created_category_codes.append(code)
    cid = resp.json()["id"]

    upd = await client.patch(
        f"{_BASE}/complaint-categories/{cid}",
        json={"label": "Renamed Cat", "is_active": False},
        headers=_auth(super_admin),
    )
    assert upd.status_code == 200
    assert upd.json()["label"] == "Renamed Cat"
    assert upd.json()["is_active"] is False


async def test_complaint_category_list_contains_seeded(client, super_admin):
    resp = await client.get(f"{_BASE}/complaint-categories", headers=_auth(super_admin))
    assert resp.status_code == 200
    codes = [c["code"] for c in resp.json()]
    assert "ROAD" in codes
    assert "SANITATION" in codes
    assert len(resp.json()) >= 13


# ---------- Priority Weights ---------------------------------------------- #


async def test_priority_weight_update_reverts(client, super_admin):
    # All six allow-listed keys are seeded, so a create is impossible;
    # update an existing seeded row and revert it.
    lst = await client.get(f"{_BASE}/priority-weights", headers=_auth(super_admin))
    assert lst.status_code == 200
    row = next(w for w in lst.json() if w["key"] == "infrastructure")
    wid = row["id"]
    original = row["weight"]

    upd = await client.patch(
        f"{_BASE}/priority-weights/{wid}",
        json={"weight": round(original + 0.01, 3), "is_active": False},
        headers=_auth(super_admin),
    )
    assert upd.status_code == 200
    assert upd.json()["weight"] == round(original + 0.01, 3)

    revert = await client.patch(
        f"{_BASE}/priority-weights/{wid}",
        json={"weight": original, "is_active": True},
        headers=_auth(super_admin),
    )
    assert revert.status_code == 200
    assert revert.json()["weight"] == original


async def test_priority_weight_rejects_invalid_key(client, super_admin):
    resp = await client.post(
        f"{_BASE}/priority-weights",
        json={"key": "totally_invalid", "label": "Bad", "weight": 0.5},
        headers=_auth(super_admin),
    )
    assert resp.status_code == 422


# ---------- SLA Rules ----------------------------------------------------- #


async def test_sla_crud(client, super_admin):
    resp = await client.post(
        f"{_BASE}/sla/policies",
        json={
            "name": "TC SLA Rule",
            "priority": "P1_CRITICAL",
            "department": "WATER",
            "sla_hours": 4,
            "at_risk_percent": 0.75,
        },
        headers=_auth(super_admin),
    )
    assert resp.status_code == 201, resp.text
    _created_sla_ids.append(uuid.UUID(resp.json()["id"]))
    pid = resp.json()["id"]

    # Duplicate identical dimension combination rejected.
    dup = await client.post(
        f"{_BASE}/sla/policies",
        json={"priority": "P1_CRITICAL", "department": "WATER", "sla_hours": 9},
        headers=_auth(super_admin),
    )
    assert dup.status_code == 409

    upd = await client.put(
        f"{_BASE}/sla/policies/{pid}",
        json={
            "name": "TC SLA Updated",
            "priority": "P2_HIGH",
            "department": "DRAINAGE",
            "sla_hours": 12,
            "at_risk_percent": 0.8,
        },
        headers=_auth(super_admin),
    )
    assert upd.status_code == 200 and upd.json()["sla_hours"] == 12

    dele = await client.delete(f"{_BASE}/sla/policies/{pid}", headers=_auth(super_admin))
    assert dele.status_code == 204
    _created_sla_ids.remove(uuid.UUID(pid))

    # Verify gone.
    lst = await client.get(f"{_BASE}/sla/policies", headers=_auth(super_admin))
    assert all(p["id"] != pid for p in lst.json())


# ---------- Configuration & Secrets --------------------------------------- #


async def test_config_never_leaks_secrets(client, super_admin):
    # Set a secret override.
    set_resp = await client.patch(
        f"{_BASE}/config/GROQ_API_KEY",
        json={"value": _TEST_SECRET},
        headers=_auth(super_admin),
    )
    assert set_resp.status_code == 200
    out = set_resp.json()
    assert out["configured"] is True
    assert out["value"] is None
    assert out["masked"] is not None
    assert _TEST_SECRET not in out["masked"]

    # Verify DB stores Fernet token, not plaintext.
    async with async_session_factory() as db:
        row = await db.scalar(select(SystemSetting).where(SystemSetting.key == "GROQ_API_KEY"))
        assert row.value != _TEST_SECRET

    # Clean up: clear the override.
    await client.delete(f"{_BASE}/config/GROQ_API_KEY", headers=_auth(super_admin))


async def test_config_clear_reverts_to_env(client, super_admin):
    set_resp = await client.patch(
        f"{_BASE}/config/GROQ_MODEL",
        json={"value": "my-custom-model"},
        headers=_auth(super_admin),
    )
    assert set_resp.status_code == 200

    clear_resp = await client.delete(f"{_BASE}/config/GROQ_MODEL", headers=_auth(super_admin))
    assert clear_resp.status_code == 200
    assert clear_resp.json()["source"] == "env"


async def test_groq_test_endpoint(client, super_admin):
    resp = await client.post(f"{_BASE}/config/groq/test", headers=_auth(super_admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "GROQ_API_KEY"
    assert body["configured"] in (True, False)
    assert body["reachable"] in (True, False)
    assert isinstance(body["message"], str)


# ---------- Audit Trail --------------------------------------------------- #


async def test_audit_logs(client, super_admin):
    # Mutating action: create a role.
    rname = f"TC-AUD-{uuid.uuid4().hex[:6].upper()}"
    resp = await client.post(
        f"{_BASE}/roles",
        json={"name": rname, "description": "audit test"},
        headers=_auth(super_admin),
    )
    assert resp.status_code == 201
    _created_role_names.append(rname)

    # Query: filter by action + entity_type.
    audit = await client.get(
        f"{_BASE}/audit-logs?action=create&entity_type=role",
        headers=_auth(super_admin),
    )
    assert audit.status_code == 200
    body = audit.json()
    assert body["total"] >= 1
    assert body["items"][0]["actor_email"] is not None
    assert any(e["entity_type"] == "role" and e["action"] == "create" for e in body["items"])


# ---------- Helpers ------------------------------------------------------- #


async def _fetch_user(email: str) -> User:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        return user
