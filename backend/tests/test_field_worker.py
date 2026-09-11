"""Tests for the Field Worker Application (Part 18).

Exercises the full field worker lifecycle through the ``/worker`` API:

* **Dashboard** — assigned / nearby / P1 / completed queues, ranked by distance
  from the worker's home base (or supplied GPS override).
* **Workflow** — accept → check-in (EN_ROUTE / ARRIVED with GPS capture) → start
  (IN_PROGRESS) → before/after photo upload → notes → complete (COMPLETED), with
  the complaint resolving in lockstep and the owner/ward notified.
* **GPS privacy** — check-ins record coordinates only when supplied; a denied /
  unavailable fix is recorded via ``geo_denied`` instead.
* **Idempotency (network interruption)** — re-playing the same queued action
  (same ``client_ref``) returns the same state without duplicating activity rows.
* **RBAC** — FIELD_WORKER only; citizens/officers/users with no worker profile
  are rejected appropriately; orders assigned to someone else are hidden.
"""

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    Complaint,
    Department,
    FieldWorker,
    Role,
    User,
    UserProfile,
    WorkerAssignment,
    WorkOrder,
    WorkOrderActivity,
    WorkOrderPhoto,
)
from app.models.enums import RoleName, WorkerStatus, WorkOrderStatus
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_WORKER_API = "/api/v1/worker"
_COMPLAINTS = "/api/v1/complaints"
_SETTINGS = get_settings()
_LAT = 17.4327
_LON = 78.3885


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _valid_png() -> bytes:
    """A real 1x1 PNG so Pillow's verify() succeeds (client-side GIF/PNG/JPEG)."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        from app.schemas.auth import RegisterIn
        from app.services import auth_service

        await auth_service.register_user(
            db, RegisterIn(
                    email=email,
                    password=_PASSWORD,
                    full_name="FieldWorker Citizen",
                    ward_id=await any_active_ward_id(db),
                )
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _officer(email: str) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="FieldWorker Officer",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), RoleName.OFFICER.value)


async def _seed_worker(
    *,
    email: str,
    dept_code: str = "WASTE",
    name: str = "Field Worker",
    lat: float = _LAT,
    lon: float = _LON,
) -> str:
    """Create a FIELD_WORKER account + profile and return its login token."""
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=name,
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        dept = await db.scalar(select(Department).where(Department.code == dept_code))
        if dept is None:
            dept = Department(name=dept_code, code=dept_code, description=f"{dept_code} crew")
            db.add(dept)
            await db.flush()
        db.add(
            FieldWorker(
                user_id=user.id,
                department_id=dept.id,
                status=WorkerStatus.ACTIVE,
                home_latitude=lat,
                home_longitude=lon,
                skill_tags=["collections"],
                equipment=["garbage-truck"],
            )
        )
        await db.commit()
        return create_access_token(str(user.id), RoleName.FIELD_WORKER.value)


async def _complain(client, token: str, *, lat: float = _LAT, lon: float = _LON) -> str:
    """Create a complaint the way a citizen would."""
    body = {
        "description": "Field worker API test complaint",
        "category": "GARBAGE",
        "media_ids": [],
        "location": {
            "latitude": lat,
            "longitude": lon,
            "address": "Test location",
            "source": "gps",
            "geopoint_denied": False,
        },
    }
    r = await client.post(_COMPLAINTS, json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _assign(
    client, token: str, complaint_id: str, worker_id: str, *, status: str = "ASSIGNED"
) -> str:
    """Seed a work order assigned to ``worker_id`` on ``complaint_id``."""
    async with async_session_factory() as db:
        order = WorkOrder(
            complaint_id=complaint_id,
            department="WASTE",
            priority="P1_CRITICAL",
            location_lat=_LAT,
            location_lon=_LON,
            address="Test location",
            status=status,
            worker_id=worker_id,
            sla_hours=24,
            created_by=None,
        )
        db.add(order)
        await db.flush()
        db.add(
            WorkerAssignment(
                work_order_id=order.id,
                worker_id=worker_id,
                status="ASSIGNED",
                assigned_by=None,
                reason="seeded for field worker test",
            )
        )
        await db.commit()
        return str(order.id)


async def _seed_unassigned_order(complaint_id: str, *, lat: float = _LAT, lon: float = _LON) -> str:
    """Seed a work order with no worker assigned (shows up in "nearby")."""
    async with async_session_factory() as db:
        order = WorkOrder(
            complaint_id=complaint_id,
            department="WASTE",
            priority="P2_HIGH",
            location_lat=lat,
            location_lon=lon,
            address="Nearby location",
            status="ASSIGNED",
            worker_id=None,
            sla_hours=48,
            created_by=None,
        )
        db.add(order)
        await db.commit()
        return str(order.id)


async def _worker_id(token: str) -> str:
    async with async_session_factory() as db:
        from app.core.security import decode_token

        claims = decode_token(token, "access")
        uid = uuid.UUID(claims["sub"])
        fw = await db.scalar(select(FieldWorker).where(FieldWorker.user_id == uid))
        return str(fw.id)


async def _cleanup() -> None:
    async with async_session_factory() as db:
        await db.execute(delete(WorkOrderActivity))
        await db.execute(delete(WorkOrderPhoto))
        await db.execute(delete(WorkerAssignment))
        await db.execute(delete(WorkOrder))
        fws = (await db.execute(select(FieldWorker))).scalars().all()
        for fw in fws:
            await db.delete(fw)
        rrole = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        for u in (await db.execute(select(User).where(User.role_id == rrole.id))).scalars().all():
            await db.delete(u)
        await db.commit()


@pytest.fixture(autouse=True)
async def _leave_db_clean():
    """Remove this module's workers/orders/assignments after each test.

    ``_clear_workers`` in other suites (e.g. dispatch) ORM-deletes field workers
    and SQLAlchemy nulls their referencing ``worker_assignments.worker_id``, which
    trips the NOT NULL constraint. Leaving no rows behind keeps run order
    deterministic.
    """
    yield
    await _cleanup()


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dashboard_queues(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-citizen"))
    wtoken = await _seed_worker(email=_unique_email("fw-dash"), name="Dash Worker")
    wid = await _worker_id(wtoken)

    far_token = await _seed_worker(
        email=_unique_email("fw-far"), name="Far Worker", lat=_LAT + 5.0, lon=_LON
    )
    cid_assigned = await _complain(client, citizen)
    cid_completed = await _complain(client, citizen)

    order_mine = await _assign(client, citizen, cid_assigned, wid)
    order_done = await _assign(client, citizen, cid_completed, wid, status="COMPLETED")
    # A completed order marked with completed_at through the completed state.
    async with async_session_factory() as db:
        done = await db.scalar(select(WorkOrder).where(WorkOrder.id == order_done))
        done.status = WorkOrderStatus.COMPLETED
        from datetime import UTC, datetime

        done.completed_at = datetime.now(UTC)
        await db.commit()
    # Unassigned nearby job.
    await _seed_unassigned_order(await _complain(client, citizen, lat=_LAT, lon=_LON))

    r = await client.get(f"{_WORKER_API}/dashboard", headers=_auth(wtoken))
    assert r.status_code == 200, r.text
    data = r.json()

    assert len(data["assigned"]) == 1
    assert data["assigned"][0]["id"] == order_mine
    assert data["assigned"][0]["priority"] == "P1_CRITICAL"
    assert (data["assigned"][0]["distance_m"] or 0) < 1000

    assert len(data["p1"]) == 1  # the assigned P1 job

    assert len(data["completed"]) == 1
    assert data["completed"][0]["id"] == order_done

    assert len(data["nearby"]) == 1  # the unassigned nearby job
    assert data["nearby"][0]["id"] != order_mine

    # GPS override from the far worker's location ranks nearby accordingly.
    r2 = await client.get(
        f"{_WORKER_API}/dashboard?latitude={_LAT + 5}&longitude={_LON}",
        headers=_auth(far_token),
    )
    assert r2.status_code == 200
    assert r2.json()["nearby"]  # far worker still sees the nearby job


@pytest.mark.asyncio
async def test_worker_sees_full_work_order_after_officer_assignment(client):
    """The worker's dashboard + detail carry the *real* order: work-order &
    complaint ids, category, ward, department, priority, location, current
    status, plus assignment provenance (when and by which officer)."""
    await _cleanup()
    from app.core.security import decode_token

    citizen_email = _unique_email("fw-citizen-provenance")
    citizen = await _citizen_token(citizen_email)
    officer_email = _unique_email("fw-officer-provenance")
    otoken = await _officer(officer_email)
    wtoken = await _seed_worker(email=_unique_email("fw-sees-order"), name="Provenance Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)

    async with async_session_factory() as db:
        claims = decode_token(otoken, "access")
        officer = await db.get(User, uuid.UUID(claims["sub"]))

        # Authoritative ward = the citizen's registered ward (the ward label the
        # officer sees on the live complaint).
        citizen_user = await db.scalar(select(User).where(User.email == citizen_email))
        complaint = await db.get(Complaint, cid)
        complaint.ward_id = citizen_user.ward_id
        await db.commit()

    order = WorkOrder(
        complaint_id=cid,
        department="WASTE",
        incident="Dumped garbage blocking the lane",
        priority="P1_CRITICAL",
        location_lat=_LAT,
        location_lon=_LON,
        address="Test location",
        status="ASSIGNED",
        worker_id=wid,
        sla_hours=24,
        created_by=None,
    )
    async with async_session_factory() as db:
        db.add(order)
        await db.flush()
        db.add(
            WorkerAssignment(
                work_order_id=order.id,
                worker_id=wid,
                status="ASSIGNED",
                assigned_by=officer.id,
                reason="assigned by officer (provenance test)",
            )
        )
        await db.commit()
        order_id = str(order.id)
        complaint = await db.scalar(
            select(Complaint).where(Complaint.id == cid).options(selectinload(Complaint.ward))
        )
        ward_name = complaint.ward.name
        ward_code = complaint.ward.code

    r = await client.get(f"{_WORKER_API}/dashboard", headers=_auth(wtoken))
    assert r.status_code == 200, r.text
    assigned = r.json()["assigned"]
    assert len(assigned) == 1
    job = assigned[0]
    assert job["id"] == order_id
    assert job["complaint_id"] == cid
    assert job["incident"]  # real incident title from the order
    assert job["category"] == "GARBAGE"
    assert job["department"] == "WASTE"
    assert job["priority"] == "P1_CRITICAL"
    assert job["status"] == "ASSIGNED"
    assert job["ward_name"] == ward_name
    assert job["ward_code"] == ward_code
    assert job["assigned_at"] is not None
    assert job["assigned_by_name"] == officer.full_name

    r2 = await client.get(f"{_WORKER_API}/orders/{order_id}", headers=_auth(wtoken))
    assert r2.status_code == 200, r2.text
    detail = r2.json()["work_order"]
    for key in (
        "id",
        "complaint_id",
        "incident",
        "category",
        "department",
        "priority",
        "status",
        "ward_name",
        "ward_code",
        "assigned_at",
        "assigned_by_name",
        "address",
    ):
        assert detail[key] == job[key], f"detail/job differ on {key!r}"
    assert detail["location_lat"] == job["location_lat"]
    assert detail["location_lon"] == job["location_lon"]


# --------------------------------------------------------------------------- #
# RBAC + profile gating
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dashboard_requires_field_worker(client):
    await _cleanup()
    otoken = await _officer(_unique_email("fw-officer"))
    r = await client.get(f"{_WORKER_API}/dashboard", headers=_auth(otoken))
    assert r.status_code == 403

    citizen = await _citizen_token(_unique_email("fw-citizen-rbac"))
    r2 = await client.get(f"{_WORKER_API}/dashboard", headers=_auth(citizen))
    assert r2.status_code == 403

    r3 = await client.get(f"{_WORKER_API}/dashboard")
    assert r3.status_code == 401


@pytest.mark.asyncio
async def test_worker_without_profile_404(client):
    await _cleanup()
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
        user = User(
            email=_unique_email("fw-noprofile"),
            password_hash=hash_password(_PASSWORD),
            full_name="No Profile",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        token = create_access_token(str(user.id), RoleName.FIELD_WORKER.value)
    r = await client.get(f"{_WORKER_API}/dashboard", headers=_auth(token))
    assert r.status_code == 404
    r2 = await client.get(f"{_WORKER_API}/me", headers=_auth(token))
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_worker_profile_me(client):
    """GET /worker/me surfaces the worker's real account + profile fields.

    Name/role/department/ward come straight from the linked account and the
    admin-managed FieldWorker record — nothing is editable by the worker app.
    """
    await _cleanup()
    email = _unique_email("fw-profile")
    wtoken = await _seed_worker(email=email, name="Profile Worker")
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        user.ward_id = await any_active_ward_id(db)
        await db.commit()
        user = await db.scalar(
            select(User).where(User.id == user.id).options(selectinload(User.ward))
        )
        ward_code = user.ward.code if user.ward else None

    r = await client.get(f"{_WORKER_API}/me", headers=_auth(wtoken))
    assert r.status_code == 200, r.text
    profile = r.json()
    assert profile["full_name"] == "Profile Worker"
    assert profile["email"] == email
    assert profile["role"] == RoleName.FIELD_WORKER.value
    assert profile["department_code"] == "WASTE"
    assert profile["status"] == "ACTIVE"
    assert profile["skill_tags"] == ["collections"]
    assert profile["equipment"] == ["garbage-truck"]
    assert profile["home_latitude"] == _LAT
    assert profile["home_longitude"] == _LON
    assert profile["ward_code"] == ward_code


async def _upload_evidence_photos(client, order_id, token, prefix="ev"):
    """Upload BEFORE + AFTER work photos (required before submit-evidence)."""
    png = _valid_png()
    for category in ("BEFORE", "AFTER"):
        r = await client.post(
            f"{_WORKER_API}/orders/{order_id}/photos",
            files={"file": (f"{prefix}-{category.lower()}.png", png, "image/png")},
            data={"category": category, "client_ref": f"{prefix}-photo-{category.lower()}"},
            headers=token,
        )
        assert r.status_code == 200, f"photo {category}: {r.text}"


# --------------------------------------------------------------------------- #
# Workflow: accept → check-in → start → photos → notes → finish → submit evidence
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_full_workflow_accept_start_photos_notes_finish_submit_evidence(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-wf-citizen"))
    wtoken = await _seed_worker(email=_unique_email("fw-wf"), name="Workflow Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid)

    # --- accept ---
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/accept",
        json={"latitude": _LAT, "longitude": _LON, "client_ref": "acc-1"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["work_order"]["status"] == "ASSIGNED"
    assert body["work_order"]["accepted_at"] is not None
    # acceptance write to the complaints status history too
    act_types = [a["activity_type"] for a in body["activities"]]
    assert "ACCEPT" in act_types

    # --- check-ins (GPS capture) ---
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={
            "activity_type": "EN_ROUTE",
            "latitude": _LAT,
            "longitude": _LON + 0.001,
            "accuracy_m": 18.5,
            "client_ref": "enr-1",
        },
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    enroute = [a for a in r.json()["activities"] if a["activity_type"] == "EN_ROUTE"]
    assert enroute and enroute[-1]["latitude"] is not None
    assert enroute[-1]["accuracy_m"] == 18.5

    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={
            "activity_type": "ARRIVED",
            "latitude": _LAT,
            "longitude": _LON,
            "accuracy_m": 12.0,
            "client_ref": "arr-1",
        },
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    arrived = [a for a in r.json()["activities"] if a["activity_type"] == "ARRIVED"]
    assert arrived and arrived[-1]["accuracy_m"] == 12.0

    # --- start → IN_PROGRESS ---
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "start-1"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["work_order"]["status"] == "IN_PROGRESS"
    assert body["work_order"]["started_at"] is not None

    # complaint advanced to IN_PROGRESS in lockstep
    cd = await client.get(f"{_COMPLAINTS}/{cid}", headers=_auth(citizen))
    assert cd.json()["status"] == "IN_PROGRESS"

    # --- before photo ---
    png = _valid_png()
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/photos",
        files={"file": ("before.png", png, "image/png")},
        data={"category": "BEFORE", "client_ref": "photo-before-1"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["work_order"]["has_before_photo"] is True
    photos = body["photos"]
    assert photos and photos[0]["category"] == "BEFORE"

    # --- after photo ---
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/photos",
        files={"file": ("after.png", png, "image/png")},
        data={"category": "AFTER", "client_ref": "photo-after-1"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    assert r.json()["work_order"]["has_after_photo"] is True

    # --- notes ---
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/notes",
        json={"notes": "Cleared the garbage pile, site is tidy now.", "client_ref": "notes-1"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    assert r.json()["work_order"]["worker_notes"] == "Cleared the garbage pile, site is tidy now."

    # --- finish work → WORK_COMPLETED (complaint NOT resolved yet) ---
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/finish",
        json={"notes": "Done", "client_ref": "finish-1"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["work_order"]["status"] == "WORK_COMPLETED"
    assert body["work_order"]["completed_at"] is not None
    act_types = [a["activity_type"] for a in body["activities"]]
    assert "FINISH_WORK" in act_types

    # the worker finishing work must NOT resolve the complaint
    cd = await client.get(f"{_COMPLAINTS}/{cid}", headers=_auth(citizen))
    assert cd.json()["status"] == "IN_PROGRESS"
    notif = await client.get("/api/v1/notifications", headers=_auth(citizen))
    types = [n["notification_type"] for n in notif.json()["items"]]
    assert "WORK_ORDER_COMPLETED" not in types

    # --- submit resolution evidence → EVIDENCE_SUBMITTED ---
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/submit-evidence",
        json={"notes": "Before/after photos attached.", "client_ref": "evidence-1"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["work_order"]["status"] == "EVIDENCE_SUBMITTED"
    assert body["work_order"]["evidence_submitted_at"] is not None
    act_types = [a["activity_type"] for a in body["activities"]]
    assert "SUBMIT_EVIDENCE" in act_types

    # still not resolved — the AI verification stage confirms it, not the worker
    cd = await client.get(f"{_COMPLAINTS}/{cid}", headers=_auth(citizen))
    assert cd.json()["status"] == "IN_PROGRESS"
    notif = await client.get("/api/v1/notifications", headers=_auth(citizen))
    types = [n["notification_type"] for n in notif.json()["items"]]
    assert "WORK_ORDER_COMPLETED" not in types

    # state persists on a fresh sync pull
    r = await client.get(f"{_WORKER_API}/orders/{order_id}", headers=_auth(wtoken))
    assert r.status_code == 200, r.text
    detail = r.json()["work_order"]
    assert detail["status"] == "EVIDENCE_SUBMITTED"
    assert detail["evidence_submitted_at"] is not None


# --------------------------------------------------------------------------- #
# GPS denied / privacy
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_gps_denied_check_in_records_without_coords(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-gps-citizen"))
    wtoken = await _seed_worker(email=_unique_email("fw-gps"), name="GPS Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid)

    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={
            "activity_type": "ARRIVED",
            "geo_denied": True,
            "note": "GPS permission denied.",
            "client_ref": "gps-denied-1",
        },
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    acts = r.json()["activities"]
    arrived = [a for a in acts if a["activity_type"] == "ARRIVED"]
    assert arrived
    assert arrived[-1]["geo_denied"] is True
    assert arrived[-1]["latitude"] is None and arrived[-1]["longitude"] is None

    # invalid coordinates are rejected outright
    r2 = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={"activity_type": "EN_ROUTE", "latitude": 999, "longitude": 0},
        headers=_auth(wtoken),
    )
    assert r2.status_code == 422


# --------------------------------------------------------------------------- #
# Idempotency / network interruption
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_replay_same_client_ref_is_idempotent(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-sync-citizen"))
    wtoken = await _seed_worker(email=_unique_email("fw-sync"), name="Sync Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid)

    # Accept → GPS check-in → start (check-in is a hard prerequisite of start).
    first_accept = await client.post(
        f"{_WORKER_API}/orders/{order_id}/accept",
        json={"client_ref": "acc-before-sync"},
        headers=_auth(wtoken),
    )
    assert first_accept.status_code == 200
    first_checkin = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={"activity_type": "ARRIVED", "client_ref": "cin-sync-1", "latitude": _LAT, "longitude": _LON},
        headers=_auth(wtoken),
    )
    assert first_checkin.status_code == 200
    first = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "start-sync-1"},
        headers=_auth(wtoken),
    )
    assert first.status_code == 200
    replayed = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "start-sync-1"},
        headers=_auth(wtoken),
    )
    assert replayed.status_code == 200
    assert replayed.json()["work_order"]["status"] == "IN_PROGRESS"

    async with async_session_factory() as db:
        count = (
            (
                await db.execute(
                    select(WorkOrderActivity).where(WorkOrderActivity.client_ref == "start-sync-1")
                )
            )
            .scalars()
            .all()
        )
        assert len(count) == 1  # never duplicated

    # accept replay is equally idempotent
    await client.post(
        f"{_WORKER_API}/orders/{order_id}/accept",
        json={"client_ref": "acc-sync-1"},
        headers=_auth(wtoken),
    )
    async with async_session_factory() as db:
        count2 = (
            (
                await db.execute(
                    select(WorkOrderActivity).where(WorkOrderActivity.client_ref == "acc-sync-1")
                )
            )
            .scalars()
            .all()
        )
        assert len(count2) == 0  # already started → accept is a no-op, nothing recorded
    # ...and accept after start does not error (already accepted → no-op)
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/accept",
        json={"client_ref": "acc-sync-2"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# START WORK gates
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_start_requires_gps_check_in(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-gate-citizen"))
    wtoken = await _seed_worker(email=_unique_email("fw-gate"), name="Gate Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid)

    # Assigned, not yet accepted, no check-in → start is rejected.
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "gate-start-0"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 409

    # Accept, still no check-in → start is rejected.
    acc = await client.post(
        f"{_WORKER_API}/orders/{order_id}/accept",
        json={"client_ref": "gate-accept"},
        headers=_auth(wtoken),
    )
    assert acc.status_code == 200
    r2 = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "gate-start-1"},
        headers=_auth(wtoken),
    )
    assert r2.status_code == 409

    # GPS check-in unlocks START WORK.
    cin = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={
            "activity_type": "ARRIVED",
            "latitude": _LAT,
            "longitude": _LON,
            "accuracy_m": 9.4,
            "client_ref": "gate-cin",
        },
        headers=_auth(wtoken),
    )
    assert cin.status_code == 200, cin.text
    started = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "gate-start-2"},
        headers=_auth(wtoken),
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["work_order"]["status"] == "IN_PROGRESS"
    assert body["work_order"]["started_at"] is not None
    # Audit trail: START_WORK status-history entry recorded with the actor.
    history = [h for h in body["status_history"] if h["action"] == "START_WORK"]
    assert history, "start must write a START_WORK audit event"


@pytest.mark.asyncio
async def test_finish_and_submit_evidence_state_machine(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-fsm-citizen"))
    wtoken = await _seed_worker(email=_unique_email("fw-fsm"), name="FSM Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid)
    token = _auth(wtoken)

    await _upload_evidence_photos(client, order_id, token, "fsm")

    # finish / submit-evidence are hard-gated before any work is started.
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/finish",
        json={"client_ref": "fsm-finish-0"},
        headers=token,
    )
    assert r.status_code == 409, r.text
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/submit-evidence",
        json={"client_ref": "fsm-evidence-0"},
        headers=token,
    )
    assert r.status_code == 409, r.text

    # accept → GPS check-in → start unlocks FINISH WORK.
    acc = await client.post(
        f"{_WORKER_API}/orders/{order_id}/accept",
        json={"latitude": _LAT, "longitude": _LON, "client_ref": "fsm-accept"},
        headers=token,
    )
    assert acc.status_code == 200, acc.text
    cin = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={
            "activity_type": "ARRIVED",
            "latitude": _LAT,
            "longitude": _LON,
            "accuracy_m": 9.4,
            "client_ref": "fsm-cin",
        },
        headers=token,
    )
    assert cin.status_code == 200, cin.text
    st = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "fsm-start"},
        headers=token,
    )
    assert st.status_code == 200, st.text

    # submit-evidence before finishing is rejected.
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/submit-evidence",
        json={"client_ref": "fsm-evidence-early"},
        headers=token,
    )
    assert r.status_code == 409, r.text

    # finish → WORK_COMPLETED (completed_at set, complaint untouched).
    fin = await client.post(
        f"{_WORKER_API}/orders/{order_id}/finish",
        json={"client_ref": "fsm-finish"},
        headers=token,
    )
    assert fin.status_code == 200, fin.text
    body = fin.json()
    assert body["work_order"]["status"] == "WORK_COMPLETED"
    assert body["work_order"]["completed_at"] is not None
    assert body["work_order"]["evidence_submitted_at"] is None
    cd = await client.get(f"{_COMPLAINTS}/{cid}", headers=_auth(citizen))
    assert cd.json()["status"] == "IN_PROGRESS"

    # finishing twice / starting after finishing / checking-in late → all 409.
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/finish",
        json={"client_ref": "fsm-finish-2"},
        headers=token,
    )
    assert r.status_code == 409, r.text
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "fsm-start-late"},
        headers=token,
    )
    assert r.status_code == 409, r.text
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={"activity_type": "ARRIVED", "client_ref": "fsm-cin-late"},
        headers=token,
    )
    assert r.status_code == 409, r.text

    # submit evidence → EVIDENCE_SUBMITTED (evidence timestamp persisted).
    ev = await client.post(
        f"{_WORKER_API}/orders/{order_id}/submit-evidence",
        json={"client_ref": "fsm-evidence"},
        headers=token,
    )
    assert ev.status_code == 200, ev.text
    body = ev.json()
    assert body["work_order"]["status"] == "EVIDENCE_SUBMITTED"
    assert body["work_order"]["evidence_submitted_at"] is not None
    assert body["work_order"]["completed_at"] is not None
    history = {h["action"] for h in body["status_history"]}
    assert "FINISH_WORK" in history
    assert "SUBMIT_EVIDENCE" in history

    # status + evidence_submitted_at survive a fresh sync pull.
    r = await client.get(f"{_WORKER_API}/orders/{order_id}", headers=token)
    assert r.status_code == 200, r.text
    detail = r.json()["work_order"]
    assert detail["status"] == "EVIDENCE_SUBMITTED"
    assert detail["evidence_submitted_at"] is not None

    # a second submit (new client_ref) is rejected; replay returns same state.
    r2 = await client.post(
        f"{_WORKER_API}/orders/{order_id}/submit-evidence",
        json={"client_ref": "fsm-evidence-again"},
        headers=token,
    )
    assert r2.status_code == 409, r2.text
    replay = await client.post(
        f"{_WORKER_API}/orders/{order_id}/submit-evidence",
        json={"client_ref": "fsm-evidence"},
        headers=token,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["work_order"]["status"] == "EVIDENCE_SUBMITTED"
    async with async_session_factory() as db:
        count = (
            (
                await db.execute(
                    select(WorkOrderActivity).where(WorkOrderActivity.client_ref == "fsm-evidence")
                )
            )
            .scalars()
            .all()
        )
        assert len(count) == 1  # idempotent replay never duplicates


# --------------------------------------------------------------------------- #
# Dashboard grouping
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_evidence_submitted_order_moves_to_completed_queue(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-dq-citizen"))
    wtoken = await _seed_worker(email=_unique_email("fw-dq"), name="DQ Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid)
    token = _auth(wtoken)

    await _upload_evidence_photos(client, order_id, token, "dq")

    await client.post(
        f"{_WORKER_API}/orders/{order_id}/accept",
        json={"client_ref": "dq-accept", "latitude": _LAT, "longitude": _LON},
        headers=token,
    )
    await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={"activity_type": "ARRIVED", "latitude": _LAT, "longitude": _LON, "client_ref": "dq-cin"},
        headers=token,
    )
    await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "dq-start"},
        headers=token,
    )
    await client.post(
        f"{_WORKER_API}/orders/{order_id}/finish",
        json={"client_ref": "dq-finish"},
        headers=token,
    )

    # WORK_COMPLETED (work done, evidence pending) still shows as an active job.
    dash = await client.get(f"{_WORKER_API}/dashboard", headers=token)
    db0 = dash.json()
    assert order_id in {o["id"] for o in db0["assigned"]}
    assert order_id not in {o["id"] for o in db0["completed"]}

    await client.post(
        f"{_WORKER_API}/orders/{order_id}/submit-evidence",
        json={"client_ref": "dq-evidence"},
        headers=token,
    )

    # EVIDENCE_SUBMITTED is worker-done → moves to the completed queue.
    dash = await client.get(f"{_WORKER_API}/dashboard", headers=token)
    db1 = dash.json()
    assert order_id in {o["id"] for o in db1["completed"]}
    assert order_id not in {o["id"] for o in db1["assigned"]}


# --------------------------------------------------------------------------- #
# State + ownership guardrails
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_finish_and_evidence_guards_on_idle_states(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-idle-citizen"))
    wtoken = await _seed_worker(email=_unique_email("fw-idle"), name="Idle Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid)

    # With no work done, finish / submit-evidence are rejected.
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/finish",
        json={"client_ref": "idle-finish"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 409
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/submit-evidence",
        json={"client_ref": "idle-evidence"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_order_assigned_to_other_worker_is_hidden(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-hidden-citizen"))
    wtoken_a = await _seed_worker(email=_unique_email("fw-a"), name="Worker A")
    wtoken_b = await _seed_worker(email=_unique_email("fw-b"), name="Worker B")
    wid_a = await _worker_id(wtoken_a)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid_a)

    r = await client.get(f"{_WORKER_API}/orders/{order_id}", headers=_auth(wtoken_b))
    assert r.status_code == 404

    r2 = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "b-start-1"},
        headers=_auth(wtoken_b),
    )
    assert r2.status_code == 404


# --------------------------------------------------------------------------- #
# Rework (Part 28): officer rejects evidence → worker restarts the job
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_worker_rework_cycle(client):
    """Officer REQUEST_REWORK → worker returns, restarts, re-submits evidence."""
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-rework-cit"))
    otoken = await _officer(_unique_email("fw-rework-off"))
    wtoken = await _seed_worker(email=_unique_email("fw-rework"), name="Rework Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid)
    token = _auth(wtoken)

    await _upload_evidence_photos(client, order_id, token, "rw")

    # 1) First full round → EVIDENCE_SUBMITTED.
    for path, payload in [
        ("accept", {"client_ref": "rw-accept"}),
        (
            "check-in",
            {
                "activity_type": "ARRIVED",
                "latitude": _LAT,
                "longitude": _LON,
                "client_ref": "rw-cin",
            },
        ),
        ("start", {"client_ref": "rw-start"}),
        ("finish", {"client_ref": "rw-finish"}),
        ("submit-evidence", {"client_ref": "rw-evidence"}),
    ]:
        r = await client.post(
            f"{_WORKER_API}/orders/{order_id}/{path}", json=payload, headers=token
        )
        assert r.status_code == 200, f"{path}: {r.text}"
    assert (
        (await client.get(f"{_WORKER_API}/orders/{order_id}", headers=token))
        .json()["work_order"]["status"]
        == "EVIDENCE_SUBMITTED"
    )

    # 2) Officer runs verification (human review required) + requests rework.
    from app.models import WorkOrderVerification

    async with async_session_factory() as db:
        db.add(
            WorkOrderVerification(
                work_order_id=uuid.UUID(order_id),
                complaint_id=uuid.UUID(cid),
                verification_status="NEEDS_HUMAN_REVIEW",
                human_review_required=True,
                confidence=0.4,
            )
        )
        await db.commit()
    r = await client.post(
        f"/api/v1/work-orders/{order_id}/verification/review",
        json={"decision": "REQUEST_REWORK", "note": "Garbage pile not fully cleared."},
        headers=_auth(otoken),
    )
    assert r.status_code == 200, r.text
    assert r.json()["rework_requested"] is True
    assert r.json()["work_order_status"] == "RETURNED_FOR_REWORK"

    # 3) Worker sees the returned order + rework reason (evidence kept until they restart).
    detail = (await client.get(f"{_WORKER_API}/orders/{order_id}", headers=token)).json()
    wo = detail["work_order"]
    assert wo["status"] == "RETURNED_FOR_REWORK"
    assert wo["rework_reason"] == "Garbage pile not fully cleared."
    assert wo["completed_at"] is not None
    assert wo["evidence_submitted_at"] is not None
    dash = (await client.get(f"{_WORKER_API}/dashboard", headers=token)).json()
    assert order_id in {o["id"] for o in dash["assigned"]}
    assert order_id not in {o["id"] for o in dash["completed"]}

    # 4) Generic START WORK is forbidden on a returned order; rework early is too
    #    (no fresh check-in AFTER the rework request yet).
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start", json={"client_ref": "rw-start-bad"}, headers=token
    )
    assert r.status_code == 409, r.text
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start-rework",
        json={"client_ref": "rw-sr-early"},
        headers=token,
    )
    assert r.status_code == 409, r.text

    # 5) A fresh GPS check-in unlocks START_REWORK → IN_PROGRESS, stale timestamps cleared.
    cin = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={
            "activity_type": "ARRIVED",
            "latitude": _LAT,
            "longitude": _LON,
            "client_ref": "rw-cin-2",
        },
        headers=token,
    )
    assert cin.status_code == 200, cin.text
    sr = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start-rework",
        json={"note": "Returning to clear the pile.", "client_ref": "rw-sr"},
        headers=token,
    )
    assert sr.status_code == 200, sr.text
    body = sr.json()
    assert body["work_order"]["status"] == "IN_PROGRESS"
    assert body["work_order"]["completed_at"] is None
    assert body["work_order"]["evidence_submitted_at"] is None
    assert body["work_order"]["rework_reason"] == "Garbage pile not fully cleared."
    actions = {h["action"] for h in body["status_history"]}
    assert "START_REWORK" in actions

    # start_rework replay (same client_ref) is idempotent.
    replay = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start-rework",
        json={"client_ref": "rw-sr"},
        headers=token,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["work_order"]["status"] == "IN_PROGRESS"

    # 6) Second round finish + submit-evidence → EVIDENCE_SUBMITTED again.
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/finish", json={"client_ref": "rw-finish-2"}, headers=token
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/submit-evidence",
        json={"client_ref": "rw-evidence-2"},
        headers=token,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["work_order"]["status"] == "EVIDENCE_SUBMITTED"
    assert body["work_order"]["evidence_submitted_at"] is not None
