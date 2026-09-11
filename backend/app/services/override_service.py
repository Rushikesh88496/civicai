"""Human override service (Part 28).

Stores officer overrides of AI decisions: original decision, new decision,
reason, who made it, and when.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HumanOverride

# Override types.
OVERRIDE_PRIORITY = "priority"
OVERRIDE_DEPARTMENT = "department"
OVERRIDE_ROUTING = "routing"
OVERRIDE_RESOLUTION = "resolution"
OVERRIDE_ASSIGNMENT = "assignment"


async def record_override(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None,
    override_type: str,
    original_value: str | None,
    new_value: str | None,
    reason: str,
    user_id: uuid.UUID | None = None,
    decision_id: uuid.UUID | None = None,
    original_data: dict[str, Any] | None = None,
    new_data: dict[str, Any] | None = None,
) -> HumanOverride:
    """Persist an override. Does NOT commit — caller commits with its tx."""
    override = HumanOverride(
        complaint_id=complaint_id,
        decision_id=decision_id,
        override_type=override_type,
        original_value=original_value,
        new_value=new_value,
        original_data=original_data,
        new_data=new_data,
        reason=reason,
        user_id=user_id,
    )
    db.add(override)
    await db.flush()
    return override


async def list_overrides(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[HumanOverride]:
    stmt = select(HumanOverride).order_by(HumanOverride.created_at.desc()).limit(limit)
    if complaint_id is not None:
        stmt = stmt.where(HumanOverride.complaint_id == complaint_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
