"""Deterministic Department Routing Engine (Part 13).

Pure, dependency-free logic that maps a complaint's category — fused with the
latest triage / vision / priority / context signal runs — onto one of the seven
fixed departments:

* ``WATER``            — drinking water, pipe bursts, water leaks.
* ``ROADS``            — potholes, road damage.
* ``ELECTRICAL``       — power outages, street / public lighting.
* ``WASTE``            — garbage collection, sanitation.
* ``DRAINAGE``         — drainage, sewerage, monsoon water-logging.
* ``PARKS``            — public parks and green spaces, fallen trees.
* ``EMERGENCY_DISASTER`` — public-safety hazards, disasters.

The engine is fully deterministic — **no LLM ever chooses the department**. It
returns ``primary_department``, ``secondary_departments`` (for multi-department
issues such as Flooding → Drainage + Roads, or fallen electrical infrastructure →
Electrical + Emergency), an explainable ``routing_reason``, and a confidence in
0..1 derived from how clearly the category is recognized plus corroborating
signals. Unrecognized / ambiguous categories are surfaced so a human can review
rather than being silently mis-routed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import (
    DEPARTMENT_LABELS,
    ComplaintCategory,
    DepartmentCode,
    DynamicPriority,
)


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
@dataclass
class RoutingSignals:
    """Corroborating signals absorbed from the upstream agents (all optional).

    Every signal is optional and degrades to neutral when unavailable, so the
    engine can always produce a deterministic decision.
    """

    # --- Triage ---
    triage_severity: str | None = None  # LOW / MEDIUM / HIGH / CRITICAL
    triage_confidence: float | None = None  # 0..1
    # --- Vision ---
    vision_severity: str | None = None  # LOW / MEDIUM / HIGH / CRITICAL
    vision_confidence: float | None = None  # 0..1
    # --- Priority ---
    priority_score: int | None = None  # 0..100
    priority_bucket: str | None = None  # P1_CRITICAL ... P4_LOW
    # --- Context ---
    weather_condition: str | None = None  # "Heavy rain", "Clear", ...
    infrastructure_hospitals: int = 0
    infrastructure_schools: int = 0
    infrastructure_bus_stops: int = 0


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #
@dataclass
class RoutingDecision:
    primary_department: DepartmentCode
    secondary_departments: list[DepartmentCode] = field(default_factory=list)
    routing_reason: str = ""
    confidence: float = 0.0
    ambiguous: bool = False

    @property
    def secondary_values(self) -> list[str]:
        return [d.value for d in self.secondary_departments]


# --------------------------------------------------------------------------- #
# Category -> department routing matrix
# --------------------------------------------------------------------------- #
_CATEGORY_PRIMARY: dict[ComplaintCategory, DepartmentCode] = {
    ComplaintCategory.WATER: DepartmentCode.WATER,
    ComplaintCategory.WATER_LEAK: DepartmentCode.WATER,
    ComplaintCategory.ROAD: DepartmentCode.ROADS,
    ComplaintCategory.ELECTRICITY: DepartmentCode.ELECTRICAL,
    ComplaintCategory.STREET_LIGHTING: DepartmentCode.ELECTRICAL,
    ComplaintCategory.GARBAGE: DepartmentCode.WASTE,
    ComplaintCategory.SANITATION: DepartmentCode.WASTE,
    ComplaintCategory.DRAINAGE: DepartmentCode.DRAINAGE,
    ComplaintCategory.FLOODING: DepartmentCode.DRAINAGE,
    ComplaintCategory.PARKS: DepartmentCode.PARKS,
    ComplaintCategory.FALLEN_TREE: DepartmentCode.PARKS,
    ComplaintCategory.PUBLIC_SAFETY: DepartmentCode.EMERGENCY_DISASTER,
}

# Fallen / exposed / collided electrical infrastructure amplifies an ELECTRICAL
# complaint to also involve Emergency / Disaster (person-safety coordination).
_ELECTRICAL_EMERGENCY_HINTS = (
    "fallen",
    "downed",
    "exposed",
    "spark",
    "live wire",
    "pole down",
    "collapsed pole",
    "broke",
    "snapped",
)

_MULTI_DEPARTMENT: dict[ComplaintCategory, list[DepartmentCode]] = {
    # Flooding is primarily a drainage problem, but the standing water affects
    # roads — so Roads collaborates.
    ComplaintCategory.FLOODING: [DepartmentCode.DRAINAGE, DepartmentCode.ROADS],
    ComplaintCategory.ELECTRICITY: [],  # filled dynamically from the description.
}


def _plural(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _is_fallen_electrical(description: str | None) -> bool:
    if not description:
        return False
    lowered = description.lower()
    return any(h in lowered for h in _ELECTRICAL_EMERGENCY_HINTS)


def _dept_label(code: DepartmentCode) -> str:
    return DEPARTMENT_LABELS.get(code.value, code.value)


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def _base_routing(
    category: ComplaintCategory,
    description: str | None,
    settings,
) -> tuple[DepartmentCode, list[DepartmentCode], bool, str]:
    """Return (primary, secondary, is_multi, base_reason) for a known category."""

    # Multi-department: flooding -> Drainage + Roads.
    if category == ComplaintCategory.FLOODING:
        primary = DepartmentCode.DRAINAGE
        secondary = [DepartmentCode.ROADS]
        reason = (
            f"Flooding is a drainage-dominant issue, but standing water also "
            f"impedes roads — route to {_dept_label(DepartmentCode.DRAINAGE)} "
            f"with cross-coordination to {_dept_label(DepartmentCode.ROADS)}."
        )
        return primary, secondary, True, reason

    primary = _CATEGORY_PRIMARY[category]

    # Multi-department: fallen / exposed electrical infrastructure -> Electrical
    # + Emergency / Disaster.
    if category == ComplaintCategory.ELECTRICITY and _is_fallen_electrical(description):
        secondary = [DepartmentCode.EMERGENCY_DISASTER]
        reason = (
            f"Fallen/exposed electrical infrastructure is an Electrical issue "
            f"that poses an immediate safety hazard — route to "
            f"{_dept_label(DepartmentCode.ELECTRICAL)} with "
            f"{_dept_label(DepartmentCode.EMERGENCY_DISASTER)} coordination."
        )
        return primary, secondary, True, reason

    secondary: list[DepartmentCode] = []
    reason = (
        f"The complaint's category ({category.value.replace('_', ' ').title()}) "
        f"maps to {_dept_label(primary)} as the responsible department."
    )
    return primary, secondary, False, reason


def _confidence(
    known: bool,
    is_multi: bool,
    severity_max: str | None,
    priority_bucket: str | None,
    settings,
) -> float:
    """Deterministic 0..1 confidence in the routing decision."""
    if not known:
        return float(settings.ROUTING_CONFIDENCE_UNKNOWN)

    base = (
        float(settings.ROUTING_CONFIDENCE_MULTI)
        if is_multi
        else float(settings.ROUTING_CONFIDENCE_KNOWN)
    )
    # Reinforce when upstream signals indicate an acute / high-priority issue.
    boost = 0.0
    if severity_max in ("HIGH", "CRITICAL"):
        boost += float(settings.ROUTING_CONFIDENCE_PRIORITY_BOOST)
    if priority_bucket in (
        DynamicPriority.P1_CRITICAL.value,
        DynamicPriority.P2_HIGH.value,
    ):
        boost += float(settings.ROUTING_CONFIDENCE_PRIORITY_BOOST)
    return round(min(1.0, base + boost), 3)


def route_complaint(
    category: ComplaintCategory,
    *,
    description: str | None = None,
    signals: RoutingSignals | None = None,
    settings=None,
) -> RoutingDecision:
    """Deterministically route a complaint to a department.

    ``category`` is required. ``description`` is used only for the multi-department
    fallen-electrical heuristic. ``signals`` (triage/vision/priority/context) tune
    confidence and contribute to the reasoning. ``settings`` supplies the confidence
    knobs (falls back to the configured defaults when omitted).
    """
    from app.core.config import get_settings

    settings = settings or get_settings()
    signals = signals or RoutingSignals()

    if category not in _CATEGORY_PRIMARY:
        # Unknown / OTHER category — surface as ambiguous rather than guessing.
        ambiguity_reason = (
            f"The category ({category.value}) is not among the routable "
            f"departments, so routing is ambiguous and a human decision is recommended."
        )
        return RoutingDecision(
            primary_department=DepartmentCode.DRAINAGE,
            secondary_departments=[],
            routing_reason=ambiguity_reason,
            confidence=float(settings.ROUTING_CONFIDENCE_UNKNOWN),
            ambiguous=True,
        )

    primary, secondary, is_multi, reason = _base_routing(category, description, settings)

    # Always attach the fallback/ambiguous flag consistently.
    return RoutingDecision(
        primary_department=primary,
        secondary_departments=secondary,
        routing_reason=reason,
        confidence=_confidence(
            known=True,
            is_multi=is_multi,
            severity_max=_max_severity(signals),
            priority_bucket=signals.priority_bucket,
            settings=settings,
        ),
        ambiguous=False,
    )


def _max_severity(signals: RoutingSignals) -> str | None:
    """Highest severity reported by the triage / vision agents (deterministic)."""
    severities = [s for s in (signals.triage_severity, signals.vision_severity) if s]
    if not severities:
        return None
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    return max(severities, key=lambda s: order.get(s, 0))


__all__ = ["RoutingDecision", "RoutingSignals", "route_complaint"]
