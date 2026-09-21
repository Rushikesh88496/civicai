"""Deterministic Priority & Risk scoring engine (Part 12).

The engine maps the seven priority inputs onto a single 0..100 score and a
``DynamicPriority`` bucket. It is pure, dependency-free and fully deterministic
— there is NO LLM involvement in the numeric score or the bucket.

Scoring model
-------------
Each input is first normalized to a dimensionless 0..1 ``unit`` via a fixed,
piecewise mapping. Each unit is then weighted by a configurable weight and the
weighted sum (over the *present* inputs only, re-normalized) is scaled to 0..100
and rounded to an integer score:

    contribution_i = unit_i * weight_i * 100
    score          = round( 100 * sum_i(unit_i * weight_i) / sum_i(weight_i) )

Because each present input's weight is re-normalized to the present set, a score
is robust to missing signals (an unknown weather contributes 0 and does not
distort the others). The result also carries an explainable factor breakdown:
factor name, input value, weight and point contribution.

Bucket thresholds (configurable via ``PRIORITY_THRESHOLD_P*``):

    [80, 100] -> P1_CRITICAL
    [60,  80) -> P2_HIGH
    [40,  60) -> P3_MEDIUM
    [ 0,  40) -> P4_LOW

``score_priority()`` is the single pure entry point used by the agent; the lower
level ``*_unit()`` helpers and ``priority_from_score()`` are exported so tests
can drive the exact boundary scores deterministically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.enums import DynamicPriority

# Severity label -> numeric unit. The complaint's stored severity (set by the
# triage agent as an input) maps onto a 0..1 basis for the weighted formula.
_SEVERITY_UNITS: dict[str, float] = {
    "LOW": 0.10,
    "MEDIUM": 0.35,
    "HIGH": 0.65,
    "CRITICAL": 0.90,
}

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


@dataclass(frozen=True)
class Weights:
    """Configurable factor weights (defaults sum to 1.0)."""

    severity: float = 0.30
    weather: float = 0.10
    location: float = 0.15
    crowd: float = 0.20
    history: float = 0.10
    time: float = 0.15


# --------------------------------------------------------------------------- #
# Pure 0..1 normalizers (each is deterministic and clamps to [0,1])
# --------------------------------------------------------------------------- #
def severity_unit(severity: str | None) -> float:
    """:return: 0..1 unit for the complaint's stored severity."""
    if not severity:
        return 0.0
    return min(1.0, max(0.0, _SEVERITY_UNITS.get(severity.upper(), 0.10)))


def population_unit(residents: int, band: float = 1000.0) -> float:
    """:return: 0..1 population-impact unit based on ward resident count."""
    if not isinstance(residents, int) or residents <= 0 or band <= 0:
        return 0.0
    return min(1.0, residents / band)


def infrastructure_unit(hospitals: int, schools: int, bus_stops: int, band: float = 5.0) -> float:
    """:return: 0..1 proximity-to-critical-infrastructure unit.

    Hospitals weigh twice as much as schools/bus stops because medical proximity
    usually carries the strongest risk.
    """
    total = (2 * int(hospitals or 0)) + int(schools or 0) + int(bus_stops or 0)
    if total <= 0 or band <= 0:
        return 0.0
    return min(1.0, total / band)


def weather_unit(
    condition: str | None, rain_mm: float | None, threshold_mm: float = 5.0, available: bool = False
) -> float:
    """:return: 0..1 weather-risk unit from the condition label and rainfall."""
    if not available:
        return 0.0
    unit = 0.0
    normalized = (condition or "").strip().lower()
    for rainy in _RAINY_CONDITIONS:
        if rainy.lower() in normalized:
            unit = max(unit, 0.6)
            break
    if rain_mm is not None and rain_mm > 0 and threshold_mm > 0:
        unit = max(unit, min(1.0, rain_mm / threshold_mm))
    if unit == 0.0 and condition:
        # Present but non-rainy condition contributes a small base (any weather
        # signal is at least *some* risk context, capped low).
        unit = 0.1
    return min(1.0, max(0.0, unit))


def complaint_count_unit(total_prior: int, band: float = 10.0) -> float:
    """:return: 0..1 crowd unit based on complaint volume near the location."""
    if not isinstance(total_prior, int) or total_prior <= 0 or band <= 0:
        return 0.0
    return min(1.0, total_prior / band)


def history_unit(same_ward_count: int | None, band: float = 15.0) -> float:
    """:return: 0..1 recurrence unit based on same-ward historical complaints."""
    if same_ward_count is None or same_ward_count <= 0 or band <= 0:
        return 0.0
    return min(1.0, same_ward_count / band)


def time_unit(time_unresolved_hours: float, band_hours: float = 168.0) -> float:
    """:return: 0..1 unresolved-time unit (ramps to 1 at ``band_hours``)."""
    if (
        not isinstance(time_unresolved_hours, (int, float))
        or not math.isfinite(float(time_unresolved_hours))
        or band_hours <= 0
    ):
        return 0.0
    return min(1.0, max(0.0, float(time_unresolved_hours) / band_hours))


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


# --------------------------------------------------------------------------- #
# Weighted combination
# --------------------------------------------------------------------------- #
def score_from_units(
    units: dict[str, float],
    weights: Weights | None = None,
    threshold_p1: float = 80.0,
    threshold_p2: float = 60.0,
    threshold_p3: float = 40.0,
) -> tuple[int, dict[str, float]]:
    """Compute a deterministic 0..100 integer score from normalized units.

    ``units`` maps factor keys (``severity``, ``weather``, ``location``,
    ``crowd``, ``history``, ``time``) to already-normalized 0..1 values. Only the
    present (in the dict) units are weighted; the weights are re-normalized over
    the present set so missing signals never distort the result.

    :returns: (integer score, dict factor_key -> contribution points)
    """
    w = weights or Weights()
    factor_weights = {
        "severity": w.severity,
        "weather": w.weather,
        "location": w.location,
        "crowd": w.crowd,
        "history": w.history,
        "time": w.time,
    }
    present = {k: max(0.0, min(1.0, float(units[k]))) for k in factor_weights if k in units}
    total_w = sum(factor_weights[k] for k in present)
    if not present or total_w <= 0:
        return 0, {}

    contributions: dict[str, float] = {}
    raw = 0.0
    for key, unit in present.items():
        contrib = unit * factor_weights[key] * 100.0
        contributions[key] = round(contrib, 2)
        raw += contrib
    score = int(round(raw / total_w))  # re-normalize over present weights
    return min(100, max(0, score)), contributions


def _clamp(v: float) -> float:
    return min(1.0, max(0.0, v))


# --------------------------------------------------------------------------- #
# Public pure scoring entry point
# --------------------------------------------------------------------------- #
def score_priority(
    *,
    severity: str | None,
    population: int,
    hospitals: int,
    schools: int,
    bus_stops: int,
    weather_condition: str | None,
    rain_mm: float | None,
    weather_available: bool,
    complaint_count: int,
    historical_recurrence: int | None,
    ward_resolved: bool,
    time_unresolved_hours: float,
    weights: Weights | None = None,
    threshold_p1: float = 80.0,
    threshold_p2: float = 60.0,
    threshold_p3: float = 40.0,
    weather_rain_mm: float = 5.0,
    population_band: float = 1000.0,
    complaint_band: float = 10.0,
    history_band: float = 15.0,
    time_band_hours: float = 168.0,
    location_available: bool = True,
) -> tuple[int, DynamicPriority, list[dict[str, object]]]:
    """Score a complaint against the seven priority inputs (pure).

    ``location_available`` encodes null-vs-0 for the critical-infrastructure
    factor: True means the GIS lookup genuinely resolved the area (counts are a
    verified figure, even an honest 0); False means the lookup could not be
    performed (DATA_UNAVAILABLE) and the location factor is excluded from the
    weighted score entirely — an unknown is never scored as "no infrastructure".

    :returns: (integer 0..100 score, DynamicPriority bucket, factor list)
    """
    units: dict[str, float] = {
        "severity": severity_unit(severity),
        "weather": weather_unit(weather_condition, rain_mm, weather_rain_mm, weather_available),
        "crowd": min(
            1.0,
            0.5 * population_unit(population, population_band)
            + 0.5 * complaint_count_unit(complaint_count, complaint_band),
        ),
        "history": history_unit(historical_recurrence, history_band),
        "time": time_unit(time_unresolved_hours, time_band_hours),
    }
    if location_available:
        units["location"] = infrastructure_unit(hospitals, schools, bus_stops, 5.0)
    score, contributions = score_from_units(
        units, weights, threshold_p1, threshold_p2, threshold_p3
    )
    bucket = priority_from_score(score, threshold_p1, threshold_p2, threshold_p3)

    present = set(contributions)
    factor_meta = [
        ("severity", "Severity"),
        ("weather", "Weather risk"),
        ("location", "Critical infrastructure proximity"),
        ("crowd", "Crowd pressure (population + reports)"),
        ("history", "Historical recurrence"),
        ("time", "Time unresolved"),
    ]
    factors: list[dict[str, object]] = []
    for key, label in factor_meta:
        contribution = contributions.get(key, 0.0)
        present_flag = key in present
        input_value = _input_label(
            key,
            {
                "severity": severity,
                "population": population,
                "hospitals": hospitals,
                "schools": schools,
                "bus_stops": bus_stops,
                "weather_condition": weather_condition,
                "rain_mm": rain_mm,
                "weather_available": weather_available,
                "complaint_count": complaint_count,
                "historical_recurrence": historical_recurrence,
                "ward_resolved": ward_resolved,
                "time_unresolved_hours": time_unresolved_hours,
                "location_available": location_available,
            },
        )
        factors.append(
            {
                "factor": label,
                "input_value": input_value,
                "present": present_flag,
                "weight": _unit_weight(key, weights),
                "unit": round(_clamp(units.get(key, 0.0)), 3),
                "contribution": contribution,
                "description": _description(key, contribution),
            }
        )
    factors.sort(key=lambda f: -float(f["contribution"]))
    return score, bucket, factors


def _unit_weight(key: str, weights: Weights | None) -> float:
    w = weights or Weights()
    return {
        "severity": w.severity,
        "weather": w.weather,
        "location": w.location,
        "crowd": w.crowd,
        "history": w.history,
        "time": w.time,
    }.get(key, 0.0)


def _input_label(key: str, inputs: dict[str, object]) -> str:
    if key == "severity":
        return str(inputs["severity"] or "LOW")
    if key == "weather":
        condition = inputs.get("weather_condition")
        rain = inputs.get("rain_mm")
        if rain is None:
            return f"{condition or 'n/a'} (no rainfall data)"
        return f"{condition or 'n/a'}, {float(rain):.1f} mm"
    if key == "location":
        if not inputs.get("location_available", True):
            return "lookup unavailable (no claim)"
        return f"{inputs['hospitals']} hosp, {inputs['schools']} school, {inputs['bus_stops']} bus"
    if key == "crowd":
        return f"pop {inputs['population']}, reports {inputs['complaint_count']}"
    if key == "history":
        rec = inputs["historical_recurrence"]
        return f"{rec} same-ward (ward_resolved={inputs['ward_resolved']})"
    if key == "time":
        return f"{float(inputs['time_unresolved_hours']):.1f} h"
    return str(inputs.get(key, ""))


def _description(key: str, contribution: float) -> str:
    """Return a human phrase like "+20 Critical infrastructure proximity"."""
    point = int(round(contribution))
    if point == 0:
        return "no contribution"
    sign = f"+{point}" if point > 0 else str(point)
    names = {
        "severity": "Severity",
        "weather": "Weather risk",
        "location": "Critical infrastructure proximity",
        "crowd": "Multiple reports / population",
        "history": "Historical recurrence",
        "time": "Time unresolved",
    }
    return f"{sign} {names.get(key, key)}"
