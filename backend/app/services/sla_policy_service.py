"""Runtime-configurable SLA policy service (Part 20).

Resolves the most specific ``sla_policies`` rule for a given
``(priority, department, category)`` triplet and manages the rulebook:

* **Resolution** — among the ACTIVE rules that match the order's three
  dimensions (a rule dimension is a wildcard when ``NULL``), the rule with the
  most non-null dimensions wins. This lets a ``P1/WATER`` rule beat a plain
  ``P1`` rule for a water emergency without losing the P1 default for
  everything else.
* **CRUD** — validate rule shapes (positive hours, ``0 < at_risk_percent <= 1``,
  no duplicate specificity tuples) so the rulebook stays unambiguous.

The built-in P1..P4 defaults come from the ``e2e3f4a5b6c7`` migration; officers
can add department- / category-scoped rules on top at runtime.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SlaPolicy


class SlaPolicyNotFoundError(Exception):
    """Raised when a policy id does not exist."""


class SlaPolicyValidationError(Exception):
    """Raised when a rule shape is invalid (bad hours / percent / duplicate)."""


def _specificity(rule: SlaPolicy) -> int:
    """Number of concrete dimensions a rule constrains (higher = more specific)."""
    return sum(1 for v in (rule.priority, rule.department, rule.category) if v)


async def resolve(
    db: AsyncSession,
    *,
    priority: str | None,
    department: str | None,
    category: str | None,
) -> SlaPolicy | None:
    """Resolve the most specific ACTIVE policy for the given dimensions.

    Wildcard rule dimensions (``NULL``) match anything; the rule with the most
    matching concrete dimensions wins. Returns ``None`` when no ACTIVE rule
    matches (the caller then keeps the order's pre-existing SLA values).
    """
    rows = (await db.execute(select(SlaPolicy).where(SlaPolicy.active.is_(True)))).scalars().all()
    matched: list[SlaPolicy] = []
    for rule in rows:
        if rule.priority is not None and rule.priority != priority:
            continue
        if rule.department is not None and rule.department != department:
            continue
        if rule.category is not None and rule.category != category:
            continue
        matched.append(rule)
    if not matched:
        return None
    matched.sort(key=lambda r: (_specificity(r), r.updated_at or r.created_at), reverse=True)
    return matched[0]


async def _duplicate_exists(
    db: AsyncSession,
    *,
    priority: str | None,
    department: str | None,
    category: str | None,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """True when an identical (priority, department, category) rule already exists.

    ``NULL``-safe: two all-wildcard rules or two ``P1`` rules are both treated as
    duplicates regardless of which columns are null. The specificity tie-break
    in :func:`resolve` would otherwise be ambiguous.
    """
    from sqlalchemy import and_

    stmt = select(SlaPolicy.id).where(
        and_(
            SlaPolicy.priority.is_(None) if priority is None else SlaPolicy.priority == priority,
            SlaPolicy.department.is_(None)
            if department is None
            else SlaPolicy.department == department,
            SlaPolicy.category.is_(None) if category is None else SlaPolicy.category == category,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(SlaPolicy.id != exclude_id)
    return (await db.scalar(stmt.limit(1))) is not None


async def list_policies(db: AsyncSession) -> list[SlaPolicy]:
    rows = (
        (
            await db.execute(
                select(SlaPolicy).order_by(
                    SlaPolicy.active.desc(),
                    SlaPolicy.priority.is_(None),
                    SlaPolicy.priority,
                    SlaPolicy.department.is_(None),
                    SlaPolicy.department,
                    SlaPolicy.category.is_(None),
                    SlaPolicy.category,
                    SlaPolicy.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def get_policy(db: AsyncSession, policy_id: uuid.UUID) -> SlaPolicy:
    rule = await db.scalar(select(SlaPolicy).where(SlaPolicy.id == policy_id))
    if rule is None:
        raise SlaPolicyNotFoundError("SLA policy not found.")
    return rule


def _validate(
    *,
    sla_hours: int,
    at_risk_percent: float,
    priority: str | None,
    department: str | None,
    category: str | None,
) -> None:
    if sla_hours <= 0:
        raise SlaPolicyValidationError("sla_hours must be a positive number of hours.")
    if not 0 < at_risk_percent <= 1:
        raise SlaPolicyValidationError("at_risk_percent must be between 0 (exclusive) and 1.")
    # Guard against nonsense: a rule must constrain at least one dimension.
    if not any((priority, department, category)):
        raise SlaPolicyValidationError(
            "An SLA rule must constrain at least one of priority, department or category."
        )


async def create_policy(
    db: AsyncSession,
    *,
    name: str | None,
    priority: str | None,
    department: str | None,
    category: str | None,
    sla_hours: int,
    at_risk_percent: float,
    escalate_on_breach: bool,
    active: bool,
    actor_id: uuid.UUID | None = None,
) -> SlaPolicy:
    priority = priority.upper().strip() if priority else None
    department = department.upper().strip() if department else None
    category = category.upper().strip() if category else None
    _validate(
        sla_hours=sla_hours,
        at_risk_percent=at_risk_percent,
        priority=priority,
        department=department,
        category=category,
    )
    if await _duplicate_exists(db, priority=priority, department=department, category=category):
        raise SlaPolicyValidationError(
            "A rule with the same priority/department/category already exists."
        )
    rule = SlaPolicy(
        name=(name or "").strip()[:120] or None,
        priority=priority,
        department=department,
        category=category,
        sla_hours=sla_hours,
        at_risk_percent=at_risk_percent,
        escalate_on_breach=escalate_on_breach,
        active=active,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def update_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    *,
    name: str | None,
    priority: str | None,
    department: str | None,
    category: str | None,
    sla_hours: int,
    at_risk_percent: float,
    escalate_on_breach: bool,
    active: bool,
    actor_id: uuid.UUID | None = None,
) -> SlaPolicy:
    rule = await get_policy(db, policy_id)
    priority = priority.upper().strip() if priority else None
    department = department.upper().strip() if department else None
    category = category.upper().strip() if category else None
    _validate(
        sla_hours=sla_hours,
        at_risk_percent=at_risk_percent,
        priority=priority,
        department=department,
        category=category,
    )
    if await _duplicate_exists(
        db,
        priority=priority,
        department=department,
        category=category,
        exclude_id=policy_id,
    ):
        raise SlaPolicyValidationError(
            "A rule with the same priority/department/category already exists."
        )
    rule.name = (name or "").strip()[:120] or None
    rule.priority = priority
    rule.department = department
    rule.category = category
    rule.sla_hours = sla_hours
    rule.at_risk_percent = at_risk_percent
    rule.escalate_on_breach = escalate_on_breach
    rule.active = active
    rule.updated_by = actor_id
    await db.commit()
    await db.refresh(rule)
    return rule


async def delete_policy(db: AsyncSession, policy_id: uuid.UUID) -> None:
    await get_policy(db, policy_id)
    await db.execute(sa_delete(SlaPolicy).where(SlaPolicy.id == policy_id))
    await db.commit()
