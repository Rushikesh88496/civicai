"""Tests for the SLA Monitoring Agent + API (Part 20).

Covers, against the live dev database:

* **Agent unit (simulated time)** — a fixed injectable ``now`` drives the four
  states (``ON_TRACK / AT_RISK / BREACHED / COMPLETED``), the countdown /
  progress and the aggregate counts; the agent backfills a missing ``sla_hours``
  / ``due_at`` deadline from the resolved rule.
* **Escalation** — staff are notified only when an order *transitions* into
  AT_RISK / BREACHED; repeat runs with an unchanged state do not re-notify, and
  an AT_RISK -> BREACHED transition fires a fresh breach alert.
* **Rulebook** — the most specific ``sla_policies`` rule wins (a ROADS + P1 rule
  beats the P1 default), and the API rejects duplicates / bad shapes.
* **API** — live board, filters, run triggering, RBAC (401 unauthenticated /
  403 for citizens; OFFICER / ADMIN / WARD_REPRESENTATIVE allowed).

No LLM / Groq calls are made: the SLA agent is deterministic.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.agents.sla_agent import SlaAgent
from app.core.security import create_access_token, decode_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    AgentRun,
    Complaint,
    Notification,
    Role,
    SlaPolicy,
    User,
    UserProfile,
    WorkOrder,
)
from app.models.enums import (
    AgentStatus,
    ComplaintStatus,
    RoleName,
    WorkOrderStatus,
)
from app.schemas.sla import NOTIFICATION_SLA_AT_RISK, NOTIFICATION_SLA_BREACHED
from app.services import auth_service, sla_service

_PASSWORD = "TestPass#2026"
_SLA = "/api/v1/sla"
_LAT = 17.4327
_LON = 78.3885

# Fixed "now" shared by the simulated-time agent tests.
_T0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

_CREATED_EMAILS: list[str] = []


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _unique_email(prefix: str) -> str:
    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    _CREATED_EMAILS.append(email)
    return email


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            auth_service.RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="SLA Citizen",
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _staff_token(email: str, role: RoleName = RoleName.OFFICER) -> str:
    async with async_session_factory() as db:
        r = await db.scalar(select(Role).where(Role.name == role.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="SLA Officer",
            role_id=r.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
    return create_access_token(str(user.id), role.value)


async def _seed_order(
    citizen_token: str,
    *,
    department: str = "ROADS",
    category: str = "ROAD",
    priority: str = "P1_CRITICAL",
    status: WorkOrderStatus = WorkOrderStatus.ASSIGNED,
    approved_at: datetime,
    sla_hours: int | None = None,
    due_at: datetime | None = None,
) -> str:
    """A monitorable order with the P1 default (24h) unless another rule wins."""
    async with async_session_factory() as db:
        complaint = Complaint(
            description="Simulated SLA test issue.",
            title=f"SLA test {uuid.uuid4().hex[:8]}",
            category=category,
            status=ComplaintStatus.OPEN,
            user_id=uuid.UUID(decode_token(citizen_token, "access")["sub"]),
        )
        db.add(complaint)
        await db.flush()
        order = WorkOrder(
            complaint_id=complaint.id,
            incident="SLA test incident",
            department=department,
            priority=priority,
            location_lat=_LAT,
            location_lon=_LON,
            address="Test location",
            status=status,
            approved_at=approved_at,
            created_at=approved_at,
            sla_hours=sla_hours,
            due_at=due_at,
            created_by=None,
        )
        db.add(order)
        await db.commit()
        return str(order.id)


async def _run_agent_at(*, now: datetime) -> None:
    async with async_session_factory() as db:
        await SlaAgent(now=now).run(db)


async def _latest_orders() -> dict[str, dict]:
    """Latest persisted scan keyed by ``work_order_id`` (JSON round-tripped)."""
    async with async_session_factory() as db:
        run = await sla_service.latest_run(db)
    assert run is not None and run["structured_result"] is not None
    return {o["work_order_id"]: o for o in run["structured_result"]["orders"]}


async def _notifications_for(user_email: str) -> dict[str, int]:
    async with async_session_factory() as db:
        uid = await db.scalar(select(User.id).where(User.email == user_email))
        assert uid is not None
        rows = (
            (
                await db.execute(
                    select(Notification.notification_type).where(Notification.user_id == uid)
                )
            )
            .scalars()
            .all()
        )
    counts = {NOTIFICATION_SLA_AT_RISK: 0, NOTIFICATION_SLA_BREACHED: 0}
    for t in rows:
        if t in counts:
            counts[t] += 1
    return counts


async def _order_fields(order_id: str) -> tuple[int | None, datetime | None]:
    async with async_session_factory() as db:
        order = await db.scalar(select(WorkOrder).where(WorkOrder.id == uuid.UUID(order_id)))
        assert order is not None
        return order.sla_hours, order.due_at


async def _cleanup() -> None:
    async with async_session_factory() as db:
        await db.execute(delete(Notification))
        await db.execute(delete(AgentRun).where(AgentRun.agent == "sla_monitor"))
        await db.execute(delete(SlaPolicy).where(SlaPolicy.created_by.is_not(None)))
        if _CREATED_EMAILS:
            users = (
                (await db.execute(select(User).where(User.email.in_(_CREATED_EMAILS))))
                .scalars()
                .all()
            )
            uids = [u.id for u in users]
            if uids:
                await db.execute(delete(Complaint).where(Complaint.user_id.in_(uids)))
                for u in users:
                    await db.delete(u)
        await db.commit()
        _CREATED_EMAILS.clear()


@pytest.fixture(autouse=True)
async def _leave_db_clean():
    yield
    await _cleanup()


# --------------------------------------------------------------------------- #
# Agent unit: simulated-time states, counts, backfill
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_agent_simulated_states_counts_and_backfill(client):
    """The four states + counts derive from the injected clock, and missing
    deadlines are backfilled from the resolved P1(24h) rule."""
    citizen = await _citizen_token(_unique_email("sla-states-cit"))
    await _staff_token(_unique_email("sla-states-off"))

    on_track = await _seed_order(citizen, approved_at=_T0 - timedelta(hours=2))
    at_risk = await _seed_order(citizen, approved_at=_T0 - timedelta(hours=21))
    breached = await _seed_order(citizen, approved_at=_T0 - timedelta(hours=30))
    done = await _seed_order(
        citizen, status=WorkOrderStatus.COMPLETED, approved_at=_T0 - timedelta(hours=1)
    )

    await _run_agent_at(now=_T0)

    snap = await _latest_orders()
    assert snap[on_track]["state"] == "ON_TRACK"
    assert snap[at_risk]["state"] == "AT_RISK"
    assert snap[breached]["state"] == "BREACHED"
    assert snap[done]["state"] == "COMPLETED"

    # Counts: 3 open (1 on track / 1 at risk / 1 breached) + 1 completed.
    async with async_session_factory() as db:
        run = await sla_service.latest_run(db)
    counts = run["structured_result"]["counts"]
    assert counts["open"] == 3
    assert counts["on_track"] == 1
    assert counts["at_risk"] == 1
    assert counts["breached"] == 1
    assert counts["completed"] == 1
    assert counts["no_deadline"] == 0

    # Progress + countdown are meaningful around the window edges.
    assert abs(snap[at_risk]["progress"] - 0.875) < 1e-3
    assert snap[at_risk]["remaining_human"] == "3h"

    # Backfill: the agent persisted sla_hours + due_at from the P1(24h) rule.
    hours, due_at = await _order_fields(at_risk)
    assert hours == 24
    assert due_at is not None and due_at == _T0 + timedelta(hours=3)


# --------------------------------------------------------------------------- #
# Escalation: transitions notify once, repeats do not
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_agent_notifies_on_transition_not_repeats(client):
    """First run notifies AT_RISK + BREACHED; an AT_RISK -> BREACHED transition
    notifies once more; a same-state rerun stays silent."""
    citizen = await _citizen_token(_unique_email("sla-notify-cit"))
    officer_email = _unique_email("sla-notify-off")
    await _staff_token(officer_email)

    await _seed_order(citizen, approved_at=_T0 - timedelta(hours=21))  # AT_RISK
    await _seed_order(citizen, approved_at=_T0 - timedelta(hours=30))  # BREACHED
    await _seed_order(citizen, approved_at=_T0 - timedelta(hours=2))  # ON_TRACK

    await _run_agent_at(now=_T0)
    assert await _notifications_for(officer_email) == {
        NOTIFICATION_SLA_AT_RISK: 1,
        NOTIFICATION_SLA_BREACHED: 1,
    }

    # +4h: the at-risk order (21h/24h) crosses into breach -> 1 new notification.
    await _run_agent_at(now=_T0 + timedelta(hours=4))
    assert await _notifications_for(officer_email) == {
        NOTIFICATION_SLA_AT_RISK: 1,
        NOTIFICATION_SLA_BREACHED: 2,
    }

    # +6h: same states as the previous run -> nothing new fires.
    await _run_agent_at(now=_T0 + timedelta(hours=6))
    assert await _notifications_for(officer_email) == {
        NOTIFICATION_SLA_AT_RISK: 1,
        NOTIFICATION_SLA_BREACHED: 2,
    }


# --------------------------------------------------------------------------- #
# Rulebook: most-specific rule wins + API validation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_policy_resolution_most_specific(client):
    """A ROADS + P1 override (12h) beats the P1 default (24h) for ROADS orders,
    while WASTE keeps the P1 default."""
    citizen = await _citizen_token(_unique_email("sla-spec-cit"))
    officer = await _staff_token(_unique_email("sla-spec-off"))

    created = await client.post(
        f"{_SLA}/policies",
        json={
            "name": "Roads P1 override",
            "priority": "P1_CRITICAL",
            "department": "ROADS",
            "sla_hours": 12,
        },
        headers=_auth(officer),
    )
    assert created.status_code == 201

    roads = await _seed_order(
        citizen, department="ROADS", priority="P1_CRITICAL", approved_at=_T0 - timedelta(hours=6)
    )
    waste = await _seed_order(
        citizen, department="WASTE", priority="P1_CRITICAL", approved_at=_T0 - timedelta(hours=6)
    )

    await _run_agent_at(now=_T0)
    snap = await _latest_orders()

    assert snap[roads]["sla_hours"] == 12
    assert snap[roads]["state"] == "ON_TRACK"  # 50% of 12h
    assert snap[waste]["sla_hours"] == 24  # unchanged P1 default
    assert snap[waste]["state"] == "ON_TRACK"  # 25% of 24h


@pytest.mark.asyncio
async def test_policy_api_rejects_duplicates_and_bad_shapes(client):
    officer = await _staff_token(_unique_email("sla-policy-off"))
    citizen = await _citizen_token(_unique_email("sla-policy-cit"))
    path = f"{_SLA}/policies"

    # Seeded defaults are listed for staff but hidden below RBAC for citizens.
    assert (await client.get(path, headers=_auth(citizen))).status_code == 403
    listed = await client.get(path, headers=_auth(officer))
    assert listed.status_code == 200
    assert len(listed.json()) >= 4  # P1..P4 defaults exist

    payload = {
        "name": "P1 DRAINAGE flood",
        "priority": "P1_CRITICAL",
        "department": "DRAINAGE",
        "category": "FLOODING",
        "sla_hours": 8,
        "at_risk_percent": 0.6,
    }
    created = await client.post(path, json=payload, headers=_auth(officer))
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["sla_hours"] == 8

    duplicate = await client.post(path, json=payload, headers=_auth(officer))
    assert duplicate.status_code == 409

    bad_hours = {**payload, "sla_hours": 0}
    assert (await client.post(path, json=bad_hours, headers=_auth(officer))).status_code == 422

    no_dimension = {"sla_hours": 10, "at_risk_percent": 0.5}
    assert (await client.post(path, json=no_dimension, headers=_auth(officer))).status_code == 422

    # PUT replaces the rule (full replace semantics).
    updated = {**payload, "priority": "P2_HIGH", "at_risk_percent": 0.5}
    replaced = await client.put(f"{path}/{pid}", json=updated, headers=_auth(officer))
    assert replaced.status_code == 200
    assert replaced.json()["priority"] == "P2_HIGH"
    assert replaced.json()["at_risk_percent"] == 0.5

    assert (await client.delete(f"{path}/{pid}", headers=_auth(officer))).status_code == 204
    assert (await client.delete(f"{path}/{pid}", headers=_auth(officer))).status_code == 404


# --------------------------------------------------------------------------- #
# API: live board, filters, run trigger, RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_board_rbac_and_filters(client):
    citizen = await _citizen_token(_unique_email("sla-api-cit"))
    officer = await _staff_token(_unique_email("sla-api-off"))

    now = datetime.now(UTC)
    healthy = await _seed_order(citizen, approved_at=now - timedelta(hours=2))
    await _seed_order(citizen, approved_at=now - timedelta(hours=21))

    assert (await client.get(f"{_SLA}/orders")).status_code == 401
    assert (await client.get(f"{_SLA}/orders", headers=_auth(citizen))).status_code == 403

    board = await client.get(f"{_SLA}/orders", headers=_auth(officer))
    assert board.status_code == 200
    body = board.json()
    assert body["total"] == 2
    assert body["counts"]["on_track"] == 1
    assert body["counts"]["at_risk"] == 1
    states = {item["state"] for item in body["items"]}
    assert states == {"ON_TRACK", "AT_RISK"}

    risky = await client.get(f"{_SLA}/orders?state=AT_RISK", headers=_auth(officer))
    assert risky.json()["total"] == 1

    searched = await client.get(f"{_SLA}/orders?search={healthy}", headers=_auth(officer))
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["work_order_id"] == healthy

    assert (await client.post(f"{_SLA}/run", headers=_auth(citizen))).status_code == 403
    run = await client.post(f"{_SLA}/run", headers=_auth(officer))
    assert run.status_code == 200
    assert run.json()["status"] == AgentStatus.SUCCEEDED.value
    assert run.json()["result"]["counts"]["open"] == 2

    latest = await client.get(f"{_SLA}/run", headers=_auth(officer))
    assert latest.status_code == 200
    assert latest.json()["agent"] == "sla_monitor"
    assert latest.json()["status"] == AgentStatus.SUCCEEDED.value
