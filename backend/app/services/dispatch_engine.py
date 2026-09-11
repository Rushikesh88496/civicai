"""Worker-selection scoring engine for work-order dispatch (Part 14).

Deterministic, explainable candidate scoring — **never random**. Given a work
order's routing ``department``, its ward, its location, its priority bucket, and
the required skills/equipment, each candidate ``FieldWorker`` is scored on eight
normalized criteria:

* **Availability** — `1.0` when the worker is ACTIVE *and* under their workload
  ceiling, else `0.0` (an unavailable worker is de-prioritized).
* **Skill** — fraction of the order's required skill tags the worker's
  ``specialty`` + ``skill_tags`` cover.
* **Department** — `1.0` when the worker's crew owns the routed department (the
  legacy seeded crews PW/SN/PR are aliased to the seven routing departments),
  else `0.0`.
* **Ward** — `1.0` when the worker's home ward equals the complaint's ward,
  else `0.0`.
* **Distance** — inverse of the great-circle distance home → order location
  (PostGIS when available, haversine fallback), scaled by
  ``DISPATCH_DISTANCE_REF_KILOMETERS``.
* **Workload** — fraction of capacity still free (current active orders vs the
  worker's ``max_active_orders`` / settings default).
* **Equipment** — fraction of the order's required equipment the worker possesses.
* **Priority** — urgency factor from the complaint's dynamic priority bucket
  (`1.0` for urgent P1/P2/HIGH/CRITICAL, else `0.5`); urgent orders also shift
  ``DISPATCH_PRIORITY_URGENCY_BOOST`` from the workload weight onto the distance
  weight so the nearest available skilled worker is preferred.

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
    department_code: str | None  # the crew the worker serves (e.g. PW/SN/PR)
    status: WorkerStatus
    specialty: str | None
    skill_tags: list[str]
    equipment: list[str]
    home_lat: float | None
    home_lon: float | None
    active_orders: int = 0
    max_active_orders: int | None = None
    ward_code: str | None = None  # the ward the worker is based in (home ward)
    # Pre-computed distance home -> order location (PostGIS source). When None
    # the engine falls back to haversine in-process.
    precomputed_distance_km: float | None = None


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
    department: float = 0.0
    ward: float = 0.0
    priority: float = 0.0
    distance_km: float | None = None
    department_code: str | None = None
    ward_code: str | None = None
    # Raw workload snapshot behind ``workload`` (real counts from CandidateInput).
    active_orders: int = 0
    capacity: int | None = None
    reasons: list[str] = field(default_factory=list)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two coordinates."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# Which legacy seeded maintenance crews own each routing department. This is the
# bridge between the routing codes (Part 13) and the real seeded crews (PW/SN/PR)
# so a recommendation can reward the department that actually owns the work.
_ROUTING_DEPARTMENT_CREW: dict[str, set[str]] = {
    "WATER": {"PW"},
    "ROADS": {"PW"},
    "ELECTRICAL": {"PW"},
    "WASTE": {"SN"},
    "DRAINAGE": {"SN"},
    "PARKS": {"PR"},
    "EMERGENCY_DISASTER": {"PW", "SN"},
}


def _department_match(worker_code: str | None, order_department: str | None) -> float:
    """1.0 when the worker's crew owns the routed department (exact or aliased)."""
    if not worker_code or not order_department:
        return 0.0
    order = order_department.upper()
    code = worker_code.upper()
    if code == order:
        return 1.0
    crew = _ROUTING_DEPARTMENT_CREW.get(order)
    if crew and code in crew:
        return 1.0
    return 0.0


_URGENT_PRIORITIES = {"P1_CRITICAL", "P2_HIGH", "HIGH", "CRITICAL"}


def _is_urgent(priority: str | None) -> bool:
    """The complaint's priority bucket/signal counts as urgent."""
    if not priority:
        return False
    return priority.strip().upper() in _URGENT_PRIORITIES


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
    order_department: str | None = None,
    order_ward: str | None = None,
    priority: str | None = None,
    settings: Settings | None = None,
) -> CandidateScore:
    """Score a single worker. Never random — fully deterministic by the formula."""
    s = settings or get_settings()

    capacity = worker.max_active_orders or s.DISPATCH_MAX_ACTIVE_ORDERS
    available = worker.status == WorkerStatus.ACTIVE and worker.active_orders < capacity
    availability = 1.0 if available else 0.0

    department = _department_match(worker.department_code, order_department)
    ward = (
        1.0
        if order_ward and worker.ward_code and worker.ward_code.upper() == order_ward.upper()
        else 0.0
    )
    urgent = _is_urgent(priority)
    urgency = 1.0 if urgent else 0.5

    # Urgent orders value "get there now": shift a little weight from workload
    # onto distance so the nearest available skilled worker is preferred.
    distance_w = s.DISPATCH_WEIGHT_DISTANCE + (s.DISPATCH_PRIORITY_URGENCY_BOOST if urgent else 0.0)
    workload_w = max(
        0.01, s.DISPATCH_WEIGHT_WORKLOAD - (s.DISPATCH_PRIORITY_URGENCY_BOOST if urgent else 0.0)
    )

    total_w = (
        s.DISPATCH_WEIGHT_AVAILABILITY
        + s.DISPATCH_WEIGHT_SKILL
        + distance_w
        + workload_w
        + s.DISPATCH_WEIGHT_EQUIPMENT
        + s.DISPATCH_WEIGHT_DEPARTMENT
        + s.DISPATCH_WEIGHT_WARD
        + s.DISPATCH_WEIGHT_PRIORITY
    )
    if total_w <= 0:
        total_w = 1.0

    skill = _skill_match(worker.specialty, worker.skill_tags, required_skills)
    equipment = _equipment_match(worker.equipment, required_equipment)

    distance_score = 0.0
    distance_km: float | None = None
    if worker.precomputed_distance_km is not None:
        distance_km = worker.precomputed_distance_km
    elif (
        worker.home_lat is not None
        and worker.home_lon is not None
        and order_lat is not None
        and order_lon is not None
    ):
        distance_km = haversine_km(worker.home_lat, worker.home_lon, order_lat, order_lon)
    if distance_km is not None:
        ref = s.DISPATCH_DISTANCE_REF_KILOMETERS or 1.0
        distance_score = max(0.0, 1.0 - distance_km / ref)

    workload = _workload_fraction(worker.active_orders, capacity)

    score = (
        s.DISPATCH_WEIGHT_AVAILABILITY * availability
        + s.DISPATCH_WEIGHT_SKILL * skill
        + distance_w * distance_score
        + workload_w * workload
        + s.DISPATCH_WEIGHT_EQUIPMENT * equipment
        + s.DISPATCH_WEIGHT_DEPARTMENT * department
        + s.DISPATCH_WEIGHT_WARD * ward
        + s.DISPATCH_WEIGHT_PRIORITY * urgency
    ) / total_w
    score = round(max(0.0, min(1.0, score)), 4)

    reasons: list[str] = []
    if not available:
        reasons.append("busy or unavailable")
    if department < 1.0 and order_department:
        reasons.append("different department")
    if order_ward and (not worker.ward_code or worker.ward_code.upper() != order_ward.upper()):
        reasons.append("different ward")
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
        department=round(department, 4),
        ward=round(ward, 4),
        priority=round(urgency, 4),
        distance_km=round(distance_km, 2) if distance_km is not None else None,
        department_code=worker.department_code,
        ward_code=worker.ward_code,
        active_orders=worker.active_orders,
        capacity=capacity,
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
    order_ward: str | None = None,
    priority: str | None = None,
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
            order_department=department,
            order_ward=order_ward,
            priority=priority,
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
