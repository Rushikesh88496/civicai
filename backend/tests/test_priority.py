"""Tests for the Dynamic Priority & Risk Engine (Part 12, rebuilt v2).

Two layers:

* **Pure engine** — ``app.services.priority_engine`` is guaranteed deterministic.
  ``score_from_units`` with a single active factor reproduces the exact boundary
  scores (0/1/49/50/69/70/89/90/100), every boundary buckets to the correct
  ``DynamicPriority``, and the rich ``score_priority()`` API is exercised with
  the real component dataclasses: extreme values clamp, missing data is reported
  honestly (``score=None`` + status) and never inflates the present components,
  risk amplifiers fire ONLY on real evidence, forecast precipitation looks
  ahead, distance decay bands are honoured per facility, the SLA clock never
  affects the engine score, and calibration against the legacy seed scenario
  scores above the old 31/100 (the OLD model's result).
* **Agent + API + history** — ``PriorityAgent`` runs against the live (dev) DB,
  persists a ``PriorityOutput`` (with risk amplifiers + SLA snapshot) to
  ``agent_runs`` (``agent="priority"``) and appends a ``complaint_priority_history``
  row; re-running detects a score change vs the previous computation. API RBAC:
  401 / 403 / 404 / full run + result + history retrieval.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.agents.priority_agent import PriorityAgent
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import Complaint, ComplaintPriorityHistory, SlaPolicy, User
from app.models.enums import DynamicPriority, PriorityReadiness
from app.schemas.auth import RegisterIn
from app.services import auth_service, priority_service
from app.services.priority_engine import (
    EvidenceInput,
    FacilityInput,
    HistoricalInput,
    InfrastructureInput,
    PopulationInput,
    SeverityInput,
    WeatherInput,
    Weights,
    ai_evidence_confidence,
    distance_band_factor,
    priority_from_score,
    score_from_units,
    score_priority,
)
from app.services.sla_service import complaint_sla_status
from tests.helpers import any_active_ward_id, any_officer_token

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"
_SETTINGS = get_settings()
_SEED_LAT = 18.4634
_SEED_LON = 73.8912

# Single-factor engine configuration: severity alone maps a 0..1 unit 1:1 to the
# 0..100 score (contribution = unit * max_points with max_points = 100).
_SINGLE = Weights(
    severity=100.0,
    infrastructure=0.0,
    population=0.0,
    history=0.0,
    weather=0.0,
    evidence=0.0,
)

# The OLD model scored the seeded/near-school flooding scenario 31/100 (P4_LOW).
# The rebuilt engine must score the same real scenario higher (recalibration).
_LEGACY_SEED_SCORE = 31
_SEED_COMPLAINT_ID = "b682e349-2a6e-4ecb-9d5f-fe53673aae67"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_token(email: str) -> str:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Priority Citizen",
                ward_id=await any_active_ward_id(db),
            ),
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


def _sum_scores(components: list[dict], score: int, amplifiers: list[dict]) -> int:
    """Engine contract: components sum to the base; only real amplifiers add."""
    base = sum(int(c["score"] or 0) for c in components)
    amp = sum(int(a["points"]) for a in amplifiers)
    return base + amp if base + amp < 100 else 100


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
# Pure engine: extreme values (rich dataclass API)
# --------------------------------------------------------------------------- #
def _extreme_bundle():
    return dict(
        category="FLOODING",
        severity=SeverityInput(severity="CRITICAL"),
        infrastructure=InfrastructureInput(
            facilities=[
                FacilityInput(
                    name=f"Hospital-{i}", category="HOSPITAL", distance_m=50.0
                )
                for i in range(6)
            ],
            status="FOUND",
            radius_m=1000.0,
        ),
        weather=WeatherInput(
            condition="Heavy rain", rain_mm=500.0, threshold_mm=5.0, status="AVAILABLE"
        ),
        historical=HistoricalInput(
            same_category_nearby_30d=50,
            same_category_nearby_7d=100,
            nearby_30d=60,
            nearby_7d=20,
            cluster_250m_30d=10,
            ward_30d=100,
            unresolved_similar_nearby=10,
            status="AVAILABLE",
        ),
        population=PopulationInput(
            reports_7d={250: 50, 500: 200, 1000: 2000},
            reports_30d={500: 300, 1000: 4000},
            unique_reporters_7d=100,
            unique_reporters_30d=200,
            unresolved_reports_7d=50,
            unresolved_reports_30d=60,
            spread_max_distance_m=9000.0,
            sensitive_facilities_nearby=6,
            population=None,
            population_status="DATA_UNAVAILABLE",
            status="AVAILABLE",
        ),
        evidence=EvidenceInput(
            has_gps=True,
            gps_accuracy_m=5.0,
            description_chars=400,
            media_count=10,
            category_structured=True,
            triage_available=True,
            triage_confidence=1.0,
            vision_available=True,
            vision_confidence=1.0,
            vision_mismatch=False,
            corroborating_reports_30d=60,
            status="AVAILABLE",
        ),
    )


def test_extreme_values_clamp_to_100():
    score, bucket, components, readiness, amplifiers = score_priority(
        **_extreme_bundle()
    )
    assert 0 <= score <= 100
    assert score == 100  # clamped despite amplifier bonus exceeding 100
    assert bucket == DynamicPriority.P1_CRITICAL
    assert readiness == PriorityReadiness.READY
    assert amplifiers  # real evidence fired the deterministic amplifiers
    for c in components:
        assert c["score"] is None or 0 <= float(c["score"]) <= float(c["max_score"])
        assert 0.0 <= float(c["unit"]) <= 1.0


def test_neutral_all_low_is_minimum():
    score, bucket, components, _readiness, amplifiers = score_priority(
        category="WATER",
        severity=SeverityInput(severity="LOW"),
        infrastructure=InfrastructureInput(status="NO_VERIFIED_RECORDS"),
        weather=WeatherInput(status="DATA_UNAVAILABLE"),
        historical=HistoricalInput(status="AVAILABLE"),
        population=PopulationInput(status="AVAILABLE"),
        evidence=EvidenceInput(status="AVAILABLE"),
    )
    assert score <= 10
    assert bucket == DynamicPriority.P4_LOW
    assert not amplifiers  # no real evidence to fire any
    # Every component remains explainable and none contributes negatively.
    assert all(c["score"] is None or float(c["score"]) >= 0 for c in components)
    assert all(0.0 <= float(c["unit"]) <= 1.0 for c in components)
    # Data-unavailable weather reports honestly, never as a fabricated 0-score.
    weather_comp = next(c for c in components if c["key"] == "weather")
    assert weather_comp["score"] is None
    assert weather_comp["status"] == "DATA_UNAVAILABLE"


def test_factor_breakdown_sum_matches_score():
    score, bucket, components, _readiness, amplifiers = score_priority(
        category="WATER",
        severity=SeverityInput(severity="HIGH"),
        infrastructure=InfrastructureInput(
            facilities=[
                FacilityInput(name="Clinic", category="SCHOOL", distance_m=120.0),
                FacilityInput(name="Depot", category="BUS_STOP", distance_m=260.0),
            ],
            status="FOUND",
        ),
        weather=WeatherInput(
            condition="Moderate rain", rain_mm=12.0, threshold_mm=5.0, status="AVAILABLE"
        ),
        historical=HistoricalInput(
            same_category_nearby_30d=4,
            same_category_nearby_7d=5,
            nearby_30d=6,
            nearby_7d=2,
            cluster_250m_30d=1,
            ward_30d=3,
            unresolved_similar_nearby=1,
            status="AVAILABLE",
        ),
        population=PopulationInput(
            reports_7d={500: 5, 1000: 8},
            unique_reporters_7d=4,
            unresolved_reports_7d=2,
            status="AVAILABLE",
        ),
        evidence=EvidenceInput(
            has_gps=True,
            description_chars=200,
            media_count=1,
            category_structured=True,
            status="PARTIAL",
        ),
    )
    assert 0 <= score <= 100
    # Component scores sum to the base; score = base + only-real amplifier bonus.
    assert _sum_scores(components, score, amplifiers) == score
    assert bucket == DynamicPriority.P3_MEDIUM
    # Every component exposes the full explainability contract.
    for c in components:
        assert all(
            k in c
            for k in (
                "key",
                "label",
                "score",
                "max_score",
                "unit",
                "status",
                "input_value",
                "explanation",
                "source",
                "calculated_at",
                "details",
            )
        )
    # Highest-scoring component is listed first (deterministic ordering).
    scores = [c["score"] for c in components]
    assert scores == sorted(scores, key=lambda s: (s is None, s), reverse=True)


# --------------------------------------------------------------------------- #
# Pure engine: honest data-availability semantics
# --------------------------------------------------------------------------- #
def test_data_unavailable_infra_is_not_scored_and_never_inflates():
    score, bucket, components, readiness, amplifiers = score_priority(
        category="ROAD",
        severity=SeverityInput(severity="MEDIUM"),
        infrastructure=InfrastructureInput(status="DATA_UNAVAILABLE"),
        weather=WeatherInput(status="DATA_UNAVAILABLE"),
        historical=HistoricalInput(status="INSUFFICIENT_DATA"),
        population=PopulationInput(status="INSUFFICIENT_DATA"),
        evidence=EvidenceInput(status="INSUFFICIENT_DATA"),
    )
    infra = next(c for c in components if c["key"] == "infrastructure")
    assert infra["score"] is None
    # Only severity scores (0.35 * 25 ≈ 9); everything else honestly unknown.
    scored = [c for c in components if c["score"] is not None]
    assert [c["key"] for c in scored] == ["severity"]
    assert score == 9
    assert bucket == DynamicPriority.P4_LOW
    assert not amplifiers
    assert readiness == PriorityReadiness.INSUFFICIENT_DATA


def test_readiness_detection_all_present_is_ready():
    _score, _bucket, components, readiness, _a = score_priority(
        category="WATER",
        severity=SeverityInput(severity="LOW"),
        infrastructure=InfrastructureInput(status="NO_VERIFIED_RECORDS"),
        weather=WeatherInput(status="AVAILABLE", condition="Clear"),
        historical=HistoricalInput(status="AVAILABLE"),
        population=PopulationInput(status="AVAILABLE"),
        evidence=EvidenceInput(status="AVAILABLE"),
    )
    # All six components report a score (even verified-zero), so readiness is full.
    assert readiness == PriorityReadiness.READY
    assert len([c for c in components if c["score"] is not None]) == 6


# --------------------------------------------------------------------------- #
# Pure engine: component differentiation (deterministic)
# --------------------------------------------------------------------------- #
def test_weather_category_multiplier_differentiates():
    rainy = WeatherInput(
        condition="Heavy rain", rain_mm=50.0, threshold_mm=5.0, status="AVAILABLE"
    )
    score_flood, _b, comps_flood, _r, _a = score_priority(
        category="FLOODING", severity=SeverityInput(severity="LOW"), weather=rainy
    )
    score_street, _b, comps_street, _r, _a = score_priority(
        category="STREET_LIGHTING", severity=SeverityInput(severity="LOW"), weather=rainy
    )
    w_flood = next(c for c in comps_flood if c["key"] == "weather")
    w_street = next(c for c in comps_street if c["key"] == "weather")
    assert w_flood["score"] > w_street["score"]
    assert score_flood > score_street


def test_distance_decay_bands_are_respected():
    bounds = (50.0, 100.0, 250.0, 500.0)
    bands = (1.0, 0.9, 0.6, 0.35)
    assert distance_band_factor(50.0, bounds) == 1.0
    assert distance_band_factor(80.0, bounds) == 0.9
    assert distance_band_factor(150.0, bounds) == 0.6
    assert distance_band_factor(400.0, bounds) == 0.35
    assert distance_band_factor(800.0, bounds) == 0.0
    assert distance_band_factor(None, bounds) == 0.0
    assert distance_band_factor(55.0, bounds) == bands[1]
    assert distance_band_factor(100.0, bounds) == bands[1]
    assert distance_band_factor(250.0, bounds) == bands[2]


def test_infrastructure_hospital_dominates_other():
    hosp = InfrastructureInput(
        facilities=[
            FacilityInput(name="Hospital", category="HOSPITAL", distance_m=50.0),
            FacilityInput(name="School", category="SCHOOL", distance_m=50.0),
        ],
        status="FOUND",
    )
    other = InfrastructureInput(
        facilities=[
            FacilityInput(name="Park", category="OTHER", distance_m=50.0),
            FacilityInput(name="Stop", category="BUS_STOP", distance_m=50.0),
        ],
        status="FOUND",
    )
    score_hosp, _b, comps_hosp, _r, _a = score_priority(
        category="WATER", severity=SeverityInput(severity="LOW"), infrastructure=hosp
    )
    score_other, _b, comps_other, _r, _a = score_priority(
        category="WATER", severity=SeverityInput(severity="LOW"), infrastructure=other
    )
    assert score_hosp > score_other
    assert next(c for c in comps_hosp if c["key"] == "infrastructure")["score"] > 0


def test_population_never_fabricated_but_reports_still_score():
    population = PopulationInput(
        reports_7d={500: 10, 250: 4},
        reports_30d={500: 12},
        unique_reporters_7d=6,
        unresolved_reports_7d=4,
        population=None,
        population_status="DATA_UNAVAILABLE",
        status="AVAILABLE",
    )
    _score, _bucket, components, _r, _a = score_priority(
        category="WATER", severity=SeverityInput(severity="LOW"), population=population
    )
    pop_comp = next(c for c in components if c["key"] == "population")
    assert pop_comp["score"] is not None
    assert pop_comp["score"] > 0
    # The absent population is explained honestly in the component details.
    assert pop_comp["details"]["population_status"] == "DATA_UNAVAILABLE"
    assert pop_comp["details"]["population"] is None


def test_score_never_renormalized_when_a_component_is_missing():
    common = dict(category="WATER", severity=SeverityInput(severity="HIGH"))
    s_missing, _b, comps_missing, _r, _a = score_priority(**common)
    s_with, _b, comps_with, _r, _a = score_priority(
        **common,
        infrastructure=InfrastructureInput(
            facilities=[
                FacilityInput(name="Hospital", category="HOSPITAL", distance_m=50.0)
            ],
            status="FOUND",
        ),
    )
    # Missing data must NOT inflate the remaining factors: the full-data run
    # scores at least as high as the degraded one, never lower.
    assert s_with >= s_missing
    keys_missing = {c["key"] for c in comps_missing}
    assert "infrastructure" not in keys_missing
    assert any(c["key"] == "infrastructure" for c in comps_with)


# --------------------------------------------------------------------------- #
# Pure engine: forecast look-ahead + deterministic risk amplifiers
# --------------------------------------------------------------------------- #
def test_weather_forecast_precip_looks_ahead():
    s_dry, _b, comps_dry, _r, _a = score_priority(
        category="DRAINAGE",
        severity=SeverityInput(severity="LOW"),
        weather=WeatherInput(
            condition="Clear", rain_mm=0.0, threshold_mm=5.0, status="AVAILABLE"
        ),
    )
    s_forecast, _b, comps_fc, _r, amps_fc = score_priority(
        category="DRAINAGE",
        severity=SeverityInput(severity="LOW"),
        weather=WeatherInput(
            condition="Clear",
            rain_mm=0.0,
            threshold_mm=5.0,
            forecast_precip_mm=12.0,
            status="AVAILABLE",
        ),
    )
    w_fc = next(c for c in comps_fc if c["key"] == "weather")
    w_dry = next(c for c in comps_dry if c["key"] == "weather")
    # A 12 mm next-days forecast beats a dry forecast for the same complaint.
    assert w_fc["score"] > w_dry["score"]
    assert s_forecast > s_dry
    # The flooding amplifier explicitly cites the forecast as its evidence.
    flooding = next(a for a in amps_fc if a["key"] == "FLOODING_RISK")
    assert flooding["applied"] is True
    assert any("forecast" in e.lower() for e in flooding["evidence"])


def test_amplifiers_fire_only_on_real_evidence():
    # Scenario 1: recurring flooding + emergent facility proximity — real data.
    score1, _b1, _c1, _r1, amps1 = score_priority(
        category="FLOODING",
        severity=SeverityInput(severity="LOW"),
        infrastructure=InfrastructureInput(
            facilities=[
                FacilityInput(name="City Hospital", category="HOSPITAL", distance_m=30.0)
            ],
            status="FOUND",
        ),
        historical=HistoricalInput(
            same_category_nearby_30d=6, unresolved_similar_nearby=2, status="AVAILABLE"
        ),
    )
    keys1 = {a["key"] for a in amps1}
    # FLOODING is also a public-safety complaint category and the hospital sits
    # within 150 m of the hazard, so three amplifiers fire on real evidence.
    assert keys1 == {
        "FLOODING_RISK",
        "EMERGENCY_ACCESS_RISK",
        "PUBLIC_SAFETY_RISK",
        "RECURRING_HOTSPOT",
    }
    assert sum(a["points"] for a in amps1) == 6 + 5 + 5 + 4
    assert all(a["applied"] and a["evidence"] for a in amps1)

    # Scenario 2: same inputs but NO real evidence → no amplifier adds points.
    score2, _b2, _c2, _r2, amps2 = score_priority(
        category="OTHER",
        severity=SeverityInput(severity="LOW"),
        infrastructure=InfrastructureInput(status="NO_VERIFIED_RECORDS"),
        historical=HistoricalInput(status="AVAILABLE"),
    )
    assert amps2 == []
    assert score2 == sum(int(c["score"] or 0) for c in _c2)


def test_amplifier_points_capped_and_explained():
    extreme = _extreme_bundle()
    score, _b, _c, _r, amps = score_priority(**extreme)
    assert score == 100  # base + amplifier bonus clamped to 100
    flooding = next(a for a in amps if a["key"] == "FLOODING_RISK")
    assert flooding["points"] > 0
    assert flooding["trigger_conditions"]
    assert flooding["evidence"]
    # Recounting twice yields identical amplifiers (deterministic).
    _s2, _b2, _c2, _r2, amps2 = score_priority(**extreme)
    assert amps == amps2


# --------------------------------------------------------------------------- #
# SLA is SEPARATE from the score (time never inflates risk)
# --------------------------------------------------------------------------- #
def test_sla_breach_never_raises_engine_score():
    # The engine has NO time input at all — identical bundle ⇒ identical score,
    # regardless of how long the complaint has been open.
    bundle = dict(
        category="WATER",
        severity=SeverityInput(severity="HIGH"),
        infrastructure=InfrastructureInput(status="NO_VERIFIED_RECORDS"),
    )
    first = score_priority(**bundle)[0]
    second = score_priority(**bundle)[0]
    assert first == second == 16  # 0.65 * 25 = 16, nothing else scores


def test_sla_status_reporting_states():
    open_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    now = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)  # 24 h later
    policy = SlaPolicy(
        id=uuid.uuid4(),
        name="SLA-24",
        priority="P1_CRITICAL",
        sla_hours=12,
        at_risk_percent=0.6,
        escalate_on_breach=True,
        active=True,
    )
    # No rule → NO_POLICY; never blocks scoring and carries no deadline.
    assert complaint_sla_status(
        priority="P1_CRITICAL", department=None, category="WATER",
        submitted_at=open_at, now=now, policy=None,
    )["state"] == "NO_POLICY"
    # Well inside the window → ON_TRACK.
    ok = complaint_sla_status(
        priority="P1_CRITICAL", department=None, category="WATER",
        submitted_at=now - timedelta(hours=2), now=now, policy=policy,
    )
    assert ok["state"] == "ON_TRACK"
    assert ok["breached"] is False
    assert ok["sla_hours"] == 12
    # Past the 12 h deadline → BREACHED (escalation 3, never a higher score).
    br = complaint_sla_status(
        priority="P1_CRITICAL", department=None, category="WATER",
        submitted_at=open_at, now=now, policy=policy,
    )
    assert br["state"] == "BREACHED"
    assert br["breached"] is True
    assert br["escalation_level"] == 3


# --------------------------------------------------------------------------- #
# Pure engine: evidence semantics
# --------------------------------------------------------------------------- #
def test_evidence_insufficient_and_partial():
    _s, _b, comps_ins, _r, _a = score_priority(
        category="WATER",
        severity=SeverityInput(severity="LOW"),
        evidence=EvidenceInput(status="INSUFFICIENT_DATA"),
    )
    ev_ins = next(c for c in comps_ins if c["key"] == "evidence")
    assert ev_ins["score"] is None
    assert ev_ins["status"] == "INSUFFICIENT_DATA"
    assert ev_ins["unit"] == 0.0

    _s2, _b2, comps_part, _r2, _a2 = score_priority(
        category="WATER",
        severity=SeverityInput(severity="LOW"),
        evidence=EvidenceInput(
            has_gps=True,
            description_chars=200,
            media_count=1,
            category_structured=True,
            status="PARTIAL",  # no AI signal (triage/vision) yet
        ),
    )
    ev_part = next(c for c in comps_part if c["key"] == "evidence")
    assert ev_part["score"] is not None
    assert ev_part["score"] > 0
    assert ev_part["status"] == "PARTIAL"
    assert ev_part["details"]["triage_available"] is False


def test_dedupe_counts_are_explained_in_details():
    _s, _b, comps, _r, _a = score_priority(
        category="ROAD",
        severity=SeverityInput(severity="MEDIUM"),
        historical=HistoricalInput(
            same_category_nearby_30d=5,
            same_category_nearby_7d=1,
            nearby_30d=9,
            nearby_7d=2,
            cluster_250m_30d=1,
            ward_30d=3,
            unresolved_similar_nearby=1,
            duplicates_excluded=2,
            status="AVAILABLE",
        ),
    )
    hist = next(c for c in comps if c["key"] == "historical")
    assert hist["details"]["duplicates_excluded"] == 2


# --------------------------------------------------------------------------- #
# Calibration vs the legacy seed scenario
# --------------------------------------------------------------------------- #
def test_calibration_seed_scenario_scores_above_legacy_31():
    """The OLD model scored the seed-like flooding/school scenario 31/100.

    The rebuilt engine must rank the same *real* signals meaningfully higher (the
    deterministic scenario here mirrors the seeded complaint's context: HIGH
    severity + hospital/school adjacency + heavy-rain forecast + recurrence).
    """
    scoring = dict(
        category="FLOODING",
        severity=SeverityInput(severity="HIGH"),
        infrastructure=InfrastructureInput(
            facilities=[
                FacilityInput(name="School", category="SCHOOL", distance_m=90.0),
                FacilityInput(name="Hospital", category="HOSPITAL", distance_m=150.0),
            ],
            status="FOUND",
            radius_m=1000.0,
        ),
        weather=WeatherInput(
            condition="Moderate rain", rain_mm=6.5, forecast_precip_mm=8.0,
            threshold_mm=5.0, status="AVAILABLE",
        ),
        historical=HistoricalInput(
            same_category_nearby_30d=4,
            same_category_nearby_7d=2,
            nearby_30d=8,
            nearby_7d=3,
            cluster_250m_30d=1,
            ward_30d=6,
            unresolved_similar_nearby=1,
            status="AVAILABLE",
        ),
        population=PopulationInput(
            reports_7d={500: 4, 250: 2},
            unresolved_reports_7d=1,
            status="AVAILABLE",
        ),
        evidence=EvidenceInput(
            has_gps=True,
            description_chars=180,
            media_count=1,
            category_structured=True,
            status="PARTIAL",
        ),
    )
    score, bucket, _c, readiness, _a = score_priority(**scoring)
    assert score > _LEGACY_SEED_SCORE  # recalibrated above the old 31/100
    assert bucket != DynamicPriority.P4_LOW
    assert readiness in (PriorityReadiness.READY, PriorityReadiness.PARTIAL)
    # Deterministic: recomputing the identical scenario reproduces the score.
    assert score_priority(**scoring)[0] == score


@pytest.mark.asyncio
async def test_calibration_actual_seeded_complaint():
    """Reproduce/verify the real seeded complaint's score if it exists.

    The legacy engine scored the seeded complaint 31/100 (P4_LOW). If the seeded
    complaint is present in the dev DB, recompute it with the rebuilt engine and
    assert the result is reproducible and moved meaningfully up. Skipped when the
    seed row is absent (e.g. a fresh/CI DB without that fixture).
    """
    async with async_session_factory() as db:
        comp = await db.get(Complaint, uuid.UUID(_SEED_COMPLAINT_ID))
    if comp is None:
        pytest.skip("Seeded calibration complaint is not present in this DB.")
    async with async_session_factory() as db:
        first = await PriorityAgent(settings=_SETTINGS).run(
            db, complaint_id=uuid.UUID(_SEED_COMPLAINT_ID)
        )
    async with async_session_factory() as db:
        second = await PriorityAgent(settings=_SETTINGS).run(
            db, complaint_id=uuid.UUID(_SEED_COMPLAINT_ID)
        )
    assert first.status.value == "SUCCEEDED"
    assert second.status.value == "SUCCEEDED"
    result = first.structured_result
    assert 0 <= result["score"] <= 100
    # Reproducible across runs (deterministic engine, apart from live timestamps).
    assert second.structured_result["score"] >= result["score"] - 1
    # Recalibrated above the legacy 31/100 for the same incident.
    assert result["score"] > _LEGACY_SEED_SCORE
    assert result["risk_amplifiers"] is not None
    assert result["sla"] is not None


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
    assert "risk_amplifiers" in result  # v2 payload carries the amplifiers
    assert "sla" in result  # and the separate SLA snapshot
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
    assert hist[0].risk_amplifiers is not None
    assert hist[0].sla is not None
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
    assert "risk_amplifiers" in result
    assert "sla" in result

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
    # Config exposes the six new weights + thresholds + change threshold.
    assert _SETTINGS.PRIORITY_WEIGHT_SEVERITY == 25.0
    assert _SETTINGS.PRIORITY_WEIGHT_INFRASTRUCTURE == 20.0
    assert _SETTINGS.PRIORITY_WEIGHT_POPULATION == 20.0
    assert _SETTINGS.PRIORITY_WEIGHT_HISTORY == 15.0
    assert _SETTINGS.PRIORITY_WEIGHT_WEATHER == 10.0
    assert _SETTINGS.PRIORITY_WEIGHT_EVIDENCE == 10.0
    assert _SETTINGS.PRIORITY_WEATHER_RAIN_MM > 0
    assert _SETTINGS.PRIORITY_AMPLIFIER_FLOODING_POINTS > 0
    assert _SETTINGS.PRIORITY_THRESHOLD_P1 == 80.0
    assert _SETTINGS.PRIORITY_CHANGE_THRESHOLD > 0


# --------------------------------------------------------------------------- #
# Calibration v3 — real-case scenario pinning (no inflation, honest data)
# --------------------------------------------------------------------------- #
def _calib_facilities() -> list[FacilityInput]:
    cells = [
        ("Hospital", "HOSPITAL", 55.0),
        ("Hospital", "HOSPITAL", 268.0),
        ("Police Station", "POLICE_STATION", 443.0),
        ("Bus Stop", "BUS_STOP", 342.0),
        ("Bus Stop", "BUS_STOP", 443.0),
        ("Park", "OTHER", 800.0),
    ]
    return [
        FacilityInput(
            name=name, category=cat, distance_m=d, verification="VERIFIED"
        )
        for name, cat, d in cells
    ]


def _calib_infra() -> InfrastructureInput:
    return InfrastructureInput(
        facilities=_calib_facilities(), status="FOUND", radius_m=1000.0
    )


def _calib_population(sensitive: bool = True) -> PopulationInput:
    return PopulationInput(
        reports_7d={250: 0, 500: 0, 1000: 0},
        reports_30d={250: 0, 500: 0, 1000: 0},
        unique_reporters_7d=0,
        unique_reporters_30d=0,
        unresolved_reports_7d=0,
        unresolved_reports_30d=0,
        spread_max_distance_m=None,
        sensitive_facilities_nearby=(2 if sensitive else 0),
        sensitive_facilities=(
            [
                FacilityInput(name="Hospital", category="HOSPITAL", distance_m=55.0),
                FacilityInput(name="Bus Stop", category="BUS_STOP", distance_m=342.0),
            ]
            if sensitive
            else []
        ),
        population=None,
        population_status="DATA_UNAVAILABLE",
        status="AVAILABLE",
    )


def _calib_weather(dry: bool = True) -> WeatherInput:
    return WeatherInput(
        condition="dry" if dry else "rain",
        rain_mm=0.0 if dry else 35.0,
        forecast_precip_mm=0.0,
        status="AVAILABLE",
        threshold_mm=5.0,
    )


def _calib_history(recurrence: int = 2) -> HistoricalInput:
    return HistoricalInput(
        same_category_nearby_30d=recurrence,
        same_category_nearby_7d=0,
        nearby_30d=3,
        nearby_7d=0,
        cluster_250m_30d=0,
        ward_30d=8,
        unresolved_similar_nearby=1,
        duplicates_excluded=0,
        status="AVAILABLE",
    )


def _calib_evidence() -> EvidenceInput:
    return EvidenceInput(
        has_gps=True,
        gps_source="device",
        gps_accuracy_m=5.0,
        description_chars=120,
        media_count=1,
        category_structured=True,
        triage_available=True,
        triage_confidence=0.9,
        vision_available=False,
        vision_confidence=None,
        vision_mismatch=False,
        corroborating_reports_30d=0,
        status="AVAILABLE",
    )


def _comp(comps: list[dict], key: str) -> dict:
    return next(c for c in comps if c["key"] == key)


def test_calibration_scenario_reports_honest_detailed_parts():
    # The real CASE-1 complaint (ROAD, MEDIUM, hospital 55 m / 268 m, police &
    # bus stops, dry weather, 2 similar in 30 d): the engine must reflect real
    # exposure without inflating any component.
    score, bucket, comps, readiness, amps = score_priority(
        category="ROAD",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
        infrastructure=_calib_infra(),
        population=_calib_population(),
        weather=_calib_weather(dry=True),
        historical=_calib_history(recurrence=2),
        evidence=_calib_evidence(),
    )
    infra = _comp(comps, "infrastructure")
    pop = _comp(comps, "population")
    sev = _comp(comps, "severity")
    assert infra["score"] is not None and 16 <= infra["score"] <= 19
    assert pop["score"] is not None and 4 <= pop["score"] <= 8
    assert sev["score"] is not None and 11 <= sev["score"] <= 14
    assert _comp(comps, "weather")["score"] <= 2
    assert readiness.value == "READY"
    assert bucket.value in {"P2_HIGH", "P3_MEDIUM"}

    fac = infra["details"]["contributing_facilities"]
    by_name = {f["name"]: f for f in fac}
    assert by_name["Hospital"]["relevance"] > 0.9
    assert by_name["Hospital"]["contribution"] > by_name["Park"]["contribution"]
    assert by_name["Park"]["contribution"] == 0
    access = infra["details"]["access_impact"]
    assert access["emergency_access_impacted"] is True
    assert access["emergency_facilities_within_band"][0]["distance_m"] == 55.0

    sev_dims = sev["details"]["dimensions"]
    assert sev_dims["accessibility"] > 0
    assert sev["details"]["base_unit"] == 0.35

    pops = pop["details"]["subcomponents"]
    assert pops["population_exposure"]["status"] == "DATA_UNAVAILABLE"
    assert pops["population_exposure"]["score"] is None
    assert pops["sensitive_facility_exposure"]["status"] == "AVAILABLE"
    assert pops["sensitive_facility_exposure"]["score"] is not None
    assert len(pop["details"]["sensitive_facilities"]) == 2

    keys = {a["key"] for a in amps}
    assert "EMERGENCY_ACCESS_RISK" in keys
    assert "PUBLIC_SAFETY_RISK" in keys


def test_calibration_emergency_amplifier_requires_access_category():
    # A hospital 55 m away must NOT trigger EMERGENCY_ACCESS_RISK for an
    # unrelated category; an access-affecting category must.
    blocked = score_priority(
        category="STREET_LIGHTING",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
        infrastructure=_calib_infra(),
    )[4]
    assert "EMERGENCY_ACCESS_RISK" not in {a["key"] for a in blocked}
    for cat in ("ROAD", "FLOODING", "DRAINAGE", "GARBAGE", "PUBLIC_SAFETY"):
        fired = score_priority(
            category=cat,
            severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
            infrastructure=_calib_infra(),
        )[4]
        assert "EMERGENCY_ACCESS_RISK" in {a["key"] for a in fired}, cat


def test_calibration_flooding_amplifier_needs_rain_or_recurrence():
    dry = WeatherInput(
        condition="dry", rain_mm=0.0, forecast_precip_mm=0.0,
        status="AVAILABLE", threshold_mm=5.0,
    )
    rainy = WeatherInput(
        condition="rain", rain_mm=6.0, forecast_precip_mm=0.0,
        status="AVAILABLE", threshold_mm=5.0,
    )
    hist_zero = HistoricalInput(
        status="AVAILABLE",
        same_category_nearby_30d=0, same_category_nearby_7d=0,
        nearby_30d=0, nearby_7d=0, cluster_250m_30d=0, ward_30d=0,
        unresolved_similar_nearby=0, duplicates_excluded=0,
    )
    hist_recur = HistoricalInput(
        status="AVAILABLE",
        same_category_nearby_30d=6, same_category_nearby_7d=1,
        nearby_30d=8, nearby_7d=2, cluster_250m_30d=2, ward_30d=12,
        unresolved_similar_nearby=2, duplicates_excluded=0,
    )
    sev = SeverityInput(severity="MEDIUM", status="AVAILABLE")

    gone = score_priority(
        category="DRAINAGE", severity=sev, weather=dry, historical=hist_zero
    )[4]
    assert "FLOODING_RISK" not in {a["key"] for a in gone}
    rained = score_priority(
        category="DRAINAGE", severity=sev, weather=rainy, historical=hist_zero
    )[4]
    assert "FLOODING_RISK" in {a["key"] for a in rained}
    recurred = score_priority(
        category="DRAINAGE", severity=sev, weather=dry, historical=hist_recur
    )[4]
    assert "FLOODING_RISK" in {a["key"] for a in recurred}


def test_calibration_population_unavailable_grid_is_not_zero():
    # No population grid wired: the sub-signal is HONESTLY DATA_UNAVAILABLE, but
    # real signals (sensitive facilities) still score; zero real signals score 0.
    with_sensitive = score_priority(
        category="ROAD",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
        population=_calib_population(sensitive=True),
    )[2]
    no_sensitive = score_priority(
        category="ROAD",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
        population=_calib_population(sensitive=False),
    )[2]
    assert _comp(with_sensitive, "population")["score"] >= 4
    assert _comp(no_sensitive, "population")["score"] <= 1


def test_calibration_severity_context_boost_is_bounded():
    heavy = PopulationInput(
        reports_7d={250: 3, 500: 2, 1000: 5},
        reports_30d={250: 0, 500: 0, 1000: 0},
        unique_reporters_7d=2, unique_reporters_30d=0,
        unresolved_reports_7d=0, unresolved_reports_30d=0,
        spread_max_distance_m=900.0,
        sensitive_facilities_nearby=1,
        sensitive_facilities=[
            FacilityInput(name="Hospital", category="HOSPITAL", distance_m=55.0)
        ],
        population=None, population_status="DATA_UNAVAILABLE", status="AVAILABLE",
    )
    storm = WeatherInput(
        condition="heavy rain", rain_mm=40.0, forecast_precip_mm=12.0,
        status="AVAILABLE", threshold_mm=5.0,
    )
    _, _, comps, _, _ = score_priority(
        category="DRAINAGE",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
        infrastructure=_calib_infra(),
        population=heavy,
        weather=storm,
    )
    sev = _comp(comps, "severity")
    assert 12 <= sev["score"] <= 15
    bare = score_priority(
        category="DRAINAGE",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
    )[2]
    assert _comp(bare, "severity")["score"] == 9


def test_calibration_weather_resaturates_to_40mm_and_is_category_aware():
    sev = SeverityInput(severity="MEDIUM", status="AVAILABLE")
    for cond, mm, cat, expected in (
        ("dry", 0.0, "ROAD", 1),
        ("clear", 0.0, "ROAD", 1),
        ("light rain", 8.0, "ROAD", 6),  # rainy floor 0.6, NOT 10
        ("heavy rain", 40.0, "ROAD", 10),
        ("heavy rain", 40.0, "DRAINAGE", 10),
        ("light rain", 8.0, "STREET_LIGHTING", 1),  # 0.6*0.15 → ~1 (was 10/10)
    ):
        w = WeatherInput(
            condition=cond, rain_mm=mm, forecast_precip_mm=0.0,
            status="AVAILABLE", threshold_mm=5.0,
        )
        comps = score_priority(category=cat, severity=sev, weather=w)[2]
        got = _comp(comps, "weather")["score"]
        assert got == expected, (cond, mm, cat, got)


def test_calibration_evidence_ai_confidence_maps_one_to_one():
    # Real AI verification confidence drives the evidence score 1:1 (98 % ~ 10/10,
    # 90 % ~ 9, 80 % ~ 8, 70 % ~ 7), with vision preferred over triage and a
    # vision mismatch voiding the vision signal entirely.
    def ev(conf=None, vision=0.95, mismatch=False, triage=None):
        return EvidenceInput(
            has_gps=False,
            gps_source=None,
            gps_accuracy_m=None,
            description_chars=20,
            media_count=0,
            category_structured=False,
            triage_available=conf is not None,
            triage_confidence=conf,
            vision_available=vision is not None,
            vision_confidence=vision,
            vision_mismatch=mismatch,
            corroborating_reports_30d=0,
            status="AVAILABLE",
        )

    assert ai_evidence_confidence(ev(None, vision=0.98))[0] == 0.98
    assert ai_evidence_confidence(ev(None, vision=0.98))[1] == "vision"
    assert ai_evidence_confidence(ev(0.9, vision=None))[1] == "triage"
    assert ai_evidence_confidence(ev(0.9, vision=None))[0] == 0.9
    assert ai_evidence_confidence(ev(0.5, vision=0.95, mismatch=True))[0] == 0.5
    assert ai_evidence_confidence(ev(0.5, vision=0.95, mismatch=True))[1] == "triage"
    assert ai_evidence_confidence(ev(None, vision=None)) == (None, None)

    for conf, expected in ((0.98, 10), (0.90, 9), (0.80, 8), (0.70, 7)):
        got = score_priority(
            category="ROAD",
            severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
            evidence=ev(None, vision=conf),
        )[2]
        assert _comp(got, "evidence")["score"] == expected, conf
        assert _comp(got, "evidence")["details"]["ai_verification_source"] == "vision"
        assert _comp(got, "evidence")["details"]["ai_verification_confidence_pct"] == (
            int(round(conf * 100))
        )

    partial = score_priority(
        category="ROAD",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
        evidence=ev(None, vision=None, triage=None),
    )[2]
    ev_comp = _comp(partial, "evidence")
    assert ev_comp["score"] <= 5  # non-AI signals capped at 0.85, honest low score
    assert ev_comp["details"]["ai_verification_source"] is None


def test_calibration_infrastructure_saturates_only_with_real_verified_proximity():
    # A genuinely blocked emergency route — ROAD with a police station 10 m away —
    # reaches max exposure, but the same facility list plays NO role for a
    # non-access category and nothing at all when nothing is near.
    blocked = InfrastructureInput(
        facilities=[
            FacilityInput(
                name="Police", category="POLICE_STATION", distance_m=10.0,
                verification="VERIFIED",
            ),
            FacilityInput(
                name="Hospital", category="HOSPITAL", distance_m=85.0,
                verification="VERIFIED",
            ),
        ],
        status="FOUND",
        radius_m=1000.0,
    )
    road = score_priority(
        category="ROAD",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
        infrastructure=blocked,
    )[2]
    assert 18 <= _comp(road, "infrastructure")["score"] <= 20  # police 10 m → near-max

    street = score_priority(
        category="STREET_LIGHTING",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
        infrastructure=blocked,
    )[2]
    infra_street = _comp(street, "infrastructure")["score"]
    assert infra_street < _comp(road, "infrastructure")["score"]

    far = InfrastructureInput(
        facilities=[
            FacilityInput(
                name="Hospital", category="HOSPITAL", distance_m=550.0,
                verification="VERIFIED",
            ),
            FacilityInput(
                name="Park", category="OTHER", distance_m=600.0,
                verification="VERIFIED",
            ),
        ],
        status="FOUND",
        radius_m=1000.0,
    )
    far_road = score_priority(
        category="ROAD",
        severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
        infrastructure=far,
    )[2]
    assert _comp(far_road, "infrastructure")["score"] == 0  # all beyond the 500 m band


def test_calibration_severity_escalates_toward_high_not_to_max():
    # The documented CASE-1-like condition (access-affecting category, verified
    # emergency facility ≤100 m, MEDIUM triage) must push severity UP toward HIGH
    # — it must exceed the bare-MEDIUM 9 but never be forced to 25 (25 only for a
    # real HIGH with verified critical infrastructure inside the access floor).
    sev = SeverityInput(severity="MEDIUM", status="AVAILABLE")
    comps = score_priority(
        category="ROAD",
        severity=sev,
        infrastructure=_calib_infra(),
    )[2]
    sev_comp = _comp(comps, "severity")
    assert sev_comp["score"] > 9
    assert sev_comp["score"] <= 15
    assert sev_comp["details"]["escalation_formula"].startswith("unit = base_unit")

    extreme = score_priority(
        category="ROAD",
        severity=SeverityInput(severity="HIGH", status="AVAILABLE"),
        infrastructure=InfrastructureInput(
            facilities=[
                FacilityInput(
                    name="Police", category="POLICE_STATION", distance_m=10.0,
                    verification="VERIFIED",
                ),
            ],
            status="FOUND",
        ),
    )[2]
    assert 16 <= _comp(extreme, "severity")["score"] <= 25
    assert _comp(extreme, "severity")["score"] < 25  # even HIGH + access floor stays bounded


def test_calibration_scenario_a_through_e():
    # End-to-end honesty sweep: five documented scenarios must fall in the stated
    # buckets and no component may ever outrun reality.
    scenarios = [
        (
            "A - verified critical access impacted",
            dict(
                category="ROAD", severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
                infrastructure=_calib_infra(), weather=_calib_weather(dry=True),
                historical=_calib_history(recurrence=2), evidence=_calib_evidence(),
            ),
            {"P2_HIGH", "P3_MEDIUM", "P1_CRITICAL"},
        ),
        (
            "B - bare medium, dry, nothing near",
            dict(category="ROAD", severity=SeverityInput(severity="MEDIUM", status="AVAILABLE")),
            {"P3_MEDIUM", "P4_LOW"},
        ),
        (
            "C - heavy rain flooding",
            dict(
                category="FLOODING", severity=SeverityInput(severity="MEDIUM", status="AVAILABLE"),
                weather=_calib_weather(dry=False),
            ),
            {"P3_MEDIUM", "P4_LOW"},  # rain alone bumps weather, not the whole score
        ),
        (
            "D - unattributed street light",
            dict(
                category="STREET_LIGHTING",
                severity=SeverityInput(severity="LOW", status="AVAILABLE"),
            ),
            {"P4_LOW"},
        ),
        (
            "E - verified high critical cluster + storm",
            dict(
                category="FLOODING", severity=SeverityInput(severity="HIGH", status="AVAILABLE"),
                infrastructure=_calib_infra(), weather=_calib_weather(dry=False),
                historical=_calib_history(recurrence=4), evidence=_calib_evidence(),
            ),
            {"P1_CRITICAL", "P2_HIGH"},
        ),
    ]
    for label, kwargs, allowed in scenarios:
        score, bucket, comps, readiness, amps = score_priority(**kwargs)
        assert bucket.value in allowed, (label, score, bucket.value)
        assert 0 <= score <= 100
        for c in comps:
            assert c["score"] is None or c["score"] <= c["max_score"]
