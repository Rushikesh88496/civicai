"""Tests for the Civic Analytics dashboard (Part 22).

Layers exercised:

* **RBAC** — officers / admins / ward-reps may read the analytics endpoints while
  citizens and field workers are forbidden; a ward-representative is scoped to
  their own ward.
* **Overview KPIs** — totals, resolution / escalation / AI-triage rates,
  response & resolution times, SLA compliance from work-order deadlines, and
  citizen satisfaction (avg + distribution).
* **Charts** — complaints over time, category / ward / department / SLA
  breakdowns.
* **Filters** — date, ward, department, category and priority narrow every
  endpoint consistently.
* **Heatmap** — pre-aggregated clusters with lat/lon, count and priority weight.
* **CSV export** — attachment headers and per-complaint row content.
* **Rating endpoint** — owner-only 1-5 star submission on resolved complaints,
  with 403/404/409 handling and validation.
"""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from sqlalchemy import delete, select
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    AgentRun,
    Complaint,
    ComplaintDepartmentHistory,
    ComplaintLocation,
    ComplaintPriorityHistory,
    ComplaintRating,
    ComplaintStatusHistory,
    Role,
    User,
    UserProfile,
    Ward,
    WorkOrder,
)
from app.models.enums import (
    ComplaintCategory,
    ComplaintStatus,
    DynamicPriority,
    RoleName,
    WorkOrderStatus,
)
from app.schemas.auth import RegisterIn
from app.services import auth_service
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/analytics"
_SETTINGS = get_settings()
_LAT = 18.4634
_LON = 73.8912
_PRIORITIES = [
    DynamicPriority.P1_CRITICAL,
    DynamicPriority.P2_HIGH,
    DynamicPriority.P3_MEDIUM,
    DynamicPriority.P4_LOW,
]


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen(email: str) -> uuid.UUID:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="AN Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
        return user.id


async def _role_user(email: str, role_name: str, *, ward_id=None) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == role_name))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=f"{role_name} User",
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


async def _ward(code: str, name: str | None = None) -> uuid.UUID:
    token = uuid.uuid4().hex[:6]
    wname = name or code
    async with async_session_factory() as db:
        ward = Ward(code=f"{code}-{token}", name=f"{wname}-{token}", description="wa")
        db.add(ward)
        await db.commit()
        return ward.id


async def _insert_complaint(
    *,
    user_id: uuid.UUID,
    title: str,
    ward_id: uuid.UUID | None = None,
    category: str = "GARBAGE",
    status: ComplaintStatus = ComplaintStatus.SUBMITTED,
    created_at: datetime | None = None,
    with_location: bool = True,
) -> uuid.UUID:
    async with async_session_factory() as db:
        complaint = Complaint(
            user_id=user_id,
            ward_id=ward_id,
            category=ComplaintCategory(category),
            title=title,
            description=f"desc {title}",
            status=status,
        )
        db.add(complaint)
        await db.flush()
        if created_at is not None:
            complaint.created_at = created_at
        if with_location:
            db.add(
                ComplaintLocation(
                    complaint_id=complaint.id,
                    latitude=_LAT,
                    longitude=_LON,
                    source="gps",
                )
            )
        await db.commit()
        return complaint.id


async def _history(complaint_id: uuid.UUID, status: str, at: datetime | None = None):
    async with async_session_factory() as db:
        row = ComplaintStatusHistory(
            complaint_id=complaint_id,
            status=ComplaintStatus(status),
            note="test",
        )
        db.add(row)
        if at is not None:
            row.recorded_at = at
        await db.commit()


async def _priority(complaint_id: uuid.UUID, bucket: DynamicPriority, score: int = 50):
    async with async_session_factory() as db:
        db.add(
            ComplaintPriorityHistory(
                complaint_id=complaint_id,
                priority=bucket,
                score=score,
                inputs={},
                factors={},
            )
        )
        await db.commit()


async def _department(complaint_id: uuid.UUID, dept: str, confidence: float = 0.9):
    async with async_session_factory() as db:
        db.add(
            ComplaintDepartmentHistory(
                complaint_id=complaint_id,
                primary_department=dept,
                routing_reason=f"test {dept}",
                confidence=confidence,
                inputs={},
            )
        )
        await db.commit()


async def _agent_run(complaint_id: uuid.UUID, agent: str, status: str = "SUCCEEDED"):
    async with async_session_factory() as db:
        db.add(AgentRun(complaint_id=complaint_id, agent=agent, status=status))
        await db.commit()


async def _work_order(
    complaint_id: uuid.UUID,
    *,
    department: str = "ROADS",
    priority: str = "P2_HIGH",
    status: WorkOrderStatus = WorkOrderStatus.COMPLETED,
    completed_at: datetime | None = None,
    due_at: datetime | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    async with async_session_factory() as db:
        wo = WorkOrder(
            complaint_id=complaint_id,
            department=department,
            priority=priority,
            status=status,
            incident="test order",
            completed_at=completed_at,
            due_at=due_at,
            created_at=created_at or datetime.now(UTC),
        )
        db.add(wo)
        await db.commit()
        return wo.id


async def _rating(
    complaint_id: uuid.UUID,
    user_id: uuid.UUID,
    rating: int,
    comment: str | None = None,
):
    async with async_session_factory() as db:
        db.add(
            ComplaintRating(
                complaint_id=complaint_id,
                user_id=user_id,
                rating=rating,
                comment=comment,
            )
        )
        await db.commit()


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _delete_complaint(complaint_id) -> None:
    async with async_session_factory() as db:
        await db.execute(delete(Complaint).where(Complaint.id == complaint_id))
        await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    async with async_session_factory() as db:
        await db.execute(delete(ComplaintRating))
        await db.execute(delete(Complaint))
        await db.execute(delete(User).where(User.email.like("%-%@example.com")))
        await db.execute(delete(Ward).where(Ward.description == "wa"))
        await db.commit()


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_analytics_forbids_citizen_and_field_worker(client: TestClient):
    citizen_id = await _citizen(_unique_email("an-cit"))
    citizen_token = create_access_token(str(citizen_id), "CITIZEN")
    worker_token = await _role_user(_unique_email("an-worker"), RoleName.FIELD_WORKER.value)

    for token in (citizen_token, worker_token):
        r = await client.get(f"{_BASE}/overview", headers=_auth(token))
        assert r.status_code == 403, token
        r = await client.get(f"{_BASE}/heatmap", headers=_auth(token))
        assert r.status_code == 403
        r = await client.get(f"{_BASE}/export", headers=_auth(token))
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_analytics_requires_auth(client: TestClient):
    r = await client.get(f"{_BASE}/overview")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_ward_rep_is_scoped_to_own_ward(client: TestClient):
    ward_a = await _ward("woptA")
    ward_b = await _ward("woptB")
    citizen_id = await _citizen(_unique_email("an-opt-scope"))
    await _insert_complaint(
        user_id=citizen_id, title="scope-a", ward_id=ward_a, status=ComplaintStatus.OPEN
    )
    await _insert_complaint(
        user_id=citizen_id, title="scope-b", ward_id=ward_b, status=ComplaintStatus.OPEN
    )

    officer_token = await _role_user(_unique_email("an-officer-scope"), RoleName.OFFICER.value)
    rep_token = await _role_user(
        _unique_email("an-rep-scope"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward_a
    )
    scoped = f"{_BASE}/overview?ward_id={ward_a}"
    for token, expected in ((officer_token, 2), (rep_token, 1)):
        r = await client.get(f"{_BASE}/overview", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["kpis"]["total_complaints"] == expected
        # Filtering by ward_a narrows both roles to that ward's complaints.
        r2 = await client.get(scoped, headers=_auth(token))
        assert r2.json()["kpis"]["total_complaints"] == 1


# --------------------------------------------------------------------------- #
# Empty state
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_overview_empty(client: TestClient):
    token = await _role_user(_unique_email("an-officer-empty"), RoleName.OFFICER.value)
    r = await client.get(f"{_BASE}/overview", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    kpis = data["kpis"]
    assert kpis["total_complaints"] == 0
    assert kpis["resolution_rate"] == 0.0
    assert kpis["ai_triage_rate"] == 0.0
    assert kpis["escalation_rate"] == 0.0
    assert kpis["satisfaction_avg"] is None
    assert data["charts"]["categories"] == []
    assert data["charts"]["complaints_over_time"] == []
    assert sum(w["total"] for w in data["charts"]["wards"]) == 0

    r = await client.get(f"{_BASE}/heatmap", headers=_auth(token))
    assert r.json()["total_points"] == 0
    assert r.json()["clusters"] == []


# --------------------------------------------------------------------------- #
# KPI math + charts
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_overview_kpis_and_charts(client: TestClient):
    citizen_id = await _citizen(_unique_email("an-kpi"))
    c_resolved = await _insert_complaint(
        user_id=citizen_id,
        title="kpi-resolved",
        ward_id=await _ward("wkpi1"),
        category="ROAD",
        status=ComplaintStatus.CITIZEN_VERIFIED,
    )
    c_resolved2 = await _insert_complaint(
        user_id=citizen_id,
        title="kpi-resolved2",
        ward_id=await _ward("wkpi2"),
        category="WATER",
        status=ComplaintStatus.RESOLVED,
    )
    c_open = await _insert_complaint(
        user_id=citizen_id,
        title="kpi-open",
        ward_id=None,
        category="PARKS",
        status=ComplaintStatus.OPEN,
    )

    for cid, bucket in (
        (c_resolved, DynamicPriority.P1_CRITICAL),
        (c_resolved2, DynamicPriority.P2_HIGH),
    ):
        await _priority(cid, bucket)
    await _department(c_resolved, "ROADS")
    await _agent_run(c_resolved, "triage", "SUCCEEDED")
    await _agent_run(c_open, "triage", "FAILED")
    await _history(c_resolved, "ESCALATED")
    await _history(c_resolved, "RESOLVED")
    await _history(c_resolved2, "RESOLVED")

    now = datetime.now(UTC)
    await _work_order(
        c_resolved,
        department="ROADS",
        priority="P1_CRITICAL",
        completed_at=now - timedelta(days=2),
        due_at=now - timedelta(days=1),
    )
    await _work_order(
        c_open,
        department="ROADS",
        priority="P3_MEDIUM",
        status=WorkOrderStatus.IN_PROGRESS,
        completed_at=None,
        due_at=now - timedelta(hours=1),
    )
    await _rating(c_resolved, citizen_id, 5, "great")
    await _rating(c_resolved2, citizen_id, 3)

    token = await _role_user(_unique_email("an-officer-kpi"), RoleName.OFFICER.value)
    r = await client.get(f"{_BASE}/overview", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    kpis = data["kpis"]

    assert kpis["total_complaints"] == 3
    # c_resolved + c_resolved2 resolved (history + current status), c_open not.
    assert kpis["resolved"] == 2
    assert round(kpis["resolution_rate"], 2) == round(2 / 3, 2)
    # escalation only on c_resolved.
    assert kpis["escalated"] == 1
    assert round(kpis["escalation_rate"], 2) == round(1 / 3, 2)
    # AI triage succeeded only on c_resolved.
    assert kpis["ai_triaged"] == 1
    assert round(kpis["ai_triage_rate"], 2) == round(1 / 3, 2)
    assert kpis["response_count"] == 2
    assert kpis["resolution_count"] == 2
    # SLA: 1 within (resolved order), 1 overdue (open past-due order) -> 50%.
    assert kpis["sla_within"] == 1
    assert kpis["sla_overdue"] == 1
    assert round(kpis["sla_compliance_rate"], 2) == 0.5
    # Satisfaction: avg (5+3)/2 = 4.0.
    assert kpis["satisfaction_avg"] == 4.0
    assert kpis["satisfaction_count"] == 2
    dist = {b["rating"]: b["count"] for b in kpis["satisfaction_distribution"]}
    assert dist == {1: 0, 2: 0, 3: 1, 4: 0, 5: 1}

    charts = data["charts"]
    cats = {c["category"]: c for c in charts["categories"]}
    assert cats["ROAD"]["total"] == 1 and cats["ROAD"]["resolved"] == 1
    assert cats["WATER"]["total"] == 1 and cats["WATER"]["resolved"] == 1
    assert cats["PARKS"]["total"] == 1 and cats["PARKS"]["resolved"] == 0

    wards = {w["ward_name"]: w for w in charts["wards"]}
    assert sum(w["total"] for w in charts["wards"]) == 3
    assert wards["Unassigned"]["total"] == 1
    assert sum(1 for w in charts["wards"] if w["total"]) == 3

    depts = {d["department"]: d for d in charts["departments"]}
    assert depts["ROADS"]["total"] == 2
    assert depts["ROADS"]["completed"] == 1
    assert depts["ROADS"]["escalated"] >= 0

    # SLA performance by bucket.
    sla = {s["priority"]: s for s in charts["sla_performance"]}
    assert sla["P1_CRITICAL"]["within"] == 1
    assert sla["P3_MEDIUM"]["overdue"] == 1

    series = charts["complaints_over_time"]
    assert len(series) >= 1
    assert sum(p["total"] for p in series) == 3
    assert sum(p["resolved"] for p in series) == 2


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_filters_narrow_results(client: TestClient):
    citizen_id = await _citizen(_unique_email("an-filt"))
    ward_x = await _ward("wfilX")
    ward_y = await _ward("wfilY")

    now = datetime.now(UTC)
    old = now - timedelta(days=30)
    c_road_x = await _insert_complaint(
        user_id=citizen_id,
        title="f-road-x",
        ward_id=ward_x,
        category="ROAD",
        status=ComplaintStatus.OPEN,
        created_at=now,
    )
    c_water_x = await _insert_complaint(
        user_id=citizen_id,
        title="f-water-x",
        ward_id=ward_x,
        category="WATER",
        status=ComplaintStatus.OPEN,
        created_at=old,
    )
    c_road_y = await _insert_complaint(
        user_id=citizen_id,
        title="f-road-y",
        ward_id=ward_y,
        category="ROAD",
        status=ComplaintStatus.OPEN,
        created_at=now,
    )

    await _priority(c_road_x, DynamicPriority.P1_CRITICAL)
    await _priority(c_water_x, DynamicPriority.P1_CRITICAL)
    await _priority(c_road_y, DynamicPriority.P3_MEDIUM)
    await _department(c_road_x, "ROADS")
    await _department(c_water_x, "WATER")
    await _department(c_road_y, "ROADS")

    token = await _role_user(_unique_email("an-officer-filt"), RoleName.OFFICER.value)
    headers = _auth(token)

    async def total(query: str = "") -> int:
        r = await client.get(f"{_BASE}/overview{query}", headers=headers)
        assert r.status_code == 200
        return r.json()["kpis"]["total_complaints"]

    assert await total() == 3
    assert await total("?category=ROAD") == 2
    assert await total("?category=WATER") == 1
    assert await total(f"?ward_id={ward_x}") == 2
    assert await total("?priority=P1_CRITICAL") == 2
    assert await total("?priority=P3_MEDIUM") == 1
    assert await total("?department=ROADS") == 2
    assert await total("?department=WATER") == 1

    date_from = quote((now - timedelta(days=2)).isoformat())
    assert await total(f"?date_from={date_from}") == 2
    date_to = quote((now - timedelta(days=29)).isoformat())
    assert await total(f"?date_to={date_to}") == 1

    # Combined filters.
    query = f"?category=ROAD&ward_id={ward_x}&priority=P1_CRITICAL&department=ROADS"
    assert await total(query) == 1


# --------------------------------------------------------------------------- #
# Heatmap
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_heatmap_aggregates_clusters(client: TestClient):
    citizen_id = await _citizen(_unique_email("an-heat"))
    ward_a = await _ward("wheatA")
    ids = [
        await _insert_complaint(
            user_id=citizen_id, title=f"heat-{i}", ward_id=ward_a, category="ROAD"
        )
        for i in range(5)
    ]
    for cid in ids:
        await _priority(cid, DynamicPriority.P1_CRITICAL)

    token = await _role_user(_unique_email("an-officer-heat"), RoleName.OFFICER.value)
    r = await client.get(f"{_BASE}/heatmap", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["total_points"] == 5
    assert data["clusters"], "expected at least one cluster"
    cluster = data["clusters"][0]
    assert abs(cluster["latitude"] - _LAT) <= 0.005
    assert abs(cluster["longitude"] - _LON) <= 0.005
    assert cluster["count"] == 5
    assert cluster["weight"] >= 5.0


# --------------------------------------------------------------------------- #
# CSV export
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_export_csv(client: TestClient):
    citizen_id = await _citizen(_unique_email("an-csv"))
    ward_a = await _ward("wcsvA")
    cid = await _insert_complaint(
        user_id=citizen_id,
        title="csv-complaint",
        ward_id=ward_a,
        category="ROAD",
        status=ComplaintStatus.RESOLVED,
    )
    await _priority(cid, DynamicPriority.P2_HIGH)
    await _department(cid, "ROADS")
    await _rating(cid, citizen_id, 4)

    token = await _role_user(_unique_email("an-officer-csv"), RoleName.OFFICER.value)
    r = await client.get(f"{_BASE}/export", headers=_auth(token))
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    lines = body.strip().splitlines()
    assert lines[0].startswith("complaint_id,created_at")
    assert len(lines) == 2
    assert ",ROAD," in lines[1]
    assert "ROADS" in lines[1]
    assert ",4" in lines[1]


# --------------------------------------------------------------------------- #
# Rating endpoint
# --------------------------------------------------------------------------- #
async def _resolved_owned_complaint(client, *, owner_id: uuid.UUID) -> uuid.UUID:
    return await _insert_complaint(
        user_id=owner_id,
        title="rate-me",
        category="PARKS",
        status=ComplaintStatus.RESOLVED,
        with_location=False,
    )


@pytest.mark.asyncio
async def test_rating_rbac_and_validation(client: TestClient):
    citizen_id = await _citizen(_unique_email("an-rate-owner"))
    complaint_id = await _resolved_owned_complaint(client, owner_id=citizen_id)

    other_id = await _citizen(_unique_email("an-rate-other"))
    worker_token = await _role_user(_unique_email("an-rate-worker"), RoleName.FIELD_WORKER.value)

    owner_token = create_access_token(str(citizen_id), "CITIZEN")
    other_token = create_access_token(str(other_id), "CITIZEN")

    url = f"/api/v1/complaints/{complaint_id}/rating"

    # Field workers are not allowed to rate.
    r = await client.post(url, json={"rating": 5}, headers=_auth(worker_token))
    assert r.status_code == 403

    # Non-owner cannot rate.
    r = await client.post(url, json={"rating": 5}, headers=_auth(other_token))
    assert r.status_code == 403

    # Validation: out-of-range rating.
    r = await client.post(url, json={"rating": 6}, headers=_auth(owner_token))
    assert r.status_code == 422
    r = await client.post(url, json={"rating": 0}, headers=_auth(owner_token))
    assert r.status_code == 422

    # Success.
    r = await client.post(
        url, json={"rating": 5, "comment": "fixed fast"}, headers=_auth(owner_token)
    )
    assert r.status_code == 201
    data = r.json()
    assert data["rating"] == 5
    assert data["comment"] == "fixed fast"
    assert data["complaint_id"] == str(complaint_id)

    # Duplicate rating → 409.
    r = await client.post(url, json={"rating": 4}, headers=_auth(owner_token))
    assert r.status_code == 409

    # Missing complaint → 404.
    r = await client.post(
        f"/api/v1/complaints/{uuid.uuid4()}/rating", json={"rating": 4}, headers=_auth(owner_token)
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_rating_requires_resolved_complaint(client: TestClient):
    citizen_id = await _citizen(_unique_email("an-rate-open"))
    complaint_id = await _insert_complaint(
        user_id=citizen_id,
        title="rate-open",
        category="WATER",
        status=ComplaintStatus.SUBMITTED,
        with_location=False,
    )
    token = create_access_token(str(citizen_id), "CITIZEN")
    r = await client.post(
        f"/api/v1/complaints/{complaint_id}/rating", json={"rating": 4}, headers=_auth(token)
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_rating_after_resolution_history_counts(client: TestClient):
    citizen_id = await _citizen(_unique_email("an-rate-hist"))
    complaint_id = await _insert_complaint(
        user_id=citizen_id,
        title="rate-hist",
        category="WATER",
        status=ComplaintStatus.WORKER_ASSIGNED,
        with_location=False,
    )
    await _history(complaint_id, "RESOLVED")
    token = create_access_token(str(citizen_id), "CITIZEN")
    r = await client.post(
        f"/api/v1/complaints/{complaint_id}/rating", json={"rating": 2}, headers=_auth(token)
    )
    assert r.status_code == 201
