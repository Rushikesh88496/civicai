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

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
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
            db, RegisterIn(email=email, password=_PASSWORD, full_name="FieldWorker Citizen")
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


# --------------------------------------------------------------------------- #
# Workflow: accept → check-in → start → photos → notes → complete
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_full_workflow_accept_start_photos_notes_complete(client):
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
            "client_ref": "enr-1",
        },
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/check-in",
        json={
            "activity_type": "ARRIVED",
            "latitude": _LAT,
            "longitude": _LON,
            "client_ref": "arr-1",
        },
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text

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

    # --- complete → COMPLETED + complaint RESOLVED + notification ---
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/complete",
        json={"notes": "Done", "client_ref": "complete-1"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["work_order"]["status"] == "COMPLETED"
    assert body["work_order"]["completed_at"] is not None

    cd = await client.get(f"{_COMPLAINTS}/{cid}", headers=_auth(citizen))
    assert cd.json()["status"] == "RESOLVED"

    # citizen got a WORK_ORDER_COMPLETED notification
    notif = await client.get("/api/v1/notifications", headers=_auth(citizen))
    types = [n["notification_type"] for n in notif.json()["items"]]
    assert "WORK_ORDER_COMPLETED" in types


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

    # Simulate a network interruption: the client POSTs, loses the response,
    # then re-sends the SAME queued action with the SAME client_ref.
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
# State + ownership guardrails
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_complete_or_start_guards_on_terminal_states(client):
    await _cleanup()
    citizen = await _citizen_token(_unique_email("fw-order-citizen"))
    wtoken = await _seed_worker(email=_unique_email("fw-order"), name="Order Worker")
    wid = await _worker_id(wtoken)
    cid = await _complain(client, citizen)
    order_id = await _assign(client, citizen, cid, wid)

    # Completing directly from ASSIGNED is allowed (work resolved on arrival).
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/complete",
        json={"client_ref": "c-early-1"},
        headers=_auth(wtoken),
    )
    assert r.status_code == 200, r.text
    assert r.json()["work_order"]["status"] == "COMPLETED"

    # Starting after completion is rejected.
    r = await client.post(
        f"{_WORKER_API}/orders/{order_id}/start",
        json={"client_ref": "s-late-1"},
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
