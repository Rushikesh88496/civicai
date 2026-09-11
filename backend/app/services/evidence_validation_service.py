"""Evidence validation service (Part 28).

Cross-checks AI claims against actual tool/database evidence. For example, if
the AI claims "Hospital = 200m" but GIS data says "Hospital = 670m", the system
records a mismatch (`is_match=False`) with the discrepancy percentage.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Complaint, EvidenceCheck

# Claim type constants.
CLAIM_CATEGORY = "category"
CLAIM_DEPARTMENT = "department"
CLAIM_PRIORITY = "priority"
CLAIM_DISTANCE = "distance"
CLAIM_FACILITY = "facility"

# Distance tolerance (fraction of the larger value) below which we consider
# the claim a match. e.g. 0.25 = within 25% of each other counts as a match.
_DISTANCE_TOLERANCE = 0.25


def _pct_diff(a: float, b: float) -> float | None:
    """Return percent difference between two values (0-100) or None if degenerate."""
    if a == 0 and b == 0:
        return 0.0
    denom = max(abs(a), abs(b))
    if denom == 0:
        return None
    return abs(a - b) / denom * 100.0


async def record_evidence_check(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None,
    decision_id: uuid.UUID | None,
    claim_type: str,
    claimed_value: str,
    actual_value: str | None,
    source: str,
    is_match: bool,
    discrepancy_pct: float | None = None,
    evidence_data: dict | None = None,
    notes: str | None = None,
) -> EvidenceCheck:
    """Persist an evidence cross-check. Does NOT commit."""
    check = EvidenceCheck(
        complaint_id=complaint_id,
        decision_id=decision_id,
        claim_type=claim_type,
        claimed_value=claimed_value,
        actual_value=actual_value,
        source=source,
        is_match=is_match,
        discrepancy_pct=discrepancy_pct,
        evidence_data=evidence_data,
        notes=notes,
    )
    db.add(check)
    await db.flush()
    return check


async def validate_distance_claim(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None,
    decision_id: uuid.UUID | None,
    claimed_metres: float | None,
    actual_metres: float | None,
    facility_name: str,
    facility_lat: float | None = None,
    facility_lon: float | None = None,
) -> EvidenceCheck | None:
    """Validate an AI distance claim against GIS-measured distance."""
    if claimed_metres is None or actual_metres is None:
        return None

    discrepancy = _pct_diff(claimed_metres, actual_metres)
    is_match = discrepancy is not None and discrepancy <= _DISTANCE_TOLERANCE * 100

    evidence_data: dict[str, Any] = {
        "claimed_metres": claimed_metres,
        "actual_metres": actual_metres,
        "facility": facility_name,
    }
    if facility_lat is not None:
        evidence_data["facility_lat"] = facility_lat
    if facility_lon is not None:
        evidence_data["facility_lon"] = facility_lon

    notes = None
    if not is_match:
        notes = (
            f"AI claimed {claimed_metres:.0f}m but GIS reports {actual_metres:.0f}m "
            f"({discrepancy:.0f}% difference) for {facility_name}."
        )

    return await record_evidence_check(
        db,
        complaint_id=complaint_id,
        decision_id=decision_id,
        claim_type=CLAIM_DISTANCE,
        claimed_value=f"{claimed_metres:.0f} m",
        actual_value=f"{actual_metres:.0f} m",
        source="gis",
        is_match=is_match,
        discrepancy_pct=discrepancy,
        evidence_data=evidence_data,
        notes=notes,
    )


async def validate_category_claim(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None,
    decision_id: uuid.UUID | None,
    claimed_category: str | None,
    actual_category: str | None,
) -> EvidenceCheck | None:
    """Validate an AI category claim against the stored/rules category."""
    if claimed_category is None or actual_category is None:
        return None
    is_match = claimed_category.upper() == actual_category.upper()
    return await record_evidence_check(
        db,
        complaint_id=complaint_id,
        decision_id=decision_id,
        claim_type=CLAIM_CATEGORY,
        claimed_value=claimed_category,
        actual_value=actual_category,
        source="rules",
        is_match=is_match,
        discrepancy_pct=0.0 if is_match else 100.0,
        notes=None
        if is_match
        else (f"AI classified as {claimed_category} but rules classify as {actual_category}."),
    )


async def validate_department_claim(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None,
    decision_id: uuid.UUID | None,
    claimed_department: str | None,
    actual_department: str | None,
) -> EvidenceCheck | None:
    """Validate an AI department claim against the category->department map."""
    if claimed_department is None or actual_department is None:
        return None
    is_match = claimed_department.strip().upper() == actual_department.strip().upper()
    return await record_evidence_check(
        db,
        complaint_id=complaint_id,
        decision_id=decision_id,
        claim_type=CLAIM_DEPARTMENT,
        claimed_value=claimed_department,
        actual_value=actual_department,
        source="rules",
        is_match=is_match,
        discrepancy_pct=0.0 if is_match else 100.0,
        notes=None
        if is_match
        else (f"AI routed to {claimed_department} but rules route to {actual_department}."),
    )


async def list_evidence_checks(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[EvidenceCheck]:
    stmt = select(EvidenceCheck).order_by(EvidenceCheck.created_at.desc()).limit(limit)
    if complaint_id is not None:
        stmt = stmt.where(EvidenceCheck.complaint_id == complaint_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_complaint_coordinates(
    db: AsyncSession, complaint_id: uuid.UUID
) -> tuple[float, float] | None:
    """Return (lat, lon) for a complaint's location if available."""
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None or complaint.complaint_location is None:
        return None
    loc = complaint.complaint_location
    if loc.latitude is not None and loc.longitude is not None:
        return (loc.latitude, loc.longitude)
    return None
