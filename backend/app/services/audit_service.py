"""Append-only administrative audit trail (Part 27).

Every mutating Super-Admin Panel action calls ``record_audit`` to persist an
``audit_logs`` row (actor, action verb, affected entity, before/after JSON,
caller IP). Sensitive values are redacted by callers *before* they reach this
service — never store API keys (even masked) in audit rows.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import AuditLog

# Action verbs used across the panel (kept stable for filtering/idempotence).
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_DISABLE = "disable"
ACTION_ENABLE = "enable"
ACTION_DELETE = "delete"
ACTION_CONFIG_SET = "config.set"
ACTION_CONFIG_CLEAR = "config.clear"
ACTION_TEST = "test"
ACTION_DISABLE_USER = "user.disable"
ACTION_ENABLE_USER = "user.enable"

# Extended audit verbs (Part 28 — Security, Audit & AI Governance).
ACTION_LOGIN = "auth.login"
ACTION_LOGOUT = "auth.logout"
ACTION_REGISTER = "auth.register"
ACTION_PASSWORD_RESET = "auth.password_reset"
ACTION_COMPLAINT_CREATE = "complaint.create"
ACTION_COMPLAINT_TRIAGE = "complaint.triage"
ACTION_COMPLAINT_CORRELATE = "complaint.correlate"
ACTION_WORK_ORDER_DISPATCH = "work_order.dispatch"
ACTION_WORK_ORDER_APPROVE = "work_order.approve"
ACTION_WORK_ORDER_ASSIGN = "work_order.assign"
ACTION_WORK_ORDER_REASSIGN = "work_order.reassign"
ACTION_WORK_ORDER_ESCALATE = "work_order.escalate"
ACTION_WORK_ORDER_REJECT = "work_order.reject"
ACTION_ROUTING_OVERRIDE = "routing.override"
ACTION_PRIORITY_OVERRIDE = "priority.override"
ACTION_DEPARTMENT_OVERRIDE = "department.override"

# Resolution-verification + evidence audit verbs (Part 30). The verification
# lifecycle must be auditable end-to-end: worker evidence submission, officer
# evidence review, AI verification start/completion, and each officer decision.
ACTION_WORK_ORDER_EVIDENCE_SUBMITTED = "work_order.evidence_submitted"
ACTION_WORK_ORDER_EVIDENCE_VIEWED = "work_order.evidence_viewed"
ACTION_WORK_ORDER_VERIFICATION_STARTED = "work_order.verification_started"
ACTION_WORK_ORDER_VERIFICATION_COMPLETED = "work_order.verification_completed"
ACTION_WORK_ORDER_RESOLUTION_CONFIRMED = "work_order.resolution_confirmed"
ACTION_WORK_ORDER_REWORK_REQUESTED = "work_order.rework_requested"
ACTION_WORK_ORDER_REOPENED = "work_order.reopened"

# Maximum IP length stored (satisfies IPv6 with room to spare).
_MAX_IP_LEN = 64


async def record_audit(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Persist an audit entry. The caller is responsible for committing later."""
    ip = (ip_address or "")[:_MAX_IP_LEN] or None
    row = AuditLog(
        actor_id=actor_id,
        action=action[:64],
        entity_type=entity_type[:64],
        entity_id=(entity_id or "")[:64] or None,
        before=before,
        after=after,
        ip_address=ip,
    )
    db.add(row)
    await db.flush()
    return row


async def list_audit_logs(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 25,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_id: uuid.UUID | None = None,
    search: str | None = None,
) -> tuple[list[AuditLog], int]:
    """Return (rows, total) for the audit trail, newest first.

    ``search`` is a free-text match against the actor email; ``entity_id`` is an
    exact match (typically a record id or a config key). Page size is capped to
    keep the trail query cheap.
    """
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))

    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conditions.append(AuditLog.entity_id == entity_id)
    if actor_id:
        conditions.append(AuditLog.actor_id == actor_id)
    if search:
        conditions.append(
            AuditLog.actor.has(func.lower(AuditLog.actor.email).contains(search.lower()))
        )

    base = select(AuditLog).options(joinedload(AuditLog.actor))
    if conditions:
        base = base.where(*conditions)

    total_stmt = select(func.count(AuditLog.id))
    if conditions:
        total_stmt = total_stmt.where(*conditions)
    total = await db.scalar(total_stmt)
    rows = (
        (
            await db.execute(
                base.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total or 0)
