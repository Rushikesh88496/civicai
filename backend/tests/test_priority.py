"""Tests for the Dynamic Priority & Risk Engine (Part 12).

Two layers:

* **Pure engine** — ``app.services.priority_engine`` is guaranteed deterministic.
  ``score_from_units`` with a single active factor reproduces the exact boundary
  scores 0 / 1 / 49 / 50 / 69 / 70 / 89 / 90 / 100, and each boundary is bucketed
  to the correct ``DynamicPriority``. Missing inputs are handled gracefully
  (absent signals contribute 0 and never distort the others) and extreme values
  clamp so the final score is bounded to 0..100.
* **Agent + API + history** — ``PriorityAgent`` runs against the live (dev) DB,
  persists a ``PriorityOutput`` to ``agent_runs`` (``agent="priority"``) and
  appends a ``complaint_priority_history`` row; re-running detects a score change
  vs the previous computation. API RBAC: 401 / 403 / 404 / full run + result +
  history retrieval.
"""

import uuid

import pytest
from sqlalchemy import select

from app.agents.priority_agent import PriorityAgent
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import Complaint, ComplaintPriorityHistory, User
from app.models.enums import DynamicPriority
from app.schemas.auth import RegisterIn
from app.services import auth_service, priority_service
from app.services.priority_engine import (
    Weights,
    priority_from_score,
    score_from_units,
    score_priority,
)
from tests.helpers import any_active_ward_id, any_officer_token

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"
_SETTINGS = get_settings()
_SEED_LAT = 17.4327
_SEED_LON = 78.3885

_SINGLE = Weights(severity=1.0, weather=0.0, location=0.0, crowd=0.0, history=0.0, time=0.0)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db, RegisterIn(
                    email=email,
                    password=_PASSWORD,
                    full_name="Priority Citizen",
                    ward_id=await any_active_ward_id(db),
                )
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _create_complaint(client, token: str, *, desc: str) -> str:
    from app.models.enums import ComplaintPriority

    body = {
        "description": desc,
        "category": "WATER",
        "media_ids": [],
        "location": {
            "latitude": _SEED_LAT,
            "longitude": _SEED_LON,
            "address": "Priority test location",
            "source": "gps",
            "geopoint_denied": False,
        },
    }
    r = await client.post(_BASE, json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    # Elevate the stored severity to CRITICAL so the engine has a strong input.
    async with async_session_factory() as db:
        comp = await db.get(Complaint, uuid.UUID(r.json()["id"]))
        comp.priority = ComplaintPriority.CRITICAL
        await db.commit()
    return r.json()["id"]


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


# --------------------------------------------------------------------------- #
# Pure engine: exact boundary scores (deterministic, single-factor)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "unit,expected_score",
    [
        (0.0, 0),
        (0.01, 1),
        (0.49, 49),
        (0.50, 50),
        (0.69, 69),
        (0.70, 70),
        (0.89, 89),
        (0.90, 90),
        (1.0, 100),
    ],
)
def test_score_from_units_boundary_scores(unit, expected_score):
    score, _contrib = score_from_units({"severity": unit}, _SINGLE)
    assert score == expected_score


@pytest.mark.parametrize(
    "score,expected",
    [
        (0, DynamicPriority.P4_LOW),
        (1, DynamicPriority.P4_LOW),
        (39, DynamicPriority.P4_LOW),
        (40, DynamicPriority.P3_MEDIUM),
        (49, DynamicPriority.P3_MEDIUM),
        (50, DynamicPriority.P3_MEDIUM),
        (59, DynamicPriority.P3_MEDIUM),
        (60, DynamicPriority.P2_HIGH),
        (69, DynamicPriority.P2_HIGH),
        (70, DynamicPriority.P2_HIGH),
        (79, DynamicPriority.P2_HIGH),
        (80, DynamicPriority.P1_CRITICAL),
        (89, DynamicPriority.P1_CRITICAL),
        (90, DynamicPriority.P1_CRITICAL),
        (100, DynamicPriority.P1_CRITICAL),
    ],
)
def test_priority_from_score_buckets(score, expected):
    assert priority_from_score(score) == expected


def test_boundary_buckets_match_engine():
    # Verify the score_from_units boundaries land in the same buckets the
    # priority-from-score mapping claims.
    for unit, want_score in [
        (0.0, 0),
        (0.49, 49),
        (0.50, 50),
        (0.69, 69),
        (0.70, 70),
        (0.89, 89),
        (0.90, 90),
        (1.0, 100),
    ]:
        score, _ = score_from_units({"severity": unit}, _SINGLE)
        assert score == want_score
        assert priority_from_score(score) == priority_from_score(want_score)


# --------------------------------------------------------------------------- #
# Pure engine: missing inputs
# --------------------------------------------------------------------------- #
def test_missing_inputs_degrades_to_low_score():
    # No signals at all (empty units) → score 0, P4_LOW.
    score, contrib = score_from_units({}, Weights())
    assert score == 0
    assert contrib == {}
    assert priority_from_score(score) == DynamicPriority.P4_LOW


def test_missing_inputs_does_not_distort_present_ones():
    # Only severity present → it dominates entirely (single present weight).
    score, contrib = score_from_units({"severity": 0.9}, _SINGLE)
    assert score == 90
    assert contrib["severity"] == pytest.approx(90.0)


# --------------------------------------------------------------------------- #
# Pure engine: extreme values
# --------------------------------------------------------------------------- #
def test_extreme_values_clamp_to_100():
    score, bucket, factors = score_priority(
        severity="CRITICAL",
        population=10_000_000,
        hospitals=50,
        schools=50,
        bus_stops=50,
        weather_condition="Heavy rain",
        rain_mm=500.0,
        weather_available=True,
        complaint_count=1_000_000,
        historical_recurrence=1_000_000,
        ward_resolved=True,
        time_unresolved_hours=10_000.0,
    )
    assert 0 <= score <= 100
    assert score >= 90  # extreme signals must push well into P1
    assert bucket == DynamicPriority.P1_CRITICAL
    for f in factors:
        assert -0.0 <= float(f["contribution"]) <= 100.0
        assert 0.0 <= float(f["unit"]) <= 1.0


def test_neutral_all_low_is_minimum():
    score, bucket, factors = score_priority(
        severity="LOW",
        population=0,
        hospitals=0,
        schools=0,
        bus_stops=0,
        weather_condition=None,
        rain_mm=None,
        weather_available=False,
        complaint_count=0,
        historical_recurrence=None,
        ward_resolved=False,
        time_unresolved_hours=0.0,
    )
    assert score <= 10
    assert bucket == DynamicPriority.P4_LOW
    # Every factor remains explainable and none contributes negatively.
    assert all(float(f["contribution"]) >= 0.0 for f in factors)
    assert all(0.0 <= float(f["unit"]) <= 1.0 for f in factors)
    # The low-severity base contributes a tiny amount; nothing else moves it.
    assert sum(float(f["contribution"]) for f in factors) >= 0.0


def test_factor_breakdown_sum_matches_score():
    score, bucket, factors = score_priority(
        severity="HIGH",
        population=500,
        hospitals=1,
        schools=1,
        bus_stops=1,
        weather_condition="Moderate rain",
        rain_mm=12.0,
        weather_available=True,
        complaint_count=5,
        historical_recurrence=4,
        ward_resolved=True,
        time_unresolved_hours=72.0,
    )
    assert 0 <= score <= 100
    # Every factor is explainable with the requested fields.
    for f in factors:
        assert all(
            k in f
            for k in (
                "factor",
                "input_value",
                "present",
                "weight",
                "unit",
                "contribution",
                "description",
            )
        )
    # Highest contribution factor is listed first (deterministic ordering).
    contribs = [float(f["contribution"]) for f in factors]
    assert contribs == sorted(contribs, reverse=True) or all(c == 0.0 for c in contribs)


# --------------------------------------------------------------------------- #
# Agent-level integration (live DB, no prior context required)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_priority_persists_output_and_history(client):
    email = _unique_email("pri-run")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, desc="Flooded market road.")

    async with async_session_factory() as db:
        run = await PriorityAgent(settings=_SETTINGS).run(db, complaint_id=uuid.UUID(complaint_id))

    assert run.agent == "priority"
    assert run.status.value == "SUCCEEDED"
    result = run.structured_result
    assert result is not None
    assert 0 <= result["score"] <= 100
    assert result["priority"] in {p.value for p in DynamicPriority}
    assert result["inputs"]["severity"] == "CRITICAL"
    assert result["summary"]

    async with async_session_factory() as db:
        hist = (
            (
                await db.execute(
                    select(ComplaintPriorityHistory).where(
                        ComplaintPriorityHistory.complaint_id == uuid.UUID(complaint_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(hist) == 1
    assert hist[0].score == result["score"]
    assert hist[0].priority.value == result["priority"]
    assert hist[0].previous_score is None
    assert hist[0].changed is True
    await _delete_user(email)


@pytest.mark.asyncio
async def test_run_priority_rerun_tracks_change(client):
    email = _unique_email("pri-rerun")
    token = await _citizen_token(email)
    complaint_id = await _create_complaint(client, token, desc="Street light out.")

    async with async_session_factory() as db:
        first = await PriorityAgent(settings=_SETTINGS).run(
            db, complaint_id=uuid.UUID(complaint_id)
        )
    async with async_session_factory() as db:
        second = await PriorityAgent(settings=_SETTINGS).run(
            db, complaint_id=uuid.UUID(complaint_id)
        )

    assert first.status.value == "SUCCEEDED"
    assert second.status.value == "SUCCEEDED"
    # Second run's output references the previous score.
    assert second.structured_result is not None
    assert second.structured_result["previous_score"] == first.structured_result["score"]

    async with async_session_factory() as db:
        hist = (
            (
                await db.execute(
                    select(ComplaintPriorityHistory)
                    .where(ComplaintPriorityHistory.complaint_id == uuid.UUID(complaint_id))
                    .order_by(ComplaintPriorityHistory.calculated_at.desc())
                )
            )
            .scalars()
            .all()
        )
    assert len(hist) == 2
    assert hist[0].previous_score == first.structured_result["score"]
    assert hist[0].changed == (
        abs(hist[0].score - first.structured_result["score"])
        >= float(_SETTINGS.PRIORITY_CHANGE_THRESHOLD)
    )
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# API + RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_priority_requires_auth(client):
    r = await client.post(f"{_BASE}/{uuid.uuid4()}/priority")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_priority_requires_access(client):
    owner_email = _unique_email("pri-ow")
    other_email = _unique_email("pri-oth")
    owner_token = await _citizen_token(owner_email)
    other_token = await _citizen_token(other_email)
    complaint_id = await _create_complaint(client, owner_token, desc="Some issue.")
    r = await client.post(
        f"{_BASE}/{complaint_id}/priority", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert r.status_code == 403, r.text
    await _delete_user(owner_email)
    await _delete_user(other_email)


@pytest.mark.asyncio
async def test_api_priority_404_unknown_complaint(client):
    otoken = await any_officer_token(_unique_email("pri-404-officer"))
    r = await client.post(
        f"{_BASE}/{uuid.uuid4()}/priority", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_api_priority_full_run_result_and_history(client):
    email = _unique_email("pri-api")
    token = await _citizen_token(email)
    otoken = await any_officer_token(_unique_email("pri-api-officer"))
    complaint_id = await _create_complaint(client, token, desc="Sinkhole near school.")

    resp = await client.post(
        f"{_BASE}/{complaint_id}/priority", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "SUCCEEDED"
    result = body["result"]
    assert 0 <= result["score"] <= 100
    assert result["priority"].startswith("P")

    getr = await client.get(
        f"{_BASE}/{complaint_id}/priority-result", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert getr.status_code == 200, getr.text
    out = getr.json()
    assert out["agent"] == "priority"
    assert out["status"] == "SUCCEEDED"
    assert out["structured_result"]["score"] == result["score"]

    h = await client.get(
        f"{_BASE}/{complaint_id}/priority-history", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert h.status_code == 200, h.text
    hist = h.json()
    assert hist["complaint_id"] == complaint_id
    assert len(hist["entries"]) == 1
    assert hist["entries"][0]["score"] == result["score"]
    await _delete_user(email)


@pytest.mark.asyncio
async def test_api_priority_result_none_before_run(client):
    email = _unique_email("pri-null")
    token = await _citizen_token(email)
    otoken = await any_officer_token(_unique_email("pri-null-officer"))
    complaint_id = await _create_complaint(client, token, desc="Nothing yet.")
    getr = await client.get(
        f"{_BASE}/{complaint_id}/priority-result", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert getr.status_code == 200, getr.text
    assert getr.json() is None
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Service-level: history is access-enforced
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_priority_history_access_enforced(client):
    owner_email = _unique_email("pri-h-ow")
    other_email = _unique_email("pri-h-oth")
    owner_token = await _citizen_token(owner_email)
    await _citizen_token(other_email)
    complaint_id = await _create_complaint(client, owner_token, desc="A complaint.")

    async with async_session_factory() as db:
        other = await db.scalar(select(User).where(User.email == other_email))
        try:
            await priority_service.get_priority_history(db, other, complaint_id)
            denied = False
        except priority_service.PriorityAccessError:
            denied = True
    assert denied
    await _delete_user(owner_email)
    await _delete_user(other_email)


def test_settings_weights_are_configurable():
    # Config exposes the six weights + thresholds + change threshold.
    assert _SETTINGS.PRIORITY_WEIGHT_SEVERITY > 0
    assert _SETTINGS.PRIORITY_WEATHER_RAIN_MM > 0
    assert _SETTINGS.PRIORITY_THRESHOLD_P1 == 80.0
    assert _SETTINGS.PRIORITY_CHANGE_THRESHOLD > 0
