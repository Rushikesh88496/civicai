"""Dev-only data reset for CivicAgent (Part 31).

Wipes all *operational / user-generated* data from the development database so
the platform returns to its genuinely-empty, reference-only baseline:

* complaint families (complaints, locations, media, ratings, status/priority/
  department history, correlations, embeddings, AI decision logs, human
  overrides, evidence checks, threads, agent runs/events),
* notifications, work orders (+ activities, photos, status history,
  verifications, worker assignments, preventive work orders),
* infra assets + all predictive model registry rows (hotspot + infra),
* refresh tokens, field workers, ward representatives,
* every user except the bootstrap ``admin@example.com`` SUPER_ADMIN,
* the legacy demo wards (W-001..W-003) **and their demo boundaries**.

REFERENCE data survives: the six roles, the three seed departments, SLA
policies, priority weights, system settings, knowledge documents, critical
locations, category config, the four reference wards (WARD 1..WARD 4, owned by
the migration) and the admin. Non-reference roles/departments (test leftovers,
ad-hoc experiments) are pruned so the roster returns to exactly what
``seed.py`` provides. The reference wards' **boundaries are also kept** so geo
ward-lookup (``ST_Contains``) keeps working after a reset — only boundaries
owned by non-reference wards are removed.

Mirror ``Complaint.user.ward_id`` semantics: after the reset, citizens must
re-register (ward-required) and officers must re-register assets — ML surfaces
report ``INSUFFICIENT_DATA`` until those accumulate.

Usage (from backend/):
    .venv\\Scripts\\python -m scripts.reset_dev_data
or (as part of seeding):
    .venv\\Scripts\\python seed.py --reset

NEVER run against production data.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, func, select

from app.db.session import async_session_factory, engine
from app.models import (
    AgentEvent,
    AgentRun,
    AIDecisionLog,
    AssistantConversation,
    AssistantMessage,
    Complaint,
    ComplaintCorrelation,
    ComplaintDepartmentHistory,
    ComplaintEmbedding,
    ComplaintLocation,
    ComplaintMedia,
    ComplaintPriorityHistory,
    ComplaintRating,
    ComplaintStatusHistory,
    Conversation,
    Department,
    DepartmentOverride,
    EvidenceCheck,
    FieldWorker,
    HumanOverride,
    InfrastructureAsset,
    InfrastructureModel,
    InfrastructurePrediction,
    Message,
    MessageAttachment,
    MessageRead,
    Notification,
    PredictiveModel,
    PreventiveWorkOrder,
    RefreshToken,
    Role,
    User,
    UserProfile,
    Ward,
    WardBoundary,
    WardRepresentative,
    WorkerAssignment,
    WorkOrder,
    WorkOrderActivity,
    WorkOrderPhoto,
    WorkOrderStatusHistory,
    WorkOrderVerification,
)
from app.models.enums import RoleName

# Reference wards + users that a dev reset must never touch.
_REFERENCE_ADMIN_EMAIL = "admin@example.com"
_REFERENCE_WARD_CODES = ("WARD-1", "WARD-2", "WARD-3", "WARD-4")

# Structural reference data the seed owns: the role enum and the three starting
# departments (seed.py ``_DEPARTMENTS``). Anything else (test leftovers, ad-hoc
# admin experiments) is pruned so a dev reset returns the exact seed roster.
_REFERENCE_ROLE_NAMES = {name.value for name in RoleName}
_REFERENCE_DEPARTMENT_CODES = {"PW", "SN", "PR"}

# (model, doc label) — delete order is child-first so no FK RESTRICT fights back.
_OPERATIONAL_TABLES = [
    (MessageRead, "message reads"),
    (MessageAttachment, "message attachments"),
    (Message, "thread messages"),
    (Conversation, "conversations"),
    (AssistantMessage, "assistant messages"),
    (AssistantConversation, "assistant conversations"),
    (Notification, "notifications"),
    (DepartmentOverride, "department overrides"),
    (WorkOrderVerification, "work order verifications"),
    (WorkOrderActivity, "work order activities"),
    (WorkerAssignment, "worker assignments"),
    (WorkOrderPhoto, "work order photos"),
    (WorkOrderStatusHistory, "work order status history"),
    (PreventiveWorkOrder, "preventive work orders"),
    (InfrastructurePrediction, "infrastructure predictions"),
    (InfrastructureAsset, "infrastructure assets"),
    (InfrastructureModel, "infrastructure models"),
    (WorkOrder, "work orders"),
    (ComplaintRating, "complaint ratings"),
    (ComplaintMedia, "complaint media"),
    (ComplaintEmbedding, "complaint embeddings"),
    (ComplaintCorrelation, "complaint correlations"),
    (ComplaintStatusHistory, "complaint status history"),
    (ComplaintPriorityHistory, "complaint priority history"),
    (ComplaintDepartmentHistory, "complaint department history"),
    (ComplaintLocation, "complaint locations"),
    (Complaint, "complaints"),
    (EvidenceCheck, "evidence checks"),
    (HumanOverride, "human overrides"),
    (AIDecisionLog, "AI decision logs"),
    (AgentEvent, "agent events"),
    (AgentRun, "agent runs"),
    (PredictiveModel, "predictive model registry"),
    (RefreshToken, "refresh tokens"),
    (FieldWorker, "field workers"),
    (WardRepresentative, "ward representatives"),
]


async def reset_dev_data(db) -> int:
    """Delete operational data; returns the number of deleted rows."""
    total = 0
    for model, label in _OPERATIONAL_TABLES:
        result = await db.execute(delete(model))
        count = result.rowcount
        if count:
            total += count
            print(f"[reset] removed {count} {label}")
    return total


async def _delete_non_admin_users(db) -> int:
    result = await db.execute(delete(User).where(User.email != _REFERENCE_ADMIN_EMAIL))
    count = result.rowcount
    if count:
        print(f"[reset] removed {count} user accounts (kept {_REFERENCE_ADMIN_EMAIL})")
    return count


async def _delete_non_reference_wards(db) -> int:
    """Remove every ward except the four migration-owned reference wards.

    Includes the legacy demo wards (W-001..W-003) AND any leftovers (test-created
    wards, admin experiments) so a dev reset returns a clean ward roster.
    """
    total = await db.scalar(
        select(func.count(Ward.id)).where(Ward.code.not_in(_REFERENCE_WARD_CODES))
    )
    await db.execute(delete(Ward).where(Ward.code.not_in(_REFERENCE_WARD_CODES)))
    count = int(total or 0)
    if count:
        print(
            f"[reset] removed {count} non-reference wards "
            "(kept WARD-1..WARD-4, including legacy W-001..W-003)"
        )
    return count


async def _prune_roles_and_departments(db) -> tuple[int, int]:
    """Drop roles/departments outside the seed's reference roster.

    Users and field workers are deleted before this runs, and no other table
    holds a FK into ``roles``/``departments``, so pruning is safe. A dev reset
    restores the exact structural roster (six roles, the three starting
    departments) — test leftovers and ad-hoc experiments never survive.
    """
    role_result = await db.execute(delete(Role).where(Role.name.not_in(_REFERENCE_ROLE_NAMES)))
    dept_result = await db.execute(
        delete(Department).where(Department.code.not_in(_REFERENCE_DEPARTMENT_CODES))
    )
    roles = role_result.rowcount or 0
    departments = dept_result.rowcount or 0
    if roles:
        print(f"[reset] removed {roles} non-reference roles")
    if departments:
        print(f"[reset] removed {departments} non-reference departments")
    return roles, departments


async def reset_dev_data_all(db) -> tuple[int, int, int]:
    """Complete dev reset on an open session.

    Wipes operational rows, every user except the bootstrap admin, and every
    non-reference ward (plus their demo boundaries). Reference wards
    (WARD 1..WARD 4), their boundaries, and the rest of the reference data
    survive. Returns ``(operational rows, deleted users, deleted wards)``.
    """
    total_ops = await reset_dev_data(db)
    await db.execute(
        delete(UserProfile).where(
            UserProfile.user_id.in_(select(User.id).where(User.email != _REFERENCE_ADMIN_EMAIL))
        )
    )
    deleted_users = await _delete_non_admin_users(db)
    # Remove boundaries only for non-reference wards (e.g. legacy W-001..W-003).
    # The reference WARD 1-4 boundaries are reference data and MUST survive so
    # geo ward lookup keeps working after a reset.
    await db.execute(
        delete(WardBoundary).where(
            WardBoundary.ward_id.in_(select(Ward.id).where(Ward.code.not_in(_REFERENCE_WARD_CODES)))
        )
    )
    deleted_wards = await _delete_non_reference_wards(db)
    await _prune_roles_and_departments(db)
    await db.commit()
    return total_ops, deleted_users, deleted_wards


async def main() -> None:
    async with async_session_factory() as db:
        total_ops, deleted_users, deleted_wards = await reset_dev_data_all(db)
        print(
            f"\n[reset] dev data reset complete: {total_ops} operational rows, "
            f"{deleted_users} users, {deleted_wards} non-reference wards removed. "
            "Reference data (roles, departments, critical locations, knowledge base, "
            "WARD 1-4) and the bootstrap admin were kept."
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
