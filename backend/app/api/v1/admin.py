"""Super-Admin Panel API (Part 27).

Every manager endpoint is restricted to ``SUPER_ADMIN`` and every mutating
action writes an ``audit_logs`` row. Secrets are never returned through these
endpoints — configuration responses expose only a ``configured`` flag and a
masked preview; raw API keys live only in the environment or Fernet-encrypted
at rest.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import (
    AuditLog,
    ComplaintCategoryConfig,
    Department,
    FieldWorker,
    PriorityWeight,
    Role,
    SlaPolicy,
    SystemSetting,
    User,
    Ward,
    WardRepresentative,
)
from app.models.enums import RoleName
from app.schemas.admin import (
    AdminSummary,
    AuditLogOut,
    AuditLogsPage,
    ComplaintCategoryIn,
    ComplaintCategoryOut,
    ComplaintCategoryUpdate,
    ConfigItemOut,
    ConfigTestOut,
    ConfigUpdateIn,
    DepartmentIn,
    DepartmentOut,
    DepartmentsPage,
    DepartmentUpdate,
    FieldWorkerOut,
    FieldWorkersPage,
    FieldWorkerUpdate,
    PriorityWeightIn,
    PriorityWeightOut,
    PriorityWeightUpdate,
    RepresentativeOut,
    RepresentativesPage,
    RepresentativeUpdate,
    RoleIn,
    RoleListItem,
    RoleOut,
    RoleUpdate,
    UserAdminCreate,
    UserAdminOut,
    UserAdminUpdate,
    UsersPage,
    WardIn,
    WardOut,
    WardsPage,
    WardUpdate,
)
from app.schemas.sla import SlaPolicyIn, SlaPolicyOut
from app.services import admin_config_service, admin_service, audit_service, sla_policy_service
from app.services.admin_service import _user_audit_payload

router = APIRouter(prefix="/admin", tags=["admin"])

_SA = Depends(require_roles(RoleName.SUPER_ADMIN.value))


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


async def _load_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(
            joinedload(User.field_worker),
            joinedload(User.ward_representative),
            joinedload(User.ward),
            joinedload(User.role),
        )
    )


def _serialize(obj) -> dict | None:
    """Best-effort, secret-free serialization for audit snapshots."""
    if obj is None:
        return None
    if hasattr(obj, "__table__"):
        return _model_audit_payload(obj)
    if isinstance(obj, dict):
        return {
            str(k): v
            for k, v in obj.items()
            if str(k) not in {"password", "password_hash", "value", "token", "secret"}
        }
    return {"value": str(obj)}


def _model_audit_payload(obj) -> dict:
    table = obj.__table__
    payload: dict = {}
    for column in table.columns:
        key = column.name
        if key in {"password_hash", "value", "token"}:
            continue  # never capture secrets in the audit trail
        value = getattr(obj, key, None)
        if isinstance(value, (uuid.UUID,)):
            value = str(value)
        elif isinstance(value, (datetime, date)):
            value = value.isoformat()
        else:
            try:
                _ = jsonable_encoder(value)
            except Exception:  # noqa: BLE001
                value = str(value)
        if key == "role_id":
            value = getattr(obj, "role", None) and getattr(obj.role, "name", None)
        payload[key] = value
    return payload


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
@router.get("/summary", response_model=AdminSummary)
async def admin_summary(
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> AdminSummary:
    counts = {
        t: await db.scalar(select(func.count(t.id))) or 0 for t in (User, Role, Ward, Department)
    }
    return AdminSummary(
        users=counts[User],
        active_users=(
            await db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
        ),
        roles=counts[Role],
        wards=counts[Ward],
        active_wards=(
            await db.scalar(select(func.count(Ward.id)).where(Ward.is_active.is_(True))) or 0
        ),
        departments=counts[Department],
        field_workers=await db.scalar(select(func.count(FieldWorker.id))) or 0,
        representatives=await db.scalar(select(func.count(WardRepresentative.id))) or 0,
        complaint_categories=await db.scalar(select(func.count(ComplaintCategoryConfig.id))) or 0,
        system_settings=await db.scalar(select(func.count(SystemSetting.id))) or 0,
        audit_logs=await db.scalar(select(func.count(AuditLog.id))) or 0,
    )


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
@router.get("/users", response_model=UsersPage)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    ward_code: str | None = None,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> UsersPage:
    items, total = await admin_service.list_users(
        db,
        page=page,
        page_size=page_size,
        search=search,
        role=role,
        is_active=is_active,
        ward_code=ward_code,
    )
    return UsersPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/users/{user_id}", response_model=UserAdminOut)
async def get_user(
    user_id: uuid.UUID,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> UserAdminOut:
    return await admin_service.get_user(db, user_id)


@router.post("/users", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserAdminCreate,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> UserAdminOut:
    created = await admin_service.create_user(db, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_CREATE,
        entity_type="user",
        entity_id=str(created.id),
        after=_user_audit_payload(await _load_user(db, created.id)),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return created


@router.put("/users/{user_id}", response_model=UserAdminOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
    request: Request,
    actor: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> UserAdminOut:
    before_user = await _load_user(db, user_id)
    before = admin_service._user_audit_payload(before_user) if before_user else None
    if before is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    updated = await admin_service.update_user(db, user_id, payload, actor=actor)
    await audit_service.record_audit(
        db,
        actor_id=actor.id,
        action=audit_service.ACTION_UPDATE,
        entity_type="user",
        entity_id=str(user_id),
        before=before,
        after=admin_service._user_audit_payload(await _load_user(db, user_id)),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return updated


@router.patch("/users/{user_id}/disable", response_model=UserAdminOut)
async def disable_user(
    user_id: uuid.UUID,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> UserAdminOut:
    before_user = await _load_user(db, user_id)
    before = admin_service._user_audit_payload(before_user) if before_user else None
    updated = await admin_service.set_user_active(db, actor=user, user_id=user_id, is_active=False)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_DISABLE_USER,
        entity_type="user",
        entity_id=str(user_id),
        before=before,
        after=admin_service._user_audit_payload(await _load_user(db, user_id)),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return updated


@router.patch("/users/{user_id}/enable", response_model=UserAdminOut)
async def enable_user(
    user_id: uuid.UUID,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> UserAdminOut:
    before_user = await _load_user(db, user_id)
    before = admin_service._user_audit_payload(before_user) if before_user else None
    updated = await admin_service.set_user_active(db, actor=user, user_id=user_id, is_active=True)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_ENABLE_USER,
        entity_type="user",
        entity_id=str(user_id),
        before=before,
        after=admin_service._user_audit_payload(await db.get(User, user_id)),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return updated


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
@router.get("/roles", response_model=list[RoleListItem])
async def list_roles(
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> list[RoleListItem]:
    rows = await admin_service.list_roles(db)
    return [RoleListItem.model_validate(row) for row in rows]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleIn,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> RoleOut:
    role = await admin_service.create_role(db, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_CREATE,
        entity_type="role",
        entity_id=str(role.id),
        after=_model_audit_payload(role),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return RoleOut.model_validate(role)


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdate,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> RoleOut:
    role = await db.get(Role, role_id)
    before = _model_audit_payload(role) if role else None
    updated = await admin_service.update_role(db, role_id, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_UPDATE,
        entity_type="role",
        entity_id=str(role_id),
        before=before,
        after=_model_audit_payload(updated),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return RoleOut.model_validate(updated)


# --------------------------------------------------------------------------- #
# Wards & Departments
# --------------------------------------------------------------------------- #
@router.get("/wards", response_model=WardsPage)
async def list_wards(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    is_active: bool | None = None,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> WardsPage:
    items, total = await admin_service.list_wards(
        db, page=page, page_size=page_size, search=search, is_active=is_active
    )
    return WardsPage(
        items=[WardOut.model_validate(w) for w in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/wards", response_model=WardOut, status_code=status.HTTP_201_CREATED)
async def create_ward(
    payload: WardIn,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> WardOut:
    ward = await admin_service.create_ward(db, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_CREATE,
        entity_type="ward",
        entity_id=str(ward.id),
        after=_model_audit_payload(ward),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return WardOut.model_validate(ward)


@router.patch("/wards/{ward_id}", response_model=WardOut)
async def update_ward(
    ward_id: uuid.UUID,
    payload: WardUpdate,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> WardOut:
    ward = await db.get(Ward, ward_id)
    before = _model_audit_payload(ward) if ward else None
    updated = await admin_service.update_ward(db, ward_id, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_UPDATE,
        entity_type="ward",
        entity_id=str(ward_id),
        before=before,
        after=_model_audit_payload(updated),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return WardOut.model_validate(updated)


@router.get("/departments", response_model=DepartmentsPage)
async def list_departments(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    is_active: bool | None = None,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> DepartmentsPage:
    items, total = await admin_service.list_departments(
        db, page=page, page_size=page_size, search=search, is_active=is_active
    )
    return DepartmentsPage(
        items=[DepartmentOut.model_validate(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentIn,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> DepartmentOut:
    dept = await admin_service.create_department(db, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_CREATE,
        entity_type="department",
        entity_id=str(dept.id),
        after=_model_audit_payload(dept),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return DepartmentOut.model_validate(dept)


@router.patch("/departments/{dept_id}", response_model=DepartmentOut)
async def update_department(
    dept_id: uuid.UUID,
    payload: DepartmentUpdate,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> DepartmentOut:
    dept = await db.get(Department, dept_id)
    before = _model_audit_payload(dept) if dept else None
    updated = await admin_service.update_department(db, dept_id, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_UPDATE,
        entity_type="department",
        entity_id=str(dept_id),
        before=before,
        after=_model_audit_payload(updated),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return DepartmentOut.model_validate(updated)


# --------------------------------------------------------------------------- #
# Field workers
# --------------------------------------------------------------------------- #
@router.get("/field-workers", response_model=FieldWorkersPage)
async def list_field_workers(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    department_code: str | None = None,
    status_filter: str | None = Query(None, description="ACTIVE|INACTIVE|ON_LEAVE"),
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> FieldWorkersPage:
    items, total = await admin_service.list_field_workers(
        db,
        page=page,
        page_size=page_size,
        search=search,
        department_code=department_code,
        status_filter=status_filter,
    )
    return FieldWorkersPage(items=items, total=total, page=page, page_size=page_size)


@router.patch("/field-workers/{worker_id}", response_model=FieldWorkerOut)
async def update_field_worker(
    worker_id: uuid.UUID,
    payload: FieldWorkerUpdate,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> FieldWorkerOut:
    worker = await db.get(FieldWorker, worker_id)
    before = _model_audit_payload(worker) if worker else None
    updated = await admin_service.update_field_worker(db, worker_id, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_UPDATE,
        entity_type="field_worker",
        entity_id=str(worker_id),
        before=before,
        after=_model_audit_payload(await db.get(FieldWorker, worker_id)),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return updated


# --------------------------------------------------------------------------- #
# Ward representatives
# --------------------------------------------------------------------------- #
@router.get("/representatives", response_model=RepresentativesPage)
async def list_representatives(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    ward_code: str | None = None,
    status_filter: str | None = Query(None, description="ACTIVE|INACTIVE|SUSPENDED"),
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> RepresentativesPage:
    items, total = await admin_service.list_representatives(
        db,
        page=page,
        page_size=page_size,
        search=search,
        ward_code=ward_code,
        status_filter=status_filter,
    )
    return RepresentativesPage(items=items, total=total, page=page, page_size=page_size)


@router.patch("/representatives/{rep_id}", response_model=RepresentativeOut)
async def update_representative(
    rep_id: uuid.UUID,
    payload: RepresentativeUpdate,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> RepresentativeOut:
    rep = await db.get(WardRepresentative, rep_id)
    before = _model_audit_payload(rep) if rep else None
    updated = await admin_service.update_representative(db, rep_id, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_UPDATE,
        entity_type="representative",
        entity_id=str(rep_id),
        before=before,
        after=_model_audit_payload(await db.get(WardRepresentative, rep_id)),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return updated


# --------------------------------------------------------------------------- #
# Complaint categories
# --------------------------------------------------------------------------- #
@router.get("/complaint-categories", response_model=list[ComplaintCategoryOut])
async def list_complaint_categories(
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> list[ComplaintCategoryOut]:
    rows = await admin_service.list_complaint_categories(db)
    return [ComplaintCategoryOut.model_validate(r) for r in rows]


@router.post(
    "/complaint-categories",
    response_model=ComplaintCategoryOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_complaint_category(
    payload: ComplaintCategoryIn,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> ComplaintCategoryOut:
    row = await admin_service.create_complaint_category(db, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_CREATE,
        entity_type="complaint_category",
        entity_id=str(row.id),
        after=_model_audit_payload(row),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return ComplaintCategoryOut.model_validate(row)


@router.patch("/complaint-categories/{category_id}", response_model=ComplaintCategoryOut)
async def update_complaint_category(
    category_id: uuid.UUID,
    payload: ComplaintCategoryUpdate,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> ComplaintCategoryOut:
    row = await db.get(ComplaintCategoryConfig, category_id)
    before = _model_audit_payload(row) if row else None
    updated = await admin_service.update_complaint_category(db, category_id, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_UPDATE,
        entity_type="complaint_category",
        entity_id=str(category_id),
        before=before,
        after=_model_audit_payload(updated),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return ComplaintCategoryOut.model_validate(updated)


# --------------------------------------------------------------------------- #
# Priority weights
# --------------------------------------------------------------------------- #
@router.get("/priority-weights", response_model=list[PriorityWeightOut])
async def list_priority_weights(
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> list[PriorityWeightOut]:
    rows = await admin_service.list_priority_weights(db)
    return [PriorityWeightOut.model_validate(r) for r in rows]


@router.post(
    "/priority-weights",
    response_model=PriorityWeightOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_priority_weight(
    payload: PriorityWeightIn,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> PriorityWeightOut:
    row = await admin_service.create_priority_weight(db, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_CREATE,
        entity_type="priority_weight",
        entity_id=str(row.id),
        after=_model_audit_payload(row),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return PriorityWeightOut.model_validate(row)


@router.patch("/priority-weights/{weight_id}", response_model=PriorityWeightOut)
async def update_priority_weight(
    weight_id: uuid.UUID,
    payload: PriorityWeightUpdate,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> PriorityWeightOut:
    row = await db.get(PriorityWeight, weight_id)
    before = _model_audit_payload(row) if row else None
    updated = await admin_service.update_priority_weight(db, weight_id, payload)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_UPDATE,
        entity_type="priority_weight",
        entity_id=str(weight_id),
        before=before,
        after=_model_audit_payload(updated),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return PriorityWeightOut.model_validate(updated)


# --------------------------------------------------------------------------- #
# SLA rules (admin-managed rulebook)
# --------------------------------------------------------------------------- #
def _policy_error(exc: Exception) -> HTTPException:
    if isinstance(exc, sla_policy_service.SlaPolicyNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, sla_policy_service.SlaPolicyValidationError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))


@router.get("/sla/policies", response_model=list[SlaPolicyOut])
async def list_sla_policies(
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> list[SlaPolicyOut]:
    rows = await sla_policy_service.list_policies(db)
    return [SlaPolicyOut.model_validate(r) for r in rows]


@router.post("/sla/policies", response_model=SlaPolicyOut, status_code=status.HTTP_201_CREATED)
async def create_sla_policy(
    payload: SlaPolicyIn,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> SlaPolicyOut:
    try:
        rule = await sla_policy_service.create_policy(
            db,
            name=payload.name,
            priority=payload.priority.value if payload.priority else None,
            department=payload.department.value if payload.department else None,
            category=payload.category.value if payload.category else None,
            sla_hours=payload.sla_hours,
            at_risk_percent=payload.at_risk_percent,
            escalate_on_breach=payload.escalate_on_breach,
            active=payload.active,
            actor_id=user.id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _policy_error(exc) from exc
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_CREATE,
        entity_type="sla_policy",
        entity_id=str(rule.id),
        after=_model_audit_payload(rule),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return SlaPolicyOut.model_validate(rule)


@router.put("/sla/policies/{policy_id}", response_model=SlaPolicyOut)
async def update_sla_policy(
    policy_id: uuid.UUID,
    payload: SlaPolicyIn,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> SlaPolicyOut:
    try:
        rule = await sla_policy_service.update_policy(
            db,
            policy_id,
            name=payload.name,
            priority=payload.priority.value if payload.priority else None,
            department=payload.department.value if payload.department else None,
            category=payload.category.value if payload.category else None,
            sla_hours=payload.sla_hours,
            at_risk_percent=payload.at_risk_percent,
            escalate_on_breach=payload.escalate_on_breach,
            active=payload.active,
            actor_id=user.id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _policy_error(exc) from exc
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_UPDATE,
        entity_type="sla_policy",
        entity_id=str(policy_id),
        after=_model_audit_payload(rule),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return SlaPolicyOut.model_validate(rule)


@router.delete("/sla/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sla_policy(
    policy_id: uuid.UUID,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = await db.get(SlaPolicy, policy_id)
    before = _model_audit_payload(rule) if rule else None
    try:
        await sla_policy_service.delete_policy(db, policy_id)
    except Exception as exc:  # noqa: BLE001
        raise _policy_error(exc) from exc
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_DELETE,
        entity_type="sla_policy",
        entity_id=str(policy_id),
        before=before,
        ip_address=_client_ip(request),
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# System configuration & integrations (secure — no secrets in responses)
# --------------------------------------------------------------------------- #
@router.get("/config", response_model=list[ConfigItemOut])
async def list_config(
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> list[ConfigItemOut]:
    return await admin_config_service.list_config(db)


@router.patch("/config/{key}", response_model=ConfigItemOut)
async def update_config(
    key: str,
    payload: ConfigUpdateIn,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> ConfigItemOut:
    await admin_config_service.update_config(
        db, key=key, value=payload.value, clear=payload.value is None, actor_id=user.id
    )
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=(
            audit_service.ACTION_CONFIG_SET
            if payload.value is not None
            else audit_service.ACTION_CONFIG_CLEAR
        ),
        entity_type="system_config",
        entity_id=key,
        ip_address=_client_ip(request),
    )
    await db.commit()
    items = {item.key: item for item in await admin_config_service.list_config(db)}
    return items[key]


@router.delete("/config/{key}", response_model=ConfigItemOut)
async def clear_config(
    key: str,
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> ConfigItemOut:
    await admin_config_service.clear_config(db, key=key, actor_id=user.id)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_CONFIG_CLEAR,
        entity_type="system_config",
        entity_id=key,
        ip_address=_client_ip(request),
    )
    await db.commit()
    items = {item.key: item for item in await admin_config_service.list_config(db)}
    return items[key]


@router.post("/config/groq/test", response_model=ConfigTestOut)
async def test_groq_config(
    request: Request,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> ConfigTestOut:
    result = await admin_config_service.test_groq(db)
    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action=audit_service.ACTION_TEST,
        entity_type="system_config",
        entity_id="GROQ_API_KEY",
        after={"reachable": result.reachable, "configured": result.configured},
        ip_address=_client_ip(request),
    )
    await db.commit()
    return result


# --------------------------------------------------------------------------- #
# Audit trail
# --------------------------------------------------------------------------- #
@router.get("/audit-logs", response_model=AuditLogsPage)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_id: uuid.UUID | None = None,
    search: str | None = None,
    user: User = _SA,
    db: AsyncSession = Depends(get_db),
) -> AuditLogsPage:
    rows, total = await audit_service.list_audit_logs(
        db,
        page=page,
        page_size=page_size,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        search=search,
    )
    items = []
    for row in rows:
        payload = AuditLogOut.model_validate(row)
        payload.actor_email = row.actor.email if row.actor else None
        items.append(payload)
    return AuditLogsPage(items=items, total=total, page=page, page_size=page_size)
