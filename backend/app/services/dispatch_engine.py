"""Worker-selection scoring engine for work-order dispatch (Part 14).

Deterministic, explainable candidate scoring — **never random**. Given a work
order's routing ``department``, its location, and the required skills/equipment,
each candidate ``FieldWorker`` is scored on five normalized criteria:

* **Availability** — `1.0` when the worker is ACTIVE *and* under their workload
  ceiling, else `0.0` (an unavailable worker is de-prioritized).
* **Skill** — fraction of the order's required skill tags the worker's
  ``specialty`` + ``skill_tags`` cover.
* **Distance** — inverse of haversine distance (home → order location), scaled by
  ``DISPATCH_DISTANCE_REF_KILOMETERS``.
* **Workload** — fraction of capacity still free (current active orders vs the
  worker's ``max_active_orders`` / settings default).
* **Equipment** — fraction of the order's required equipment the worker possesses.

The weighted sum (setting weights) produces a single 0–1 score; ties break by
worker id for full determinism. The result includes the sub-scores and a short
human-readable rationale so a dispatch decision is always explainable and can be
reviewed by an officer.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.models.enums import WorkerStatus


@dataclass(frozen=True)
class CandidateInput:
    """A worker's dispatch-relevant attributes (decoupled from the ORM row)."""

    worker_id: uuid.UUID
    name: str
    department_code: str | None  # the Routing DepartmentCode the crew serves
    status: WorkerStatus
    specialty: str | None
    skill_tags: list[str]
    equipment: list[str]
    home_lat: float | None
    home_lon: float | None
    active_orders: int = 0
    max_active_orders: int | None = None


@dataclass(frozen=True)
class CandidateScore:
    """Scoring breakdown for one worker."""

    worker_id: uuid.UUID
    name: str
    score: float
    available: bool
    availability: float
    skill: float
    distance: float
    workload: float
    equipment: float
    reasons: list[str] = field(default_factory=list)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two coordinates."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _skill_match(specialty: str | None, skill_tags: list[str], required: list[str]) -> float:
    if not required:
        return 1.0
    tags = {t.strip().lower() for t in (skill_tags or []) if t}
    if specialty:
        tags.add(specialty.strip().lower())
    covered = sum(1 for r in required if r.strip().lower() in tags)
    return covered / len(required)


def _equipment_match(owned: list[str], required: list[str]) -> float:
    if not required:
        return 1.0
    owned_set = {e.strip().lower() for e in (owned or []) if e}
    covered = sum(1 for r in required if r.strip().lower() in owned_set)
    return covered / len(required)


def _workload_fraction(active: int, capacity: int) -> float:
    if capacity <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - active / capacity))


def score_candidate(
    worker: CandidateInput,
    *,
    required_skills: list[str],
    required_equipment: list[str],
    order_lat: float,
    order_lon: float,
    settings: Settings | None = None,
) -> CandidateScore:
    """Score a single worker. Never random — fully deterministic by the formula."""
    s = settings or get_settings()

    capacity = worker.max_active_orders or s.DISPATCH_MAX_ACTIVE_ORDERS
    available = worker.status == WorkerStatus.ACTIVE and worker.active_orders < capacity
    availability = 1.0 if available else 0.0

    total_w = (
        s.DISPATCH_WEIGHT_AVAILABILITY
        + s.DISPATCH_WEIGHT_SKILL
        + s.DISPATCH_WEIGHT_DISTANCE
        + s.DISPATCH_WEIGHT_WORKLOAD
        + s.DISPATCH_WEIGHT_EQUIPMENT
    )
    if total_w <= 0:
        total_w = 1.0

    skill = _skill_match(worker.specialty, worker.skill_tags, required_skills)
    equipment = _equipment_match(worker.equipment, required_equipment)

    distance_score = 0.0
    if (
        worker.home_lat is not None
        and worker.home_lon is not None
        and order_lat is not None
        and order_lon is not None
    ):
        km = haversine_km(worker.home_lat, worker.home_lon, order_lat, order_lon)
        ref = s.DISPATCH_DISTANCE_REF_KILOMETERS or 1.0
        distance_score = max(0.0, 1.0 - km / ref)

    workload = _workload_fraction(worker.active_orders, capacity)

    score = (
        s.DISPATCH_WEIGHT_AVAILABILITY * availability
        + s.DISPATCH_WEIGHT_SKILL * skill
        + s.DISPATCH_WEIGHT_DISTANCE * distance_score
        + s.DISPATCH_WEIGHT_WORKLOAD * workload
        + s.DISPATCH_WEIGHT_EQUIPMENT * equipment
    ) / total_w
    score = round(max(0.0, min(1.0, score)), 4)

    reasons: list[str] = []
    if not available:
        reasons.append("busy or unavailable")
    if skill < 1.0:
        reasons.append(f"skill match {skill * 100:.0f}%")
    if distance_score < 0.5:
        reasons.append("far from site")
    if workload < 1.0:
        reasons.append(f"workload {worker.active_orders}/{capacity}")

    return CandidateScore(
        worker_id=worker.worker_id,
        name=worker.name,
        score=score,
        available=available,
        availability=availability,
        skill=skill,
        distance=round(distance_score, 4),
        workload=round(workload, 4),
        equipment=round(equipment, 4),
        reasons=reasons,
    )


def rank_candidates(
    workers: list[CandidateInput],
    *,
    required_skills: list[str],
    required_equipment: list[str],
    order_lat: float | None,
    order_lon: float | None,
    department: str | None = None,
    settings: Settings | None = None,
) -> list[CandidateScore]:
    """Rank workers by score (desc; ties by worker id asc) and cap the results.

    Deterministic order by ``(score desc, name asc, worker_id asc)`` so the same
    inputs always yield the same recommendation.
    """
    s = settings or get_settings()
    lat = order_lat
    lon = order_lon
    if lat is None or lon is None:
        lat = 0.0
        lon = 0.0

    pool = workers
    if department:
        pool = [w for w in workers if w.department_code is not None]
        # Prefer the crew matching the order's department first, but do not drop
        # other-department eligible workers entirely (they remain lower-ranked).
        pool = sorted(pool, key=lambda w: (w.department_code != department, w.name))

    scored = [
        score_candidate(
            w,
            required_skills=required_skills,
            required_equipment=required_equipment,
            order_lat=lat,
            order_lon=lon,
            settings=s,
        )
        for w in pool
    ]
    scored.sort(
        key=lambda c: (
            -c.score,
            c.name.lower(),
            str(c.worker_id),
        )
    )
    return scored[: max(1, s.DISPATCH_MAX_CANDIDATES)]
