"""Feature contract + explainer for Predictive Infrastructure Maintenance.

The infra model blends, per asset: infrastructure age, complaint frequency near
the asset, repair history, current weather (rainfall), and location (ward +
availability). Missing signals degrade to ``0`` with an accompanying
``*_available`` flag so the pipeline always produces a bounded, serializable
feature row — never an error.

``failure_probability`` is a *predicted risk*; ``risk_level`` buckets it using
the configured thresholds and every explanation uses "predicted risk" /
"recommended inspection" phrasing — never a claim that an asset will fail.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from app.core.config import Settings
from app.models.enums import InfrastructureCategory, InfrastructureRiskLevel

# Deterministic ordering of the one-hot category columns.
CATEGORY_ORDER: list[str] = [c.value for c in InfrastructureCategory]


def feature_columns() -> list[str]:
    cols = [
        "age_years",
        "complaints_90d",
        "repairs_12m",
        "rainfall_norm",
        "pop_density",
        "weather_available",
        "age_available",
        "location_available",
    ]
    cols += [f"cat_{c}" for c in CATEGORY_ORDER]
    return cols


def age_years(installed_at: date | datetime | None, reference: datetime) -> float:
    if installed_at is None:
        return 0.0
    if isinstance(installed_at, datetime):
        installed_date = (
            installed_at.date()
            if installed_at.tzinfo is None
            else installed_at.astimezone().date()
        )
    else:
        installed_date = installed_at
    delta = reference.date() - installed_date
    return max(0.0, delta.days / 365.25)


def rainfall_norm(mm: float | None) -> tuple[float, bool]:
    """Normalize rainfall to ~0..1; the availability flag follows the input."""
    if mm is None or mm <= 0:
        return 0.0, False
    return round(min(1.0, math.log1p(mm) / math.log1p(50.0)), 4), True


def pop_norm(residents: float | None) -> float:
    """Ward resident-count proxy normalized to ~0..1 (5000 residents => 1.0)."""
    if residents is None or residents <= 0:
        return 0.0
    return round(min(1.0, residents / 5000.0), 4)


def build_feature_dict(
    *,
    category: str,
    age: float,
    complaints_90d: int,
    repairs_12m: int,
    rainfall_mm: float | None,
    residents: float | None,
    location_available: bool,
) -> dict[str, Any]:
    """Bounded, ordered feature dict consumed by the model at train/inference."""
    rain, weather_available = rainfall_norm(rainfall_mm)
    row: dict[str, Any] = {
        "age_years": round(max(0.0, age), 4),
        "complaints_90d": int(max(0, complaints_90d)),
        "repairs_12m": int(max(0, repairs_12m)),
        "rainfall_norm": rain,
        "pop_density": pop_norm(residents),
        "weather_available": 1 if weather_available else 0,
        "age_available": 1 if age > 0 else 0,
        "location_available": 1 if location_available else 0,
    }
    for cat in CATEGORY_ORDER:
        row[f"cat_{cat}"] = 1 if cat == category else 0
    return row


def risk_level_for_probability(prob: float, settings: Settings) -> InfrastructureRiskLevel:
    if prob >= settings.INFRA_RISK_CRITICAL:
        return InfrastructureRiskLevel.CRITICAL
    if prob >= settings.INFRA_RISK_HIGH:
        return InfrastructureRiskLevel.HIGH
    if prob >= settings.INFRA_RISK_MEDIUM:
        return InfrastructureRiskLevel.MEDIUM
    return InfrastructureRiskLevel.LOW


_RECOMMENDATIONS: dict[InfrastructureRiskLevel, str] = {
    InfrastructureRiskLevel.LOW: (
        "Routine monitoring — keep the asset on the standard maintenance "
        "schedule; no immediate inspection is required."
    ),
    InfrastructureRiskLevel.MEDIUM: (
        "Recommended inspection within the next 90 days to confirm the asset's "
        "current condition."
    ),
    InfrastructureRiskLevel.HIGH: (
        "Prioritized inspection recommended within the next 30 days; verify "
        "asset condition before the next heavy-weather cycle."
    ),
    InfrastructureRiskLevel.CRITICAL: (
        "Urgent technical inspection recommended at the earliest opportunity; "
        "verify the asset's condition before considering any return to service."
    ),
}

# Category-specific, conservative action hint appended for HIGH/CRITICAL levels.
_ACTION_HINTS: dict[str, str] = {
    "WATER_MAIN": "Inspect pipe joints and pressure points along the main.",
    "SEWER": "Inspect the line for blockages and structural settlement.",
    "DRAINAGE": "Inspect the drain structure and clear any debris build-up.",
    "BRIDGE": "Inspect girders, deck joints and support bearings.",
    "ROAD": "Inspect the road surface for cracking and base deterioration.",
    "STREET_LIGHTING": "Inspect poles, wiring and control cabinets.",
    "PARK": "Inspect playground equipment, paths and drainage.",
    "PUBLIC_BUILDING": "Inspect structural, electrical and plumbing systems.",
}


def recommendation_for(risk: InfrastructureRiskLevel, category: str) -> str:
    text = _RECOMMENDATIONS[risk]
    if risk in (InfrastructureRiskLevel.HIGH, InfrastructureRiskLevel.CRITICAL):
        hint = _ACTION_HINTS.get(category)
        if hint:
            text = f"{text} {hint}"
    return text


def supporting_factors_for(
    *,
    category: str,
    age: float,
    age_available: bool,
    complaints_90d: int,
    repairs_12m: int,
    rainfall_mm: float | None,
    ward_label: str | None,
    location_available: bool,
) -> list[str]:
    """Short, human-readable drivers shown alongside a prediction.

    Generated from the *live* value snapshot (never the model's hidden
    weights); the phrasing keeps every item an observed input, not a verdict.
    """
    factors: list[str] = []
    if age_available and age >= 20:
        factors.append(f"Asset age estimated at ~{round(age)} years.")
    if not age_available:
        factors.append("Installation date unavailable - asset age treated as "
                       "unknown for this run.")
    if complaints_90d > 0:
        factors.append(f"{complaints_90d} complaint(s) reported near the asset "
                       f"in the last 90 days.")
    if repairs_12m > 0:
        factors.append(f"{repairs_12m} repair(s) recorded for the asset in the "
                       f"last 12 months.")
    if rainfall_mm is not None and rainfall_mm > 0:
        factors.append("Elevated rainfall now; surface conditions may warrant a "
                       "closer look.")
    if ward_label:
        factors.append(f"Located in {ward_label}.")
    if not location_available:
        factors.append("Location signal unavailable — nearby history was treated "
                       "as none for this run.")
    if repairs_12m >= 2 and repairs_12m > complaints_90d:
        factors.append("Frequent recent repairs suggest this asset needs closer "
                       "monitoring.")
    if not factors:
        factors.append("No strong historical or environmental signals detected.")
    return factors


def recommend_action_text(risk: InfrastructureRiskLevel, category: str) -> str:
    """Concrete proactive action text for a preventive work order."""
    hint = _ACTION_HINTS.get(category) or "Perform a field inspection."
    level = {
        InfrastructureRiskLevel.HIGH: "Prioritized",
        InfrastructureRiskLevel.CRITICAL: "Urgent",
    }.get(risk, "Scheduled")
    return f"{level} preventive inspection — {hint}"
