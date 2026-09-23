"""Deterministic Priority & Risk scoring engine (Part 12, rebuilt).

The engine maps *real* context data onto a single 0..100 score and a
``DynamicPriority`` bucket. It is pure, dependency-free and fully deterministic
— there is NO LLM involvement in the numeric score or the bucket.

Component maxima (configurable via ``PRIORITY_WEIGHT_*``, defaults sum to 100)::

    Severity / potential harm         25
    Infrastructure exposure           30
    Affected population & area        15
    Recurrence / incident pattern     10
    Weather / environmental risk      10
    Evidence confidence               10
                                     ----
                                     100

Scoring model
-------------
Each component is normalized to a dimensionless 0..1 ``unit`` via a fixed,
piecewise mapping over its *real* inputs, then scored as points:

    component_score = round(unit * max_points)

The BASE final score is the plain sum of the scored components, clamped to
0..100. Deterministic **risk amplifiers** — never guessed — may then add a few
capped points when their real evidence triggers are met (e.g. flooding category
plus rain in the forecast); the amplified score is again clamped 0..100, so
nothing can push a score out of range.

The engine NEVER re-normalizes over the present factors. A component whose data
could not be resolved (``DATA_UNAVAILABLE`` / ``INSUFFICIENT_DATA``) carries
``score=None``, contributes 0 and is reported honestly — an unknown nearby never
scores as "no infrastructure" and missing data never inflates the rest. Each
component output carries its ``status``, ``source`` and ``calculated_at`` so the
API/UI can always explain where a number (or the lack of one) came from.

Component internals (calibration v3 + evidence/infra/severity recalibration):

* **Severity / harm** — a five-part 25-point model. The stored triage severity
  label (``complaint.priority``) supplies ONLY the BASE sub-score (LOW 3/10,
  MEDIUM 6/10, HIGH 9/10, CRITICAL 10/10 of its 10). The other four sub-scores
  are deterministic and evidence-backed escalators, each capped at ITS OWN max:
  Safety/Harm 5 (inherent category hazard + verified emergency-access and
  people-exposure + real rain for wet categories + corroborating reports),
  Public Accessibility 3 (access-affecting category with a verified
  emergency/people facility in range), Critical Infrastructure Impact 4 (text-
  names-a-facility or category-relevant registry facility, distance-decayed) and
  Environmental/Weather 3 (real current/recent/forecast precipitation scaled by
  the category). The AI triage is therefore the BASE, never a cap: a MEDIUM with
  verified critical context CAN reach the top of the 25 points, and an empty
  context adds nothing (bare MEDIUM stays 6/10 + inherent hazard only).
* **Infrastructure exposure** — scored two ways, never fabricated. When the
  complaint text EXPLICITLY names a facility (hospital / school / police / fire /
  transit / …) AND the registry VERIFIES a facility of that type within the
  configured search radius AND the complaint category is relevant to that
  facility, the component scores its FULL 30/30 (with the matched record,
  distance, relationship, relationship confidence and access impact reported).
  Otherwise it scores contextually: per facility ``base relevance * complaint-
  category factor * distance-decay`` with four decay bands 0-50 / 50-100 /
  100-250 / 250-500 m (inside-band weights 1.0 / 0.9 / 0.6 / 0.35). The unit
  blends the strongest single facility (``peak``), the saturated cluster of ALL
  nearby facilities (``cluster``) and — only for access-affecting categories an
  emergency facility genuinely ≤50 m/≤100 m away — a real access-impact bonus
  (0.28/0.18). The relevance rulebook is *category-aware*: a hospital matters
  more for a road-obstruction complaint than a park does for a streetlight. An
  explicit mention with NO verified match is reported honestly
  (``matched_facility_id = null``) and never earns the 30/30 rule.
* **Affected population & area** — four real sub-signals:
  ``population_exposure`` (always ``DATA_UNAVAILABLE`` unless a real density grid
  is wired), ``report_pressure`` (real complaint counts 250/500/1000 m x 7d/30d,
  unique reporters, unresolved), ``geographic_spread`` (real PostGIS spread) and
  ``sensitive_facility_exposure`` (distance-decayed real registry facilities).
  Sub-signals are re-normalized over what is genuinely AVAILABLE: an unavailable
  population grid is reported honestly and NEVER treated as "low population".
* **Recurrence** — real same-category 7d/30d counts (deduped).
* **Weather** — real Open-Meteo current + RECENT (trailing days) + forecast
  precipitation plus the forecast precipitation-probability, combined into a
  banded 0..1 unit (band /10 = ``round(unit*10)``: 0-2 none, 3-4 minor, 5-7
  moderate, 8-9 strong, 10 severe) and scaled by the complaint category. A dry
  streetlight complaint is ~0; a drainage complaint with a meaningful forecast
  RISES above the old "auto 1/10"; full risk needs real measured/forecast rain.
* **Evidence confidence** — the strongest *validated AI* verification confidence
  (vision/triage ``structured_result.confidence``, 0..1) maps 1:1 onto the unit
  (98 % → 0.98 → 10/10, 90 % → 9, 80 % → 8, 70 % → 7); the non-AI signals (GPS,
  description, media, structured category, corroborating reports) are blended
  but capped at 0.85 so weak evidence NEVER drags a verified AI result down.
  Separately scored from severity: strong evidence means *the classification is
  trustworthy*, not that the issue is more harmful.

Time is NOT a component. The length of time a complaint has been open is tracked
and surfaced by the SEPARATE SLA engine (``sla_policy`` rulebook → due date →
ON_TRACK / AT_RISK / BREACHED), and a breached SLA never raises the risk score.

Bucket thresholds (configurable via ``PRIORITY_THRESHOLD_P*``):

    [80, 100] -> P1_CRITICAL
    [60,  80) -> P2_HIGH
    [40,  60) -> P3_MEDIUM
    [ 0,  40) -> P4_LOW

The engine exposes the component-*input* dataclasses (populated by the data
collector in ``app.services.priority_data_service``) and the pure
``score_priority()`` entry point (used by ``PriorityAgent``), plus lower level
helpers exported for deterministic unit testing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.models.enums import DynamicPriority, PriorityReadiness

# Severity label -> numeric base unit (the complaint's stored severity, set by
# the triage agent). This is ONLY the BASE of the five-part severity model: it is
# the HARM baseline (0..1, scaled against the 10 base points), never a ceiling —
# the other four parts (safety / accessibility / critical-infrastructure /
# environmental) escalate from it with their own capped maxima.
_SEVERITY_BASE_UNITS: dict[str, float] = {
    "LOW": 0.30,
    "MEDIUM": 0.60,
    "HIGH": 0.90,
    "CRITICAL": 1.00,
}
_DEFAULT_SEVERITY_BASE: float = 0.30

# Weather conditions treated as risk-raising (rain / thunder / fog / snow).
_RAINY_CONDITIONS = frozenset(
    {
        "Light rain",
        "Moderate rain",
        "Heavy rain",
        "Light freezing rain",
        "Heavy freezing rain",
        "Slight rain showers",
        "Moderate rain showers",
        "Violent rain showers",
        "Thunderstorm",
        "Thunderstorm with slight hail",
        "Thunderstorm with heavy hail",
        "Drizzle",
        "Light drizzle",
        "Moderate drizzle",
        "Dense drizzle",
        "Fog",
        "Depositing rime fog",
        "Light snow",
        "Moderate snow",
        "Heavy snow",
    }
)

# How strongly weather risk matters per complaint category. Drainage / flooding /
# water genuinely worsen in rain; garbage barely changes; street lighting barely
# changes at all (near-zero).
_WEATHER_CATEGORY_MULTIPLIERS: dict[str, float] = {
    "FLOODING": 1.6,
    "DRAINAGE": 1.6,
    "WATER_LEAK": 1.2,
    "WATER": 1.0,
    "ROAD": 1.0,
    "FALLEN_TREE": 1.0,
    "SANITATION": 0.8,
    "PUBLIC_SAFETY": 0.7,
    "ELECTRICITY": 0.6,
    "GARBAGE": 0.5,
    "PARKS": 0.4,
    "OTHER": 0.4,
    "STREET_LIGHTING": 0.15,
}

# Rainfall -> weighted "weather severity" signal curve (mm -> 0..1, applied to
# current / recent / forecast precipitation before the category multiplier).
# Calibrated so the component's /10 bands land sensibly: 0 mm -> 0 (truly none),
# ~1 mm light rain -> ~2/10 pre-category, 5 mm (the configured threshold) is the
# 0.5 midpoint, 8 mm light rain -> 0.6, 40 mm heavy rain -> 1.0 (saturates).
_RAIN_MM_SIGNAL: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (1.0, 0.25),
    (5.0, 0.5),
    (8.0, 0.6),
    (20.0, 0.85),
    (40.0, 1.0),
)

# Weather-risk bands for the /10 component score (band = round(unit * 10)).
_WEATHER_BANDS: tuple[tuple[int, str], ...] = (
    (2, "none"),
    (4, "minor"),
    (7, "moderate"),
    (9, "strong"),
    (10, "severe"),
)

# --------------------------------------------------------------------------- #
# Explicit-facility detection (complaint text -> normalized facility category)
# --------------------------------------------------------------------------- #
# Deterministic phrase aliases -> facility category, so "near hospital",
# "near a medical college hospital", "near a health centre" and "clinic" all
# normalize to HOSPITAL. Detection is keyword-shape matching on the lowercased
# complaint text — never an LLM, never a fabricated facility.
_EXPLICIT_FACILITY_ALIASES: dict[str, tuple[str, ...]] = {
    "HOSPITAL": (
        "hospital",
        "hospitals",
        "medical college hospital",
        "medical centre",
        "medical center",
        "health centre",
        "health center",
        "healthcare centre",
        "healthcare center",
        "clinic",
        "clinics",
        "nursing home",
        "dispensary",
        "primary health",
        "phc ",
    ),
    "SCHOOL": (
        "school",
        "schools",
        "college",
        "colleges",
        "university",
        "vidyalaya",
        "gram vidyalaya",
        "madrasa",
        "playschool",
        "play school",
        "kindergarten",
        " tuition",
    ),
    "POLICE_STATION": (
        "police station",
        "police chowky",
        "police chowki",
        "police thana",
        "thana",
    ),
    "FIRE_STATION": (
        "fire station",
        "fire brigade",
        "fire department",
        "fire service",
    ),
    "BUS_STOP": (
        "bus stop",
        "bus stops",
        "bus stand",
        "bus depot",
        "bus terminal",
        "bus bay",
    ),
    "TRANSPORT": (
        "railway station",
        "train station",
        "metro station",
        "rail station",
        "subway station",
    ),
    "GOVERNMENT_BUILDING": (
        "municipal office",
        "collectorate",
        "gram panchayat",
        "sarkari office",
        "government office",
        "govt office",
        "talathi office",
        "zilla parishad",
        "tehsildar office",
    ),
    "PUBLIC_FACILITY": (
        "community hall",
        "public library",
        "library",
        "market",
        "gymnasium",
        "stadium",
        "auditorium",
        "park",
        "garden",
        "playground",
        "temple",
        "masjid",
        "church",
    ),
}

# Complaint categories for which a matched facility type is "relevant" for the
# 30/30 explicit-mention rule. Relevance = the facility genuinely matters for the
# category (either the category is access-affecting, or the category-aware
# rulebook raises that facility's factor >= 1.0 for the category, or the pair is
# explicitly listed). Anything else scores contextually, never auto-30.
_SCORE30_RELEVANT_FACILITIES: dict[str, frozenset[str]] = {
    "ROAD": frozenset(
        {"HOSPITAL", "SCHOOL", "FIRE_STATION", "POLICE_STATION", "TRANSPORT", "BUS_STOP"}
    ),
    "FLOODING": frozenset(
        {"HOSPITAL", "FIRE_STATION", "SCHOOL", "POLICE_STATION", "TRANSPORT", "BUS_STOP"}
    ),
    "DRAINAGE": frozenset({"HOSPITAL", "FIRE_STATION", "SCHOOL", "POLICE_STATION"}),
    "SANITATION": frozenset({"HOSPITAL", "SCHOOL", "BUS_STOP", "TRANSPORT"}),
    "GARBAGE": frozenset({"HOSPITAL", "SCHOOL", "BUS_STOP", "TRANSPORT"}),
    "WATER_LEAK": frozenset({"HOSPITAL", "SCHOOL", "FIRE_STATION"}),
    "WATER": frozenset({"HOSPITAL", "SCHOOL"}),
    "PUBLIC_SAFETY": frozenset({"HOSPITAL", "SCHOOL", "POLICE_STATION", "TRANSPORT", "BUS_STOP"}),
    "STREET_LIGHTING": frozenset({"SCHOOL", "HOSPITAL", "TRANSPORT", "BUS_STOP", "POLICE_STATION"}),
    "ELECTRICITY": frozenset({"HOSPITAL", "FIRE_STATION", "SCHOOL"}),
    "FALLEN_TREE": frozenset({"HOSPITAL", "FIRE_STATION", "POLICE_STATION", "SCHOOL"}),
    "PARKS": frozenset({"SCHOOL", "BUS_STOP", "HOSPITAL"}),
}

# --------------------------------------------------------------------------- #
# Category-aware infrastructure relevance rulebook (calibration v3)
# --------------------------------------------------------------------------- #
# Base relevance of each *facility type* — how much an incident right next to
# that facility matters, all else equal. Hospital adjacency is the strongest
# signal; neutral/generic facilities the weakest. These are BASELINE weights:
# the effective relevance is ``base * category_factor``, and the complaint's
# category only ever RAISES relevance for facilities that genuinely matter for
# that category (the factor for an unrelated facility stays 1.0).
_FACILITY_BASE_RELEVANCE: dict[str, float] = {
    "HOSPITAL": 0.90,
    "FIRE_STATION": 0.85,
    "SCHOOL": 0.75,
    "POLICE_STATION": 0.70,
    "TRANSPORT": 0.50,
    "BUS_STOP": 0.45,
    "ROAD": 0.50,
    "PUBLIC_FACILITY": 0.30,
    "GOVERNMENT_BUILDING": 0.25,
    "OTHER": 0.10,
}

# Complaint-category-aware relevance factors. ``1.0`` means the category does
# not change that facility's relevance; values above 1.0 raise it. The rulebook
# follows the documented calibration guidance:
#   HOSPITAL: very high for access/obstruction/public-safety/road/flooding/
#             drainage/water; high for streetlighting (patients/visitors).
#   SCHOOL:   high for road, garbage, drainage, lighting, public safety.
#   FIRE:     very high for road, flooding, drainage, electricity, trees.
#   POLICE:   high for road obstruction, public safety, fallen tree.
#   BUS/TRANSPORT: moderate-high for road, lighting, garbage, public safety.
_CATEGORY_FACILITY_FACTORS: dict[str, dict[str, float]] = {
    "ROAD": {
        "HOSPITAL": 1.1,
        "SCHOOL": 1.1,
        "FIRE_STATION": 1.15,
        "POLICE_STATION": 1.2,
        "TRANSPORT": 1.2,
        "BUS_STOP": 1.2,
        "PUBLIC_FACILITY": 1.0,
        "GOVERNMENT_BUILDING": 1.0,
    },
    "FLOODING": {
        "HOSPITAL": 1.1,
        "FIRE_STATION": 1.2,
        "SCHOOL": 1.1,
        "POLICE_STATION": 1.0,
        "TRANSPORT": 0.9,
        "BUS_STOP": 0.9,
    },
    "DRAINAGE": {
        "HOSPITAL": 1.1,
        "FIRE_STATION": 1.15,
        "SCHOOL": 1.1,
        "POLICE_STATION": 1.0,
    },
    "SANITATION": {
        "HOSPITAL": 1.15,
        "SCHOOL": 1.15,
        "BUS_STOP": 1.1,
        "TRANSPORT": 1.0,
    },
    "GARBAGE": {
        "HOSPITAL": 1.2,
        "SCHOOL": 1.2,
        "BUS_STOP": 1.1,
        "TRANSPORT": 1.0,
    },
    "WATER_LEAK": {
        "HOSPITAL": 1.15,
        "SCHOOL": 1.1,
        "FIRE_STATION": 1.1,
    },
    "WATER": {
        "HOSPITAL": 1.05,
        "SCHOOL": 1.0,
    },
    "PUBLIC_SAFETY": {
        "HOSPITAL": 1.2,
        "SCHOOL": 1.15,
        "POLICE_STATION": 1.2,
        "TRANSPORT": 1.2,
        "BUS_STOP": 1.2,
    },
    "STREET_LIGHTING": {
        "SCHOOL": 1.3,
        "HOSPITAL": 1.1,
        "TRANSPORT": 1.2,
        "BUS_STOP": 1.3,
        "POLICE_STATION": 1.0,
    },
    "ELECTRICITY": {
        "HOSPITAL": 1.1,
        "FIRE_STATION": 1.2,
        "SCHOOL": 1.0,
    },
    "FALLEN_TREE": {
        "HOSPITAL": 1.1,
        "FIRE_STATION": 1.2,
        "POLICE_STATION": 1.1,
        "SCHOOL": 1.0,
    },
    "PARKS": {
        "HOSPITAL": 1.0,
        "SCHOOL": 1.1,
        "BUS_STOP": 1.1,
    },
}

# Complaint categories where a nearby EMERGENCY facility can be genuinely
# impacted (access blocked / services interrupted). EMERGENCY_ACCESS_RISK and the
# Infrastructure Access Impact signal only fire for these categories + real
# proximity — never for an unrelated category.
_ACCESS_AFFECTING_CATEGORIES = frozenset(
    {
        "ROAD",
        "FLOODING",
        "DRAINAGE",
        "FALLEN_TREE",
        "WATER_LEAK",
        "SANITATION",
        "PUBLIC_SAFETY",
        "GARBAGE",
    }
)

# Complaint categories with a real pedestrian/public-safety angle (used to weight
# the SAFETY severity dimension and the PUBLIC_SAFETY_RISK amplifier).
_PUBLIC_AFFECTING_CATEGORIES = frozenset(
    {
        "ROAD",
        "STREET_LIGHTING",
        "DRAINAGE",
        "FLOODING",
        "PUBLIC_SAFETY",
        "ELECTRICITY",
        "FALLEN_TREE",
        "SANITATION",
        "GARBAGE",
    }
)

# Facility categories that expose *people* to an incident (school, hospital,
# transit, emergency) — used by the SAFETY severity dimension and the
# PUBLIC_SAFETY_RISK amplifier.
_PUBLIC_SAFETY_FACILITY_CATEGORIES = frozenset(
    {"SCHOOL", "HOSPITAL", "TRANSPORT", "BUS_STOP", "PUBLIC_FACILITY"}
)

# Facility categories that count toward the sensitive-facility exposure of the
# affected-area component (real registry; decayed by distance, never invented).
_SENSITIVE_FACILITY_CATEGORIES = frozenset(
    {"HOSPITAL", "SCHOOL", "FIRE_STATION", "POLICE_STATION", "TRANSPORT", "BUS_STOP"}
)

# Facility categories acutely affected by an access-blocking incident
# (EMERGENCY_ACCESS_RISK amplifier + Accessibility severity dimension).
_EMERGENCY_CATEGORIES = frozenset({"HOSPITAL", "FIRE_STATION", "POLICE_STATION"})

# Public-safety complaint categories for the PUBLIC_SAFETY_RISK amplifier.
_PUBLIC_SAFETY_COMPLAINT_CATEGORIES = frozenset(
    {"PUBLIC_SAFETY", "ELECTRICITY", "FALLEN_TREE", "ROAD", "DRAINAGE", "FLOODING"}
)

_FLOODING_CATEGORIES = frozenset({"FLOODING", "DRAINAGE", "WATER_LEAK", "SANITATION"})

# Sub-signal weights of the affected-population component (sum = 1.0). When a
# sub-signal is DATA_UNAVAILABLE the remaining AVAILABLE sub-signals are
# re-normalized to the component's max points, so an absent population grid is
# NEVER read as "zero population".
_POPULATION_SUBWEIGHTS: dict[str, float] = {
    "population_exposure": 0.30,
    "report_pressure": 0.25,
    "geographic_spread": 0.10,
    "sensitive_facility_exposure": 0.35,
}

# Severity is a five-part model: fractions of the severity component's max
# points (defaults 10 + 5 + 3 + 4 + 3 = 25). The AI triage label feeds ONLY the
# "base" part; every other part is a deterministic, evidence-gated escalator
# with ITS OWN ceiling — there is NO shared "+0.30" cap any more, so a MEDIUM
# with verified critical context can genuinely reach 25 and a bare MEDIUM cannot
# leave the low range. (Sub-scores are scaled proportionally if the severity
# weight is reconfigured.)
_SEVERITY_BASE_FRACTION: float = 0.40        #   10 / 25
_SEVERITY_SAFETY_FRACTION: float = 0.20      #    5 / 25
_SEVERITY_ACCESSIBILITY_FRACTION: float = 0.12  #  3 / 25
_SEVERITY_CRITICAL_INFRA_FRACTION: float = 0.16 # 4 / 25
_SEVERITY_ENVIRONMENTAL_FRACTION: float = 0.12  # 3 / 25
_SEVERITY_SUB_FRACTIONS: dict[str, float] = {
    "base": _SEVERITY_BASE_FRACTION,
    "safety": _SEVERITY_SAFETY_FRACTION,
    "accessibility": _SEVERITY_ACCESSIBILITY_FRACTION,
    "critical_infrastructure": _SEVERITY_CRITICAL_INFRA_FRACTION,
    "environmental": _SEVERITY_ENVIRONMENTAL_FRACTION,
}
_SEVERITY_SUB_LABELS: dict[str, str] = {
    "base": "Base (AI triage)",
    "safety": "Safety / harm",
    "accessibility": "Public accessibility",
    "critical_infrastructure": "Critical infrastructure impact",
    "environmental": "Environmental / weather",
}

# Inherent category hazard baseline (0..1) used to seed the Safety/Harm
# sub-score. It is multiplied by 0.5 so the category ALONE can never dominate —
# verified signals (emergency access, people exposure, real rain, corroborating
# reports) raise it further.
_CATEGORY_HAZARD: dict[str, float] = {
    "ELECTRICITY": 0.90,
    "PUBLIC_SAFETY": 0.80,
    "FLOODING": 0.85,
    "FALLEN_TREE": 0.75,
    "SANITATION": 0.70,
    "GARBAGE": 0.60,
    "WATER_LEAK": 0.55,
    "WATER": 0.50,
    "DRAINAGE": 0.50,
    "ROAD": 0.45,
    "OTHER": 0.25,
    "STREET_LIGHTING": 0.15,
    "PARKS": 0.10,
}
_CATEGORY_HAZARD_FLOOR: float = 0.20

# Distance tiers (m -> verified emergency-access safety unit) for the Safety
# escalator: an emergency facility genuinely ≤50 m / ≤100 m / ≤150 m away from
# an access-affecting hazard. This is what separates "road obstruction beside a
# police station" (5/5) from "road near hospital" (4/5).
_SAFETY_EMERGENCY_TIERS: tuple[tuple[float, float], ...] = (
    (50.0, 1.00),
    (100.0, 0.80),
    (150.0, 0.60),
)

# Wet-affected complaint categories: REAL precipitation raises Safety/Harm
# (flooding/drainage/water are genuinely more dangerous in rain).
_WET_AFTER_CATEGORIES = frozenset({"FLOODING", "DRAINAGE", "WATER_LEAK", "WATER"})

# Context-escalation gate: a complaint triaged MEDIUM+ ALWAYS gains context;
# a LOW-triage complaint only escalates when the TEXT itself names a facility
# (the reporter is claiming the relationship, the registry must still verify it).
_SEVERITY_MEDIUM_BASE: float = _SEVERITY_BASE_UNITS.get("MEDIUM", 0.60)

# Infrastructure exposure blend weights. The unit is a weighted mix of the
# strongest single facility (peak), the saturated cluster of all nearby
# facilities (cluster) and a real emergency-access bonus — so one very close
# critical facility is strong, and a dense cluster with a genuinely blocked
# emergency route saturates to the component maximum.
_INFRA_PEAK_WEIGHT: float = 0.60
_INFRA_CLUSTER_WEIGHT: float = 0.25
_INFRA_ACCESS_BONUS_50M: float = 0.28
_INFRA_ACCESS_BONUS_100M: float = 0.18

# Cap on the NON-AI evidence blend (GPS/description/media/structured/
# corroborating). A verified AI classification is mapped 1:1 from its confidence
# and this cap keeps weak non-AI signals from ever diluting it.
_NON_AI_EVIDENCE_CAP: float = 0.85


@dataclass(frozen=True)
class Weights:
    """Configurable component max-points (defaults sum to 100).

    These are MAXIMUM points per component, not relative weights: an input's
    normalized unit times its max determines its points, and the final score is
    the plain sum (never re-normalized over present factors).
    """

    severity: float = 25.0
    infrastructure: float = 30.0
    population: float = 10.0
    history: float = 5.0
    weather: float = 10.0
    evidence: float = 20.0

    @property
    def total(self) -> float:
        return sum(
            (
                self.severity,
                self.infrastructure,
                self.population,
                self.history,
                self.weather,
                self.evidence,
            )
        )

    def max_points(self, key: str) -> float:
        return {
            "severity": self.severity,
            "infrastructure": self.infrastructure,
            "population": self.population,
            "historical": self.history,
            "weather": self.weather,
            "evidence": self.evidence,
        }[key]


# --------------------------------------------------------------------------- #
# Component input dataclasses (populated by PriorityDataService collectors)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SeverityInput:
    """The complaint's stored severity label (triage agent's input)."""

    severity: str | None
    status: str = "AVAILABLE"
    source: str = "complaint.priority"
    calculated_at: datetime | None = None
    explanation: str | None = None


@dataclass(frozen=True)
class FacilityInput:
    """One verified (or live-candidate) nearby facility with its real distance."""

    name: str
    category: str
    distance_m: float | None = None
    verification: str = "FOUND"
    # Registry record id (``CriticalLocation.id``) when the facility came from
    # the verified registry; ``None`` for live (unverified) candidates. Used as
    # the explicit-mention component's ``matched_facility_id`` provenance.
    record_id: str | None = None


@dataclass(frozen=True)
class InfrastructureInput:
    """Nearby critical facilities (real registry/PostGIS, metre-exact distances)."""

    facilities: list[FacilityInput] = field(default_factory=list)
    # FOUND / NO_VERIFIED_RECORDS / DATA_UNAVAILABLE / PARTIAL_DATA.
    status: str = "DATA_UNAVAILABLE"
    radius_m: float | None = None
    source: str = "postgis-infrastructure"
    calculated_at: datetime | None = None
    explanation: str | None = None


@dataclass(frozen=True)
class PopulationInput:
    """Affected population & area around the complaint.

    Four independently-reported sub-signals feed this component:

    * report pressure — real PostGIS complaint counts (per radius over 7 d/30 d,
      duplicates excluded), unique reporters and unresolved nearby;
    * geographic spread — how widely those reports are distributed (PostGIS);
    * sensitive-facility exposure — real registry facilities (school/hospital/
      fire/police/transit) with distance-decayed weight;
    * population density — ONLY ever scored against a real resident/grid
      dataset; otherwise ``population`` stays ``None`` and
      ``population_status`` is ``DATA_UNAVAILABLE`` (never fabricated).

    Unavailable sub-signals are reported honestly (``DATA_UNAVAILABLE``) and the
    AVAILABLE sub-signals are re-normalized to the component maximum — an absent
    population grid is never treated as "low population".
    """

    reports_7d: dict[int, int] = field(default_factory=dict)
    reports_30d: dict[int, int] = field(default_factory=dict)
    unique_reporters_7d: int = 0
    unique_reporters_30d: int = 0
    unresolved_reports_7d: int = 0
    unresolved_reports_30d: int = 0
    spread_max_distance_m: float | None = None
    sensitive_facilities_nearby: int = 0
    # Real facilities that expose people to the incident (distance-decayed).
    sensitive_facilities: list[FacilityInput] = field(default_factory=list)
    population: int | None = None
    population_status: str = "DATA_UNAVAILABLE"
    # AVAILABLE / INSUFFICIENT_DATA.
    status: str = "AVAILABLE"
    source: str = "postgis-reports"
    calculated_at: datetime | None = None
    explanation: str | None = None


@dataclass(frozen=True)
class HistoricalInput:
    """Recurrence / incident-pattern counts (same area, same category, 7d/30d)."""

    same_category_nearby_7d: int = 0
    same_category_nearby_30d: int = 0
    nearby_7d: int = 0
    nearby_30d: int = 0
    cluster_250m_30d: int = 0
    ward_30d: int = 0
    unresolved_similar_nearby: int = 0
    # Confirmed duplicates excluded from every count (dedupe, never double-count).
    duplicates_excluded: int = 0
    # AVAILABLE / INSUFFICIENT_DATA.
    status: str = "AVAILABLE"
    source: str = "postgis-historical"
    calculated_at: datetime | None = None
    explanation: str | None = None


@dataclass(frozen=True)
class WeatherInput:
    """Real Open-Meteo current + recent + forecast conditions."""

    condition: str | None = None
    rain_mm: float | None = None
    precipitation_mm: float | None = None
    # Max precipitation_sum over the next-days forecast window.
    forecast_precip_mm: float | None = None
    # Max precipitation_sum over the recent (trailing past-days) window.
    recent_precip_mm: float | None = None
    # Forecast precipitation-probability (%) — the strongest real-signal driver
    # that lifts drainage/flooding risk before rain actually falls.
    precip_probability_pct: float | None = None
    threshold_mm: float = 5.0
    category: str | None = None
    # AVAILABLE / DATA_UNAVAILABLE.
    status: str = "DATA_UNAVAILABLE"
    source: str = "open-meteo"
    calculated_at: datetime | None = None
    explanation: str | None = None


@dataclass(frozen=True)
class EvidenceInput:
    """Evidence-confidence sub-signals for the complaint.

    Every field is a real, measurable signal: whether a verified GPS coordinate
    exists, description substance, attached photos, a structured category, an
    AI triage/vision agreement (with its real confidence) and corroborating
    nearby reports. None of these are invented; when no AI signal exists the
    component reports ``status=PARTIAL`` and scores only the non-AI evidence.
    """

    has_gps: bool = False
    gps_source: str | None = None
    gps_accuracy_m: float | None = None
    description_chars: int = 0
    media_count: int = 0
    category_structured: bool = False
    triage_available: bool = False
    triage_confidence: float | None = None
    vision_available: bool = False
    vision_confidence: float | None = None
    vision_mismatch: bool | None = None
    corroborating_reports_30d: int = 0
    # AVAILABLE / PARTIAL (no AI signal yet) / INSUFFICIENT_DATA.
    status: str = "AVAILABLE"
    source: str = "complaint-evidence"
    calculated_at: datetime | None = None
    explanation: str | None = None


@dataclass
class PriorityDataBundle:
    """All real context collected for one scoring pass."""

    category: str = "OTHER"
    severity: SeverityInput = field(default_factory=SeverityInput)
    infrastructure: InfrastructureInput | None = None
    population: PopulationInput | None = None
    weather: WeatherInput | None = None
    historical: HistoricalInput | None = None
    evidence: EvidenceInput | None = None


# --------------------------------------------------------------------------- #
# Pure 0..1 normalizers (each deterministic, clamps to [0,1])
# --------------------------------------------------------------------------- #
def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def severity_unit(severity: str | None) -> float:
    """:return: 0..1 unit for the stored triage severity label — the BASE of the
    five-part severity model, NEVER a ceiling."""
    if not severity:
        return 0.0
    return _clamp(_SEVERITY_BASE_UNITS.get(severity.upper(), _DEFAULT_SEVERITY_BASE))


def _severity_context_open(base_unit: float, description: str | None) -> bool:
    """:return: True when contextual escalation is authorised.

    A MEDIUM+ triage always opens the context clip (the incident itself is real).
    A LOW-triage complaint only escalates when the complaint TEXT names a
    facility — the reporter claims the relationship, the registry must still
    verify it (``detect_explicit_facility`` -> ``best_facility_match``). This is
    the guard that keeps a "minor pothole" beside a hospital at its bare LOW
    base unless the relationship is genuinely claimed.
    """
    if base_unit >= _SEVERITY_MEDIUM_BASE:
        return True
    return detect_explicit_facility(description) is not None


def _weather_precip_signals(weather: WeatherInput | None) -> float:
    """:return: the strongest REAL precipitation signal (0..1) across current /
    recent / forecast amounts, plus a modest floor for a meaningful forecast
    (rain forecast WITH a high precipitation-probability). 0 when nothing is
    falling/fallen/forecast."""
    if weather is None or weather.status != "AVAILABLE":
        return 0.0
    rain = weather.rain_mm if weather.rain_mm is not None else weather.precipitation_mm
    values = [
        v
        for v in (rain, weather.recent_precip_mm, weather.forecast_precip_mm)
        if v is not None
    ]
    signal = max((_rain_signal_mm(v) for v in values), default=0.0)
    if (
        weather.forecast_precip_mm is not None
        and weather.forecast_precip_mm > 0
        and weather.precip_probability_pct is not None
        and weather.precip_probability_pct >= 60.0
    ):
        signal = max(signal, 0.45)
    return _clamp(signal)


def safety_unit(
    *,
    category: str | None,
    base_unit: float,
    description: str | None,
    infrastructure: InfrastructureInput | None,
    population: PopulationInput | None,
    weather: WeatherInput | None,
) -> float:
    """:return: 0..1 Safety/Harm sub-unit (seeded from the category's inherent
    hazard, raised ONLY by verified signals).

    * inherent category hazard baseline (``0.5 * _CATEGORY_HAZARD``);
    * verified emergency-access harm — an access-affecting category with an
      emergency facility ≤50/≤100/≤150 m (police 10 m → 5/5, hospital 85 m → 4/5)
      — but ONLY when the context clip is open (MEDIUM+ or explicit mention),
      so a minor pothole beside a hospital is never auto-raised;
    * modest people-exposure add for public-affecting categories with a
      school/hospital/transit facility ≤150 m;
    * REAL rain for wet-affected categories (flooding/drainage/water) —
      ``0.4 + 0.6 * precip signal``;
    * corroborating real nearby reports (each adds a small amount).
    """
    cat = (category or "").upper()
    hazard = _CATEGORY_HAZARD.get(cat, _CATEGORY_HAZARD_FLOOR)
    unit = _clamp(0.5 * hazard)

    facilities = list((infrastructure.facilities or ()) if infrastructure is not None else ())
    emergency_unit = 0.0
    if _severity_context_open(base_unit, description):
        if cat in _ACCESS_AFFECTING_CATEGORIES:
            emergency = [
                f
                for f in facilities
                if str(f.category).upper() in _EMERGENCY_CATEGORIES
                and f.distance_m is not None
            ]
            for band, tier_unit in _SAFETY_EMERGENCY_TIERS:
                if any(f.distance_m is not None and f.distance_m <= band for f in emergency):
                    emergency_unit = tier_unit
                    break
        # People-exposure is the weaker signal and only matters when no verified
        # emergency-access tier already applies (never stacked on top of it), so
        # "road near hospital" stays 4/5 and "blocked beside police" is 5/5.
        if emergency_unit == 0 and cat in _PUBLIC_AFFECTING_CATEGORIES:
            exposed = any(
                str(f.category).upper() in _PUBLIC_SAFETY_FACILITY_CATEGORIES
                and f.distance_m is not None
                and f.distance_m <= 150.0
                for f in facilities
            )
            if exposed:
                unit = max(unit, _clamp(unit + 0.15))
    unit = max(unit, emergency_unit)

    if cat in _WET_AFTER_CATEGORIES:
        rain_signal = _weather_precip_signals(weather)
        if rain_signal > 0:
            unit = max(unit, _clamp(0.4 + 0.6 * rain_signal))

    if population is not None and population.status == "AVAILABLE":
        n500 = int(population.reports_7d.get(500, 0)) + int(
            population.reports_7d.get(250, 0)
        )
        unique = int(population.unique_reporters_7d)
        corroboration = _clamp(
            0.05 * min(1.0, n500 / 6.0) + 0.05 * min(1.0, unique / 4.0)
        )
        unit = _clamp(unit + corroboration)
    return _clamp(unit)


def accessibility_unit(
    *,
    category: str | None,
    base_unit: float,
    description: str | None,
    infrastructure: InfrastructureInput | None,
    bands: tuple[float, float, float, float] = (50.0, 100.0, 250.0, 500.0),
    band_factors: tuple[float, float, float, float] = (1.0, 0.9, 0.6, 0.35),
) -> float:
    """:return: 0..1 Public-Accessibility sub-unit for an access-affecting
    category with a VERIFIED emergency/people facility in range.

    Accessibility is proximity-strength (``0.35 + 0.65 * distance-decay``) with a
    0.6 floor when any such facility is within the 500 m band — a road beside a
    hospital 60 m away floors at ~3/3, a garbage pile 450 m from a hospital still
    reads ~2/3, and a LOW complaint that does not name the facility stays 0.
    """
    cat = (category or "").upper()
    if cat not in _ACCESS_AFFECTING_CATEGORIES:
        return 0.0
    if not _severity_context_open(base_unit, description):
        return 0.0
    facilities = list((infrastructure.facilities or ()) if infrastructure is not None else ())
    exposed = [
        f
        for f in facilities
        if str(f.category).upper()
        in (_EMERGENCY_CATEGORIES | _PUBLIC_SAFETY_FACILITY_CATEGORIES)
        and f.distance_m is not None
    ]
    if not exposed:
        return 0.0
    nearest = min(exposed, key=lambda f: f.distance_m)
    decay = distance_band_factor(nearest.distance_m, bands, band_factors)
    unit = _clamp(0.35 + 0.65 * decay)
    if any(f.distance_m is not None and f.distance_m <= bands[-1] for f in exposed):
        unit = max(unit, 0.60)
    return _clamp(unit)


def critical_infra_unit(
    *,
    category: str | None,
    base_unit: float,
    description: str | None,
    infrastructure: InfrastructureInput | None,
    bands: tuple[float, float, float, float] = (50.0, 100.0, 250.0, 500.0),
    band_factors: tuple[float, float, float, float] = (1.0, 0.9, 0.6, 0.35),
) -> float:
    """:return: 0..1 Critical-Infrastructure-Impact sub-unit.

    This is severity's SMALL 4-point slice and is deliberately STRICTER than the
    30-point infrastructure component: only truly critical facilities
    (hospital / fire / police) count. Targets the facility the TEXT explicitly
    names (when the registry VERIFIES it and the pair is category-relevant) OR
    the nearest critical facility relevant to the category, distance-decayed
    (``0.25 + 0.75 * decay``). A road beside a hospital 60 m → 4/4; garbage
    450 m from a hospital → ~2/4 ("lower impact"); a streetlight beside a SCHOOL
    → 0/4 (schools are not critical infrastructure, though the 30-point
    exposure component still reflects them); a LOW complaint that never names
    the facility stays 0. Critical-facility exposure is never double-counted
    with the separate infrastructure component.
    """
    cat = (category or "").upper()
    if not _severity_context_open(base_unit, description):
        return 0.0
    facilities = list((infrastructure.facilities or ()) if infrastructure is not None else ())
    if not facilities:
        return 0.0

    critical = [
        f
        for f in facilities
        if str(f.category).upper() in _EMERGENCY_CATEGORIES
        and f.distance_m is not None
    ]
    explicit = detect_explicit_facility(description)
    matched = best_facility_match(explicit, facilities) if explicit is not None else None
    if (
        matched is not None
        and str(matched.category).upper() in _EMERGENCY_CATEGORIES
        and explicit_facility_relevant(cat, matched.category)
        and distance_band_factor(matched.distance_m, bands, band_factors) > 0
    ):
        target = matched
    else:
        relevant = [
            f
            for f in critical
            if explicit_facility_relevant(cat, f.category)
            and distance_band_factor(f.distance_m, bands, band_factors) > 0
        ]
        if not relevant:
            return 0.0
        target = min(relevant, key=lambda f: f.distance_m)
    decay = distance_band_factor(target.distance_m, bands, band_factors)
    return _clamp(0.25 + 0.75 * decay)


def environmental_unit(
    *,
    category: str | None,
    weather: WeatherInput | None,
) -> float:
    """:return: 0..1 Environmental/Weather sub-unit from REAL precipitation only.

    ``precip signal (current/recent/forecast) * category multiplier`` — drainage
    in heavy rain → 3/3, a dry drainage complaint → 0/3, a road with 8 mm → ~2/3.
    """
    cat = (category or "").upper()
    signal = _weather_precip_signals(weather)
    if signal <= 0:
        return 0.0
    multiplier = _WEATHER_CATEGORY_MULTIPLIERS.get(cat)
    if multiplier is None:
        return 0.0
    return _clamp(signal * multiplier)


def severity_dimensions(
    *,
    severity: str | None,
    category: str | None,
    infrastructure: InfrastructureInput | None,
    population: PopulationInput | None,
    weather: WeatherInput | None,
    complaint_description: str | None = None,
    bands: tuple[float, float, float, float] = (50.0, 100.0, 250.0, 500.0),
    band_factors: tuple[float, float, float, float] = (1.0, 0.9, 0.6, 0.35),
) -> dict[str, float]:
    """Deterministic five-part severity sub-units (each 0..1).

    ``base`` is the AI triage label (never a cap); ``safety``, ``accessibility``,
    ``critical_infrastructure`` and ``environmental`` are evidence-gated
    escalators with their own maxima. Each is bounded and honest: empty context
    leaves the base untouched.
    """
    base = severity_unit(severity)
    return {
        "base": base,
        "safety": safety_unit(
            category=category,
            base_unit=base,
            description=complaint_description,
            infrastructure=infrastructure,
            population=population,
            weather=weather,
        ),
        "accessibility": accessibility_unit(
            category=category,
            base_unit=base,
            description=complaint_description,
            infrastructure=infrastructure,
            bands=bands,
            band_factors=band_factors,
        ),
        "critical_infrastructure": critical_infra_unit(
            category=category,
            base_unit=base,
            description=complaint_description,
            infrastructure=infrastructure,
            bands=bands,
            band_factors=band_factors,
        ),
        "environmental": environmental_unit(category=category, weather=weather),
    }


def distance_band_factor(
    distance_m: float | None,
    bands: tuple[float, ...] = (50.0, 100.0, 250.0, 500.0),
    band_factors: tuple[float, ...] = (1.0, 0.9, 0.6, 0.35),
) -> float:
    """:return: 0..1 distance-decay factor for a facility at ``distance_m``.

    Fully weighted inside band 1, ``band_factors[i]`` in band ``i+1`` and 0
    beyond the last band. ``bands`` and ``band_factors`` must be same length
    (default calibration: 0-50 / 50-100 / 100-250 / 250-500 m at 1.0 / 0.9 /
    0.6 / 0.35). A facility with no resolvable distance contributes nothing (its
    proximity cannot be claimed).
    """
    if distance_m is None or not math.isfinite(distance_m) or distance_m < 0:
        return 0.0
    for index, upper in enumerate(bands):
        if distance_m <= upper:
            factor = band_factors[index] if index < len(band_factors) else 0.0
            return float(factor) if factor is not None else 0.0
    return 0.0


def detect_explicit_facility(text: str | None) -> str | None:
    """Detect an explicitly-named facility category in complaint text.

    Deterministic alias matching over the lowercased text (``_EXPLICIT_FACILITY_ALIASES``):
    "Road is broken near hospital" -> ``HOSPITAL``. Returns ``None`` when no
    facility is named — the 30/30 explicit rule then never fires and the
    component scores contextually. Never invents a facility.
    """
    if not text:
        return None
    lowered = f" {text.lower()} "
    found: list[tuple[str, int]] = []
    for category, aliases in _EXPLICIT_FACILITY_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                found.append((category, len(alias)))
    if not found:
        return None
    # Longest alias wins ("medical college hospital" beats bare "hospital").
    found.sort(key=lambda item: item[1], reverse=True)
    return found[0][0]


def best_facility_match(
    category: str | None, facilities: list[FacilityInput]
) -> FacilityInput | None:
    """:return: the nearest VERIFIED facility whose type matches ``category``.

    Only registry-verified facilities (``FOUND``/``VERIFIED``) are eligible —
    a live PENDING candidate is never claimed as the explicit-mention match.
    """
    if not category:
        return None
    matches = [
        f
        for f in (facilities or ())
        if str(f.category).upper() == str(category).upper()
        and str(f.verification).upper() in {"FOUND", "VERIFIED"}
        and f.distance_m is not None
    ]
    if not matches:
        return None
    return min(matches, key=lambda f: f.distance_m)


def explicit_facility_relevant(category: str | None, facility_category: str | None) -> bool:
    """:return: True when a matched facility type is relevant for the complaint
    category under the 30/30 explicit-mention rule (deterministic rulebook).

    Access-affecting categories are relevant for any emergency/people-exposing
    facility; otherwise the pair must be listed in ``_SCORE30_RELEVANT_FACILITIES``.
    An unknown category is never auto-relevant.
    """
    ftype = str(facility_category or "").upper()
    cat = (category or "").upper()
    if not ftype:
        return False
    if cat in _ACCESS_AFFECTING_CATEGORIES and ftype in {
        "HOSPITAL",
        "FIRE_STATION",
        "POLICE_STATION",
        "SCHOOL",
        "TRANSPORT",
        "BUS_STOP",
    }:
        return True
    return ftype in _SCORE30_RELEVANT_FACILITIES.get(cat, frozenset())


def facility_relevance(
    facility: FacilityInput,
    category: str | None,
    base_relevance: dict[str, float] | None = None,
    category_factors: dict[str, dict[str, float]] | None = None,
) -> float:
    """Category-aware relevance of a facility for a complaint category.

    :return: ``base_relevance[type] * category_factor[category][type]`` (capped
        at 1.5). An unrelated category keeps factor 1.0 — the matrix only raises
        relevance where the facility genuinely matters, never the reverse.
    """
    weights = base_relevance if base_relevance is not None else _FACILITY_BASE_RELEVANCE
    factors = (
        category_factors if category_factors is not None else _CATEGORY_FACILITY_FACTORS
    )
    ftype = str(facility.category).upper()
    base = weights.get(ftype, weights.get(facility.category, 0.10))
    factor = (factors.get((category or "").upper()) or {}).get(ftype, 1.0)
    return min(1.5, base * factor)


def facility_contribution(
    facility: FacilityInput,
    category: str | None = None,
    base_relevance: dict[str, float] | None = None,
    category_factors: dict[str, dict[str, float]] | None = None,
    bands: tuple[float, ...] = (50.0, 100.0, 250.0, 500.0),
    band_factors: tuple[float, ...] = (1.0, 0.9, 0.6, 0.35),
) -> float:
    """TYPE x CATEGORY x DISTANCE contribution of one facility (dimensionless)."""
    relevance = facility_relevance(facility, category, base_relevance, category_factors)
    return relevance * distance_band_factor(facility.distance_m, bands, band_factors)


def _infra_access_bonus(
    facilities: list[FacilityInput],
    category: str | None,
    *,
    bonus_50m: float = _INFRA_ACCESS_BONUS_50M,
    bonus_100m: float = _INFRA_ACCESS_BONUS_100M,
) -> float:
    """Access-impact bonus for an emergency facility genuinely very close.

    Only applied when the complaint category is access-affecting AND an
    emergency facility (hospital/fire/police) is ≤50 m (``bonus_50m``) or
    ≤100 m (``bonus_100m``) away — the documented "road beside a police
    station / hospital" condition. No category match → no bonus.
    """
    if (category or "").upper() not in _ACCESS_AFFECTING_CATEGORIES:
        return 0.0
    emergency = [
        f
        for f in (facilities or ())
        if str(f.category).upper() in _EMERGENCY_CATEGORIES and f.distance_m is not None
    ]
    if any(f.distance_m is not None and f.distance_m <= 50.0 for f in emergency):
        return float(bonus_50m)
    if any(f.distance_m is not None and f.distance_m <= 100.0 for f in emergency):
        return float(bonus_100m)
    return 0.0


def infrastructure_unit(
    facilities: list[FacilityInput],
    category: str | None = None,
    base_relevance: dict[str, float] | None = None,
    category_factors: dict[str, dict[str, float]] | None = None,
    bands: tuple[float, ...] = (50.0, 100.0, 250.0, 500.0),
    band_factors: tuple[float, ...] = (1.0, 0.9, 0.6, 0.35),
    saturation: float = 2.2,
    peak_weight: float = _INFRA_PEAK_WEIGHT,
    cluster_weight: float = _INFRA_CLUSTER_WEIGHT,
    access_bonus_50m: float = _INFRA_ACCESS_BONUS_50M,
    access_bonus_100m: float = _INFRA_ACCESS_BONUS_100M,
) -> float:
    """:return: 0..1 proximity unit from the distance-decayed facility scores.

    The unit blends three real signals: the strongest single facility (``peak``,
    ``peak_weight``), the saturated sum of ALL contributions (``cluster``,
    ``cluster_weight``, diminishing returns past ``saturation``) and the
    category-gated emergency-access bonus. So a police station 10 m away is
    strong, a dense cluster of critical facilities is stronger, and a genuinely
    blocked emergency route pushes the component toward its maximum.
    """
    contributions = [
        facility_contribution(
            f,
            category,
            base_relevance,
            category_factors,
            bands,
            band_factors,
        )
        for f in (facilities or ())
    ]
    if not contributions or any(
        not math.isfinite(float(c)) for c in contributions
    ):
        return 0.0
    peak = max(0.0, max(contributions))
    total = sum(contributions)
    cluster_unit = (
        1.0 - math.exp(-total / float(saturation))
        if total > 0 and saturation > 0
        else 0.0
    )
    bonus = _infra_access_bonus(
        facilities or (), category, bonus_50m=access_bonus_50m, bonus_100m=access_bonus_100m
    )
    return _clamp(peak_weight * min(1.0, peak) + cluster_weight * cluster_unit + bonus)


def sensitive_exposure_unit(
    facilities: list[FacilityInput],
    sensitive_categories: frozenset[str] | None = None,
    bands: tuple[float, ...] = (50.0, 100.0, 250.0, 500.0),
    band_factors: tuple[float, ...] = (1.0, 0.9, 0.6, 0.35),
    saturation: float = 2.0,
) -> float:
    """:return: 0..1 affected-people exposure from REAL sensitive facilities.

    Sensitive infrastructure (schools, hospitals, fire/police, transit) exposes
    real people to an incident even when a population grid or report volume is
    unavailable. Contributions decay by distance and saturate, so a single
    facility far away never dominates and a hospital 55 m away is strong — but
    never a guaranteed maximum.
    """
    cats = (
        sensitive_categories if sensitive_categories is not None else _SENSITIVE_FACILITY_CATEGORIES
    )
    total = sum(
        distance_band_factor(f.distance_m, bands, band_factors)
        for f in (facilities or ())
        if str(f.category).upper() in cats
    )
    if total <= 0 or saturation <= 0:
        return 0.0
    return _clamp(1.0 - math.exp(-total / float(saturation)))


def population_subunits(
    c: PopulationInput,
    subweights: dict[str, float] | None = None,
) -> list[tuple[str, float | None, float]]:
    """:return: ``[(sub_key, unit_or_None, weight), ...]`` for each real sub-signal.

    A ``None`` unit marks a sub-signal that is DATA_UNAVAILABLE (population grid
    absent) — it is reported but does NOT contribute. The remaining AVAILABLE
    sub-signals are re-normalized to the component maximum by ``population_unit``.
    """
    weights = subweights if subweights is not None else _POPULATION_SUBWEIGHTS
    w_pop = float(weights.get("population_exposure", 0.30))
    w_report = float(weights.get("report_pressure", 0.25))
    w_spread = float(weights.get("geographic_spread", 0.10))
    w_sensitive = float(weights.get("sensitive_facility_exposure", 0.35))

    out: list[tuple[str, float | None, float]] = []
    if c.population is not None and c.population > 0 and c.population_status == "AVAILABLE":
        out.append(
            ("population_exposure", _clamp(min(1.0, c.population / 150_000.0)), w_pop)
        )
    else:
        out.append(("population_exposure", None, w_pop))

    n250 = int(c.reports_7d.get(250, 0))
    n500 = int(c.reports_7d.get(500, 0))
    n1000 = int(c.reports_7d.get(1000, 0))
    n500_30d = int(c.reports_30d.get(500, 0))
    n1000_30d = int(c.reports_30d.get(1000, 0))
    report_unit = _clamp(
        0.30 * min(1.0, n500 / 8.0)
        + 0.20 * min(1.0, n250 / 4.0)
        + 0.10 * min(1.0, n1000 / 20.0)
        + 0.10 * min(1.0, n500_30d / 20.0)
        + 0.05 * min(1.0, n1000_30d / 40.0)
        + 0.10 * min(1.0, c.unique_reporters_7d / 4.0)
        + 0.05 * min(1.0, c.unique_reporters_30d / 10.0)
        + 0.10 * min(1.0, c.unresolved_reports_7d / 6.0)
        + 0.05 * min(1.0, c.unresolved_reports_30d / 12.0)
    )
    out.append(("report_pressure", report_unit, w_report))

    spread_unit = (
        _clamp((c.spread_max_distance_m or 0.0) / 1000.0)
        if c.spread_max_distance_m is not None
        else 0.0
    )
    out.append(("geographic_spread", spread_unit, w_spread))

    sensitive_unit = sensitive_exposure_unit(c.sensitive_facilities or ())
    out.append(("sensitive_facility_exposure", sensitive_unit, w_sensitive))
    return out


def population_unit(
    c: PopulationInput,
    subweights: dict[str, float] | None = None,
) -> float:
    """:return: 0..1 affected-area unit, re-normalized over AVAILABLE sub-signals.

    An unavailable population grid does NOT zero the component: the weighted
    sum of the genuinely-available sub-signals (report pressure, spread,
    sensitive facilities) is divided by the available weight, so data absence is
    reported honestly while the real signals still count.
    """
    if c.status != "AVAILABLE":
        return 0.0
    subs = [(k, u, w) for k, u, w in population_subunits(c, subweights) if u is not None]
    total_weight = sum(w for _, _, w in subs)
    if total_weight <= 0:
        return 0.0
    return _clamp(sum(u * w for _, u, w in subs) / total_weight)


def historical_unit(h: HistoricalInput) -> float:
    """:return: 0..1 recurrence unit from the real 7 d / 30 d counts."""
    if h.status != "AVAILABLE":
        return 0.0
    return _clamp(
        0.25 * min(1.0, h.same_category_nearby_30d / 10.0)
        + 0.20 * min(1.0, h.same_category_nearby_7d / 5.0)
        + 0.15 * min(1.0, h.cluster_250m_30d / 6.0)
        + 0.10 * min(1.0, h.ward_30d / 40.0)
        + 0.15 * min(1.0, h.nearby_30d / 20.0)
        + 0.15 * min(1.0, h.unresolved_similar_nearby / 4.0)
    )


def _rain_signal_mm(mm: float | None) -> float:
    """Map a precipitation amount onto the weather-signal curve (0..1).

    Piecewise-linear over ``_RAIN_MM_SIGNAL`` (0 mm -> 0, 5 mm -> 0.5 midpoint,
    40 mm -> 1.0 saturation). Amounts beyond the last point saturate at 1.0.
    """
    if mm is None or not math.isfinite(mm) or mm <= 0:
        return 0.0
    points = _RAIN_MM_SIGNAL
    if mm >= points[-1][0]:
        return float(points[-1][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= mm <= x1:
            frac = (mm - x0) / (x1 - x0) if x1 > x0 else 0.0
            return float(y0 + frac * (y1 - y0))
    return 0.0


def weather_band_label(score: int | None) -> str | None:
    """:return: the human band label for a /10 weather score (None when unscored).

    Bands: 0-2 none, 3-4 minor, 5-7 moderate, 8-9 strong, 10 severe.
    """
    if score is None:
        return None
    for upper, label in _WEATHER_BANDS:
        if score <= upper:
            return label
    return "severe"


def weather_unit(
    condition: str | None,
    rain_mm: float | None,
    *,
    threshold_mm: float = 5.0,
    precipitation_mm: float | None = None,
    forecast_precip_mm: float | None = None,
    recent_precip_mm: float | None = None,
    precip_probability_pct: float | None = None,
    probability_threshold_pct: float = 60.0,
    category: str | None = None,
) -> float:
    """:return: 0..1 banded weather-risk unit, category-aware and multi-signal.

    Every signal is a real Open-Meteo number — nothing is guessed:

    * current rain (``rain_mm``/``precipitation_mm``) — strongest live signal;
    * RECENT rain (``recent_precip_mm``, trailing past days) — counts, slightly
      discounted, because ground wetness persists for drainage/flooding;
    * forecast rain (``forecast_precip_mm``) — trusted more as the forecast
      precipitation-probability (``precip_probability_pct``) rises, so a
      meaningful forecast lifts a drainage complaint OUT of the old "auto 1/10";
    * a rainy current condition floors 0.55;
    * a high probability of rain by itself signals risk for wet-affecting
      categories (forecast probability ≥ the configured threshold
      ``probability_threshold_pct`` → 0.45, ≥ threshold+25 → 0.6), but only when
      rain is actually forecast (never a bare "probabilistic guess" with a dry
      forecast).

    ``None``/0 mm everywhere yields 0.0 (true "none", never the old automatic
    0.1 from an arbitrary non-empty condition). The unit is then scaled by the
    complaint-category multiplier (drainage/flooding weigh rain far more than
    streetlighting) and clamped; the component's /10 = ``round(unit*10)`` bands
    as 0-2 none, 3-4 minor, 5-7 moderate, 8-9 strong, 10 severe.
    """
    current = rain_mm if rain_mm is not None else precipitation_mm
    signals: list[float] = []

    if recent_precip_mm is not None and recent_precip_mm > 0:
        signals.append(_rain_signal_mm(recent_precip_mm) * 0.9)
    if current is not None and current > 0:
        signals.append(_rain_signal_mm(current))
    if forecast_precip_mm is not None and forecast_precip_mm > 0:
        forecast_signal = _rain_signal_mm(forecast_precip_mm)
        if precip_probability_pct is not None:
            forecast_signal *= 0.6 + 0.4 * _clamp(precip_probability_pct / 100.0)
        signals.append(forecast_signal)

    normalized = (condition or "").strip().lower()
    for rainy in _RAINY_CONDITIONS:
        if rainy.lower() in normalized:
            signals.append(0.55)
            break

    prob = precip_probability_pct if precip_probability_pct is not None else None
    if prob is not None and forecast_precip_mm is not None and forecast_precip_mm > 0:
        if prob >= probability_threshold_pct + 25.0:
            signals.append(0.6)
        elif prob >= probability_threshold_pct:
            signals.append(0.45)

    unit = max(signals) if signals else 0.0
    multiplier = _WEATHER_CATEGORY_MULTIPLIERS.get((category or "").upper())
    if multiplier is not None:
        unit = _clamp(unit * multiplier)
    return _clamp(unit)


def ai_evidence_confidence(e: EvidenceInput) -> tuple[float | None, str | None]:
    """Strongest validated AI verification confidence + its source.

    :return: ``(confidence 0..1 or None, source "vision"/"triage" or None)``.
        Vision is the AI Evidence-Verification agent and is preferred; a vision
        run must be SUCCEEDED, have a ``structured_result.confidence`` and NOT
        have flagged a mismatch (a mismatch voids the vision signal). Falling
        back to the triage run's confidence (also 0..1). Returns ``(None, None)``
        when no validated AI signal exists.
    """
    if e.vision_available and not e.vision_mismatch and e.vision_confidence is not None:
        return _clamp(float(e.vision_confidence)), "vision"
    if e.triage_available and e.triage_confidence is not None:
        return _clamp(float(e.triage_confidence)), "triage"
    return None, None


def evidence_unit(e: EvidenceInput) -> float:
    """:return: 0..1 evidence-confidence unit from real sub-signals.

    The strongest validated AI verification confidence maps 1:1 onto the unit:
    98 % → 0.98 → a 10/10 evidence score, 90 % → 9, 80 % → 8, 70 % → 7. The
    non-AI signals (GPS, description, media, structured category, corroborating
    reports) are blended but capped at ``_NON_AI_EVIDENCE_CAP`` so weak sources
    can never dilute a verified AI classification — the unit is the max.
    """
    if e.status == "INSUFFICIENT_DATA":
        return 0.0
    ai_unit, _source = ai_evidence_confidence(e)

    if e.has_gps:
        if e.gps_accuracy_m is not None and e.gps_accuracy_m > 0:
            gps = 0.6 + 0.4 * (1.0 - _clamp(e.gps_accuracy_m / 100.0))
        else:
            gps = 0.9
    else:
        gps = 0.0
    description = _clamp(e.description_chars / 300.0)
    media = _clamp(e.media_count / 2.0)
    structured = 1.0 if e.category_structured else 0.0
    corroborating = _clamp(e.corroborating_reports_30d / 6.0)
    base_unit = (
        0.30 * gps
        + 0.20 * description
        + 0.20 * media
        + 0.15 * structured
        + 0.15 * corroborating
    )
    if ai_unit is None:
        return _clamp(min(base_unit, _NON_AI_EVIDENCE_CAP))
    return _clamp(max(ai_unit, min(base_unit, _NON_AI_EVIDENCE_CAP)))


# --------------------------------------------------------------------------- #
# Risk amplifiers (deterministic, evidence-backed, NEVER guessed)
# --------------------------------------------------------------------------- #
def _access_impact_detail(
    facilities: list[FacilityInput],
    category: str | None,
    *,
    bands: tuple[float, ...] = (50.0, 100.0, 250.0, 500.0),
    band_factors: tuple[float, ...] = (1.0, 0.9, 0.6, 0.35),
    emergency_band_m: float = 250.0,
) -> dict[str, Any]:
    """Explainable access-impact summary for a complaint category + facilities."""
    cat = (category or "").upper()
    emergency = [
        f
        for f in (facilities or ())
        if str(f.category).upper() in _EMERGENCY_CATEGORIES
        and f.distance_m is not None
    ]
    near = [f for f in emergency if f.distance_m is not None and f.distance_m <= emergency_band_m]
    unclear = [f for f in (facilities or ()) if f.distance_m is None]
    return {
        "category": cat,
        "category_type": (
            "access-affecting" if cat in _ACCESS_AFFECTING_CATEGORIES else (
                "public-affecting" if cat in _PUBLIC_AFFECTING_CATEGORIES else "other"
            )
        ),
        "emergency_access_impacted": (
            cat in _ACCESS_AFFECTING_CATEGORIES
            and bool(access_proximity(near, bands, band_factors))
        ),
        "emergency_facilities_within_band": [
            {
                "name": f.name,
                "category": f.category,
                "distance_m": f.distance_m,
                "decay": round(
                    distance_band_factor(f.distance_m, bands, band_factors), 3
                ),
            }
            for f in sorted(near, key=lambda x: (x.distance_m or float("inf")))
        ][:5],
        "unresolved_facility_distances": len(unclear),
    }


def access_proximity(
    facilities: list[FacilityInput],
    bands: tuple[float, float, float],
    band_factors: tuple[float, float, float],
) -> float:
    """0..1 proximity weight of emergency facilities in range."""
    return sum(distance_band_factor(f.distance_m, bands, band_factors) for f in (facilities or ()))


def evaluate_risk_amplifiers(
    *,
    category: str,
    severity: str | None,
    infrastructure: InfrastructureInput | None,
    historical: HistoricalInput | None,
    weather: WeatherInput | None,
    amplifier_points: dict[str, float] | None = None,
    hotspot_repeat_count: int = 5,
    emergency_access_band_m: float = 250.0,
) -> list[dict[str, Any]]:
    """Evaluate the four deterministic risk amplifiers against real evidence.

    Each amplifier reports its trigger conditions and the exact real evidence
    that satisfied them, so a ``+N`` is always explainable. No amplifier is ever
    applied "just to push a score up". EMERGENCY_ACCESS_RISK now ALSO requires an
    access-affecting complaint category (a hospital 55 m away does NOT trigger it
    for an unrelated category), and FLOODING_RISK needs real rain/forecast or
    genuine same-category recurrence evidence.
    """
    points = {
        "FLOODING_RISK": amplifier_points.get("FLOODING_RISK", 6.0)
        if amplifier_points
        else 6.0,
        "EMERGENCY_ACCESS_RISK": amplifier_points.get("EMERGENCY_ACCESS_RISK", 5.0)
        if amplifier_points
        else 5.0,
        "PUBLIC_SAFETY_RISK": amplifier_points.get("PUBLIC_SAFETY_RISK", 5.0)
        if amplifier_points
        else 5.0,
        "RECURRING_HOTSPOT": amplifier_points.get("RECURRING_HOTSPOT", 4.0)
        if amplifier_points
        else 4.0,
    }
    out: list[dict[str, Any]] = []

    cat = (category or "").upper()
    facilities = list((infrastructure.facilities or ()) if infrastructure is not None else ())
    weather_available = weather is not None and weather.status == "AVAILABLE"
    current_rain = (
        weather.rain_mm if weather.rain_mm is not None else weather.precipitation_mm
    ) if weather is not None else None
    forecast_rain = weather.forecast_precip_mm if weather is not None else None
    threshold = weather.threshold_mm if weather is not None else 5.0
    same_cat_30d = historical.same_category_nearby_30d if historical is not None else 0

    def _emitter(
        key: str, label: str, default_points: float, triggers: list[str], evidence: list[str]
    ) -> None:
        applied = bool(triggers and evidence)
        out.append(
            {
                "key": key,
                "label": label,
                "points": int(round(default_points)),
                "applied": applied,
                "trigger_conditions": triggers,
                "evidence": evidence,
                "explanation": (
                    (
                        f"{label} triggered: {'; '.join(evidence)}."
                        if evidence
                        else f"{label} not triggered (no real evidence)."
                    )
                    if applied
                    else f"{label} not triggered: no real evidence met the conditions."
                ),
            }
        )

    flooding_triggers: list[str] = []
    flooding_evidence: list[str] = []
    if cat in _FLOODING_CATEGORIES:
        flooding_triggers.append("Complaint category is flood/drainage-related")
        if current_rain is not None and current_rain >= threshold:
            flooding_triggers.append(f"Current precipitation >= {threshold:g} mm")
            flooding_evidence.append(f"{current_rain:.1f} mm now")
        if forecast_rain is not None and forecast_rain >= threshold:
            flooding_triggers.append(f"Forecast precipitation >= {threshold:g} mm")
            flooding_evidence.append(f"{forecast_rain:.1f} mm forecast")
        if same_cat_30d > 0:
            flooding_triggers.append("Similar issues occurred in the last 30 days")
            flooding_evidence.append(f"{same_cat_30d} similar in 30 d")
        if weather_available and current_rain is None and forecast_rain is None:
            flooding_triggers.append("Weather data is live (no rain signal yet)")
            flooding_evidence.append(f"condition={weather.condition or 'n/a'}")
    else:
        flooding_triggers = ["Complaint category is not flood/drainage-related"]
    if not flooding_evidence:
        flooding_triggers = ["Flooding risk needs real rain/forecast or recurrence"]
    _emitter(
        "FLOODING_RISK",
        "Flooding risk",
        points["FLOODING_RISK"],
        flooding_triggers,
        flooding_evidence,
    )

    emergency_triggers: list[str] = []
    emergency_evidence: list[str] = []
    emergency_facilities = [
        f for f in facilities
        if str(f.category).upper() in _EMERGENCY_CATEGORIES
        and f.distance_m is not None
        and f.distance_m <= emergency_access_band_m
    ]
    if cat in _ACCESS_AFFECTING_CATEGORIES and emergency_facilities:
        distance_emergency = [
            f"{f.name} ({f.category}, {f.distance_m:.0f} m)"
            for f in sorted(
                emergency_facilities, key=lambda f: (f.distance_m or float("inf"))
            )
        ]
        emergency_triggers.append(
            "Access-affecting hazard close to an emergency facility "
            f"(within {emergency_access_band_m:g} m)"
        )
        emergency_triggers.append(f"Complaint category={cat}")
        emergency_evidence = distance_emergency[:3]
    else:
        emergency_triggers = [
            "No access-affecting hazard near an emergency facility within "
            f"{emergency_access_band_m:g} m"
        ]
    _emitter(
        "EMERGENCY_ACCESS_RISK",
        "Emergency access risk",
        points["EMERGENCY_ACCESS_RISK"],
        emergency_triggers,
        emergency_evidence,
    )

    safety_facilities = [
        f"{f.name} ({f.category}, {f.distance_m:.0f} m)"
        for f in facilities
        if str(f.category).upper() in _PUBLIC_SAFETY_FACILITY_CATEGORIES
        and f.distance_m is not None
        and f.distance_m <= 150
    ]
    safety_triggers: list[str] = []
    safety_evidence: list[str] = []
    if cat in _PUBLIC_SAFETY_COMPLAINT_CATEGORIES and safety_facilities:
        safety_triggers.append("Hazard near people: school/hospital/transit within 150 m")
        safety_evidence = safety_facilities[:3]
    else:
        safety_triggers = ["No hazard near a school/hospital/transit within 150 m"]
    _emitter(
        "PUBLIC_SAFETY_RISK",
        "Public safety risk",
        points["PUBLIC_SAFETY_RISK"],
        safety_triggers,
        safety_evidence,
    )

    hotspot_triggers: list[str] = []
    hotspot_evidence: list[str] = []
    unresolved = historical.unresolved_similar_nearby if historical is not None else 0
    if same_cat_30d >= max(1, int(hotspot_repeat_count)) and unresolved >= 1:
        hotspot_triggers.append("Repeated same-category incidents in the area")
        hotspot_evidence.append(
            f"{same_cat_30d} similar in 30 d, {unresolved} still unresolved"
        )
    else:
        hotspot_triggers = ["No recurring same-category hotspot in the area"]
    _emitter(
        "RECURRING_HOTSPOT",
        "Recurring hotspot",
        points["RECURRING_HOTSPOT"],
        hotspot_triggers,
        hotspot_evidence,
    )

    return [a for a in out if a["applied"]]


# --------------------------------------------------------------------------- #
# Bucketing
# --------------------------------------------------------------------------- #
def priority_from_score(
    score: int,
    threshold_p1: float = 80.0,
    threshold_p2: float = 60.0,
    threshold_p3: float = 40.0,
) -> DynamicPriority:
    """Map a 0..100 integer score onto a ``DynamicPriority`` bucket."""
    if score >= threshold_p1:
        return DynamicPriority.P1_CRITICAL
    if score >= threshold_p2:
        return DynamicPriority.P2_HIGH
    if score >= threshold_p3:
        return DynamicPriority.P3_MEDIUM
    return DynamicPriority.P4_LOW


def readiness_from_components(components: list[dict[str, Any]]) -> PriorityReadiness:
    """Derive the honest data-readiness of a computation from its components.

    Severity is always present; ``READY`` needs at least 5 of the 6 components
    scored, ``PARTIAL`` between 3 and 4, ``INSUFFICIENT_DATA`` otherwise
    (severity alone is never enough to trust a score).
    """
    scored = [c for c in components if c.get("score") is not None]
    if len(scored) >= 5:
        return PriorityReadiness.READY
    if len(scored) >= 3:
        return PriorityReadiness.PARTIAL
    return PriorityReadiness.INSUFFICIENT_DATA


def score_from_units(
    units: dict[str, float],
    weights: Weights | None = None,
    threshold_p1: float = 80.0,
    threshold_p2: float = 60.0,
    threshold_p3: float = 40.0,
) -> tuple[int, dict[str, float]]:
    """Compute a deterministic 0..100 score from already-normalized units.

    ``units`` maps factor keys (``severity``, ``infrastructure``,
    ``population``, ``historical``, ``weather``, ``evidence``) to normalized 0..1
    values; each key's ``max_points`` is its weight. The score is the plain SUM
    of ``unit * max_points`` (clamped 0..100) — it is NOT re-normalized over the
    present set, so a missing factor never inflates the others.

    :returns: (integer score, dict factor_key -> contribution points)
    """
    w = weights or Weights()
    factor_max = {
        "severity": w.severity,
        "infrastructure": w.infrastructure,
        "population": w.population,
        "historical": w.history,
        "weather": w.weather,
        "evidence": w.evidence,
    }
    if not units:
        return 0, {}

    contributions: dict[str, float] = {}
    raw = 0.0
    for key, unit in units.items():
        if key not in factor_max:
            continue
        unit = max(0.0, min(1.0, float(unit)))
        contrib = round(unit * float(factor_max[key]), 2)
        contributions[key] = contrib
        raw += contrib
    score = int(round(raw))
    return min(100, max(0, score)), contributions


# --------------------------------------------------------------------------- #
# Public pure scoring entry point
# --------------------------------------------------------------------------- #
def score_priority(
    *,
    category: str,
    severity: SeverityInput,
    complaint_description: str | None = None,
    infrastructure: InfrastructureInput | None = None,
    population: PopulationInput | None = None,
    weather: WeatherInput | None = None,
    historical: HistoricalInput | None = None,
    evidence: EvidenceInput | None = None,
    weights: Weights | None = None,
    threshold_p1: float = 80.0,
    threshold_p2: float = 60.0,
    threshold_p3: float = 40.0,
    infra_decay_bands: tuple[float, ...] = (50.0, 100.0, 250.0, 500.0),
    infra_band_factors: tuple[float, ...] = (1.0, 0.9, 0.6, 0.35),
infra_saturation: float = 2.2,
    infra_peak_weight: float = _INFRA_PEAK_WEIGHT,
    infra_cluster_weight: float = _INFRA_CLUSTER_WEIGHT,
    infra_access_bonus_50m: float = _INFRA_ACCESS_BONUS_50M,
    infra_access_bonus_100m: float = _INFRA_ACCESS_BONUS_100M,
    weather_probability_threshold_pct: float = 60.0,
    facility_base_relevance: dict[str, float] | None = None,
        category_facility_factors: dict[str, dict[str, float]] | None = None,
        population_subweights: dict[str, float] | None = None,
        emergency_access_band_m: float = 250.0,
        amplifier_points: dict[str, float] | None = None,
        hotspot_repeat_count: int = 5,
) -> tuple[int, DynamicPriority, list[dict[str, Any]], PriorityReadiness, list[dict[str, Any]]]:
    """Score a complaint against the six real-data components (pure).

    Each component produces a ``score`` of at most its ``max_points``; the BASE
    score is the plain sum (clamped 0..100), never re-normalized. Only real-evidence
    risk amplifiers may add further points (still clamped 0..100). A component
    whose data could not be resolved has ``score=None`` and contributes 0, with
    its ``status``/``source`` still reported so the UI can show it honestly.

    ``complaint_description`` (optional) is the raw complaint text. When it
    EXPLICITLY names a facility and the infrastructure registry VERIFIES a
    facility of that type in range, the infrastructure component scores its full
    ``max_points`` (30/30 by default) — reported with the matched record id,
    matched facility type, real distance, relationship and relationship
    confidence. An explicit mention with NO verified match never triggers the
    rule and falls back to contextual scoring.

    :returns: (amplified score 0..100, bucket, component dicts, readiness,
        applied risk amplifiers)
    """
    w = weights or Weights()
    now = severity.calculated_at or datetime.now(UTC)
    components: list[dict[str, Any]] = []

    def _emit(
        key: str,
        label: str,
        max_points: float,
        unit: float,
        status: str,
        source: str,
        input_value: str,
        explanation: str | None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        score = (
            int(round(unit * max_points))
            if status not in {"DATA_UNAVAILABLE", "INSUFFICIENT_DATA"}
            else None
        )
        return {
            "key": key,
            "label": label,
            "score": score,
            "max_score": int(round(max_points)),
            "unit": round(_clamp(unit), 3),
            "status": status,
            "input_value": input_value,
            "explanation": explanation or "",
            "source": source,
            "calculated_at": now.isoformat(),
            "details": details,
        }

    dims = severity_dimensions(
        severity=severity.severity,
        category=category,
        infrastructure=infrastructure,
        population=population,
        weather=weather,
        complaint_description=complaint_description,
        bands=infra_decay_bands,
        band_factors=infra_band_factors,
    )
    sub_maxima = {
        sub: round(w.severity * frac)
        for sub, frac in _SEVERITY_SUB_FRACTIONS.items()
    }
    sub_scores = {
        sub: int(round(dims[sub] * sub_maxima[sub])) for sub in dims
    }
    severity_unit_value = sum(sub_scores.values()) / w.severity
    components.append(
        _emit(
            "severity",
            "Severity / potential harm",
            w.severity,
            severity_unit_value,
            severity.status,
            severity.source,
            (severity.severity or "LOW").upper(),
            severity.explanation
            or (
                "Five-part severity: the AI triage label sets ONLY the base "
                f"({severity_unit(severity.severity) * sub_maxima['base']:g}/"
                f"{sub_maxima['base']:g}); Safety/Harm, Public accessibility, "
                "Critical infrastructure impact and Environmental/weather are "
                "deterministic escalators from verified evidence — the AI label "
                "is the base, not a cap, and empty context adds nothing."
            ),
            details={
                "triage_input": severity.severity or "LOW",
                "model": "5-part (sum = severity max points): base + safety + "
                "accessibility + critical_infrastructure + environmental",
                "dimensions": dims,
                "base_unit": round(severity_unit(severity.severity), 3),
                "subcomponents": {
                    sub: {
                        "label": _SEVERITY_SUB_LABELS[sub],
                        "max": sub_maxima[sub],
                        "score": sub_scores[sub],
                        "unit": round(dims[sub], 3),
                    }
                    for sub in _SEVERITY_SUB_FRACTIONS
                },
                "escalation_formula": (
                    "severity(0..max) = base(unit*"
                    f"{sub_maxima['base']:g}) + safety(x"
                    f"{sub_maxima['safety']:g}) + accessibility(x"
                    f"{sub_maxima['accessibility']:g}) + "
                    f"critical_infrastructure(x{sub_maxima['critical_infrastructure']:g}) "
                    f"+ environmental(x{sub_maxima['environmental']:g}); "
                    "AI triage supplies ONLY the base sub-score"
                ),
            },
        )
    )

    infra_facilities: list[FacilityInput] = []
    if infrastructure is not None:
        infra_facilities = list(infrastructure.facilities or ())
        unit = infrastructure_unit(
            infra_facilities,
            category,
            facility_base_relevance,
            category_facility_factors,
            bands=infra_decay_bands,
            band_factors=infra_band_factors,
            saturation=infra_saturation,
            peak_weight=infra_peak_weight,
            cluster_weight=infra_cluster_weight,
            access_bonus_50m=infra_access_bonus_50m,
            access_bonus_100m=infra_access_bonus_100m,
        )
        # ---- Explicit-facility rule: text names a facility AND the registry
        # ---- VERIFIES it in range AND the pair is relevant -> full max_points.
        explicit_facility = detect_explicit_facility(
            complaint_description or infrastructure.explanation or None
        )
        explicit_match = (
            best_facility_match(explicit_facility, infra_facilities)
            if explicit_facility is not None
            else None
        )
        explicit_relevant = (
            explicit_facility_relevant(
                category, explicit_match.category if explicit_match is not None else None
            )
            if explicit_facility is not None
            else False
        )
        relationship_confidence: float | None = None
        if explicit_match is not None:
            relationship_confidence = round(
                min(
                    0.9,
                    0.5
                    + 0.4
                    * distance_band_factor(
                        explicit_match.distance_m, infra_decay_bands, infra_band_factors
                    ),
                ),
                3,
            )
        infra30 = bool(
            explicit_facility is not None
            and explicit_match is not None
            and explicit_relevant
            and infrastructure.status != "DATA_UNAVAILABLE"
        )
        if infra30:
            unit = 1.0
        access_impact = _access_impact_detail(
            infra_facilities,
            category,
            bands=infra_decay_bands,
            band_factors=infra_band_factors,
            emergency_band_m=emergency_access_band_m,
        )
        labels = {
            "FOUND": "Verified nearby facilities found",
            "NO_VERIFIED_RECORDS": (
                "Search resolved: verified zero nearby facilities"
            ),
            "DATA_UNAVAILABLE": (
                "Nearby-infrastructure lookup could not be performed; nothing claimed"
            ),
            "PARTIAL_DATA": "Some categories resolved, others degraded",
        }
        summary_parts = []
        if explicit_facility is not None:
            summary_parts.append(
                f"explicit mention: {explicit_facility.lower()}"
            )
        summary = ", ".join(
            f"{f.category.lower()}: {f.distance_m:.0f} m" for f in infra_facilities[:5]
        ) or "none in range"
        if summary_parts:
            summary = f"{summary_parts[0]}; {summary}"
        comp = _emit(
            "infrastructure",
            "Infrastructure exposure",
            w.infrastructure,
            unit,
            infrastructure.status,
            infrastructure.source,
            summary,
            labels.get(infrastructure.status) or infrastructure.explanation,
            details={
                "radius_m": infrastructure.radius_m,
                "explicit_facility_mentioned": explicit_facility,
                "matched_facility_id": (
                    explicit_match.record_id if explicit_match is not None else None
                ),
                "matched_facility_type": (
                    explicit_match.category if explicit_match is not None else None
                ),
                "matched_facility_name": (
                    explicit_match.name if explicit_match is not None else None
                ),
                "matched_distance_m": (
                    explicit_match.distance_m if explicit_match is not None else None
                ),
                "relationship": (
                    f"Complaint text explicitly names a {explicit_facility.lower()}; "
                    f"verified {explicit_match.category.lower()} {explicit_match.name!r} is "
                    f"{explicit_match.distance_m:.0f} m away."
                    if explicit_match is not None
                    else (
                        f"Complaint text explicitly names a {explicit_facility.lower()} "
                        "but no verified facility of that type was found in range; "
                        "the 30/30 rule is NOT applied (contextual score only)."
                        if explicit_facility is not None
                        else "No explicit facility mentioned; contextual scoring."
                    )
                ),
                "relationship_confidence": relationship_confidence,
                "explicit_rule_applied": infra30,
                "access_impact": access_impact,
                "contributing_facilities": [
                    {
                        "name": f.name,
                        "category": f.category,
                        "distance_m": f.distance_m,
                        "verification": f.verification,
                        "record_id": f.record_id,
                        "relevance": round(
                            facility_relevance(
                                f,
                                category,
                                facility_base_relevance,
                                category_facility_factors,
                            ),
                            3,
                        ),
                        "contribution": round(
                            facility_contribution(
                                f,
                                category,
                                facility_base_relevance,
                                category_facility_factors,
                                bands=infra_decay_bands,
                                band_factors=infra_band_factors,
                            ),
                            3,
                        ),
                    }
                    for f in infra_facilities
                ],
            },
        )
        comp["radius_m"] = infrastructure.radius_m
        components.append(comp)

    if population is not None:
        unit = population_unit(population, population_subweights)
        subs = population_subunits(population, population_subweights)
        radii_7d = sorted((population.reports_7d or {}).items())
        radii_30d = sorted((population.reports_30d or {}).items())
        sub_records: dict[str, Any] = {}
        for key, sub_unit, weight in subs:
            sub_records[key] = {
                "score": (
                    int(round(sub_unit * w.population))
                    if sub_unit is not None
                    else None
                ),
                "status": "AVAILABLE" if sub_unit is not None else "DATA_UNAVAILABLE",
                "weight": round(weight, 2),
            }
        sub_records["population_exposure"]["status"] = population.population_status
        comp = _emit(
            "population",
            "Affected population & area",
            w.population,
            unit,
            population.status,
            population.source,
            (
                f"7d: {', '.join(f'{r}m={n}' for r, n in radii_7d)}; "
                f"30d: {', '.join(f'{r}m={n}' for r, n in radii_30d)}"
            ),
            population.explanation
            or (
                "Real report pressure (250/500/1000 m over 7d/30d), geographic "
                "spread and sensitive-facility exposure, re-normalized over what "
                "is genuinely AVAILABLE."
                + (
                    " Population density dataset unavailable (never fabricated)."
                    if population.population_status == "DATA_UNAVAILABLE"
                    else ""
                )
                if population.status == "AVAILABLE"
                else "Insufficient report data (no location)"
            ),
            details={
                "reports_7d": population.reports_7d,
                "reports_30d": population.reports_30d,
                "unique_reporters_7d": population.unique_reporters_7d,
                "unique_reporters_30d": population.unique_reporters_30d,
                "unresolved_7d": population.unresolved_reports_7d,
                "unresolved_30d": population.unresolved_reports_30d,
                "geographic_spread_max_distance_m": population.spread_max_distance_m,
                "sensitive_facilities_nearby": population.sensitive_facilities_nearby,
                "sensitive_facilities": [
                    {
                        "name": f.name,
                        "category": f.category,
                        "distance_m": f.distance_m,
                    }
                    for f in (population.sensitive_facilities or ())
                ],
                "population": population.population,
                "population_status": population.population_status,
                "subcomponents": sub_records,
            },
        )
        components.append(comp)

    if weather is not None:
        unit = weather_unit(
            weather.condition,
            weather.rain_mm,
            threshold_mm=weather.threshold_mm or 5.0,
            precipitation_mm=weather.precipitation_mm,
            forecast_precip_mm=weather.forecast_precip_mm,
            recent_precip_mm=weather.recent_precip_mm,
            precip_probability_pct=weather.precip_probability_pct,
            probability_threshold_pct=weather_probability_threshold_pct,
            category=category,
        )
        state_available = weather.status == "AVAILABLE"
        if not state_available:
            unit = 0.0
        rain_value = (
            weather.rain_mm
            if weather.rain_mm is not None
            else weather.precipitation_mm or 0.0
        )
        band_label = weather_band_label(
            int(round(unit * w.weather)) if state_available else None
        )
        # A raw unit < 0.05 can still round to a 10-scale 0 (correct); banded
        # units are derived from the raw unit, not this rounded /10 value.
        components.append(
            _emit(
                "weather",
                "Weather / environmental risk",
                w.weather,
                unit,
                weather.status,
                weather.source,
                (
                    f"{weather.condition or 'n/a'}, {float(rain_value):.1f} mm now, "
                    f"{float(weather.forecast_precip_mm or 0.0):.1f} mm forecast, "
                    f"{float(weather.recent_precip_mm or 0.0):.1f} mm recent, "
                    f"{weather.precip_probability_pct or 0.0:.0f}% forecast probability"
                ),
                weather.explanation
                or (
                    "Real Open-Meteo current + recent + forecast precipitation and "
                    "forecast probability, category-aware and banded"
                    if state_available
                    else "Weather data unavailable (no coordinates or upstream failure)"
                ),
                details={
                    "condition": weather.condition,
                    "rain_mm_now": (  # noqa: E501
                        weather.rain_mm
                        if weather.rain_mm is not None
                        else weather.precipitation_mm
                    ),
                    "forecast_precip_max_mm": weather.forecast_precip_mm,
                    "recent_precip_max_mm": weather.recent_precip_mm,
                    "forecast_precipitation_probability_pct": weather.precip_probability_pct,
                    "band": band_label,
                    "category_multiplier": _WEATHER_CATEGORY_MULTIPLIERS.get(
                        (category or "").upper()
                    ),
                },
            )
        )

    if historical is not None:
        unit = historical_unit(historical)
        components.append(
            _emit(
                "historical",
                "Recurrence / incident pattern",
                w.history,
                unit,
                historical.status,
                historical.source,
                (
                    f"{historical.same_category_nearby_30d} same cat·30d, "
                    f"{historical.same_category_nearby_7d} same cat·7d, "
                    f"{historical.nearby_30d} nearby·30d, "
                    f"{historical.unresolved_similar_nearby} unresolved similar"
                ),
                historical.explanation
                or (
                    "Real prior-complaint recurrence in the area (same category, 7 d/30 d)"
                    if historical.status == "AVAILABLE"
                    else "Insufficient historical signal (no ward or location)"
                ),
                details={
                    "same_category_7d": historical.same_category_nearby_7d,
                    "same_category_30d": historical.same_category_nearby_30d,
                    "nearby_7d": historical.nearby_7d,
                    "nearby_30d": historical.nearby_30d,
                    "cluster_250m_30d": historical.cluster_250m_30d,
                    "ward_30d": historical.ward_30d,
                    "unresolved_similar": historical.unresolved_similar_nearby,
                    "duplicates_excluded": historical.duplicates_excluded,
                },
            )
        )

    if evidence is not None:
        unit = evidence_unit(evidence)
        if evidence.status == "INSUFFICIENT_DATA":
            unit = 0.0
        ai_conf, ai_source = ai_evidence_confidence(evidence)
        ai_pct = int(round((ai_conf or 0.0) * 100.0))
        ai_label = (
            f"AI verified {ai_pct}% ({ai_source})"
            if ai_conf is not None
            else "AI not available"
        )
        components.append(
            _emit(
                "evidence",
                "Evidence confidence",
                w.evidence,
                unit,
                evidence.status,
                evidence.source,
                (
                    f"GPS={evidence.has_gps}, {evidence.description_chars} chars, "
                    f"{evidence.media_count} media, {ai_label}"
                ),
                evidence.explanation
                or (
                    "Strongest validated AI verification confidence mapped 1:1 "
                    "(98% → 10/10); non-AI signals capped so they never dilute it"
                    if evidence.status == "AVAILABLE"
                    else (
                        "AI evidence unavailable — scored on non-AI signals only"
                        if evidence.status == "PARTIAL"
                        else "No evidence requested or resolvable"
                    )
                ),
                details={
                    "has_gps": evidence.has_gps,
                    "gps_source": evidence.gps_source,
                    "gps_accuracy_m": evidence.gps_accuracy_m,
                    "description_chars": evidence.description_chars,
                    "media_count": evidence.media_count,
                    "category_structured": evidence.category_structured,
                    "triage_available": evidence.triage_available,
                    "triage_confidence": evidence.triage_confidence,
                    "vision_available": evidence.vision_available,
                    "vision_confidence": evidence.vision_confidence,
                    "vision_mismatch": evidence.vision_mismatch,
                    "corroborating_reports_30d": evidence.corroborating_reports_30d,
                    "ai_verification_confidence_pct": ai_pct,
                    "ai_verification_source": ai_source,
                    "ai_verification_summary": ai_label,
                },
            )
        )

    base_score = int(round(sum(c.get("score") or 0 for c in components)))
    base_score = min(100, max(0, base_score))

    amplifiers = evaluate_risk_amplifiers(
        category=category,
        severity=severity.severity,
        infrastructure=infrastructure,
        historical=historical,
        weather=weather,
        amplifier_points=amplifier_points,
        hotspot_repeat_count=hotspot_repeat_count,
        emergency_access_band_m=emergency_access_band_m,
    )
    amplifier_total = sum(int(a["points"]) for a in amplifiers)
    score = min(100, max(0, base_score + amplifier_total))
    bucket = priority_from_score(score, threshold_p1, threshold_p2, threshold_p3)
    readiness = readiness_from_components(components)
    components.sort(key=lambda c: -float(c.get("score") or 0))
    return score, bucket, components, readiness, amplifiers


__all__ = [
    "EvidenceInput",
    "FacilityInput",
    "HistoricalInput",
    "InfrastructureInput",
    "PopulationInput",
    "PriorityDataBundle",
    "SeverityInput",
    "Weights",
    "WeatherInput",
    "access_proximity",
    "ai_evidence_confidence",
    "distance_band_factor",
    "evaluate_risk_amplifiers",
    "evidence_unit",
    "facility_contribution",
    "facility_relevance",
    "historical_unit",
    "infrastructure_unit",
    "population_subunits",
    "population_unit",
    "priority_from_score",
    "readiness_from_components",
    "score_from_units",
    "score_priority",
    "sensitive_exposure_unit",
    "severity_dimensions",
    "severity_unit",
    "weather_unit",
]
