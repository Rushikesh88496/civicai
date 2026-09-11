"""Super-Admin Panel entity management (Part 27).

CRUD + disable/search/filter for the management model: users, roles, wards,
departments, field workers, ward representatives, complaint categories and
priority weights. Every mutation is audited by the caller via the audit service;
sensitive fields (passwords, API keys) are never included in audit payloads.
Domain errors surface as ``HTTPException`` (matching ``auth_service``).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.security import hash_password
from app.models import (
    ComplaintCategoryConfig,
    Department,
    FieldWorker,
    PriorityWeight,
    RefreshToken,
    Role,
    User,
    UserProfile,
    Ward,
    WardRepresentative,
)
from app.models.enums import RepresentativeStatus, RoleName, WorkerStatus
from app.services.geo_service import GeoService, InvalidCoordinatesError
from app.schemas.admin import (
    DepartmentIn,
    DepartmentUpdate,
    FieldWorkerOut,
    FieldWorkerUpdate,
    PriorityWeightIn,
    PriorityWeightUpdate,
    RepresentativeOut,
    RepresentativeUpdate,
    RoleIn,
    RoleUpdate,
    UserAdminCreate,
    UserAdminOut,
    UserAdminUpdate,
    WardIn,
    WardUpdate,
)

# The Priority Engine's six factor keys (mirrors Weights in priority_engine.py).
PRIORITY_WEIGHT_KEYS = frozenset({"severity", "weather", "location", "crowd", "history", "time"})

_PAGE_CAP = 100


def _page(page: int, page_size: int) -> tuple[int, int]:
    return (max(1, int(page)), min(_PAGE_CAP, max(1, int(page_size))))


async def _reload_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Re-SELECT a user with every relationship ``_user_out`` needs preloaded.

    A fresh ``select`` guarantees the eager loads are applied even when the row
    is already present in the session identity map (``Session.get`` would return
    the cached instance without reapplying loader options).
    """
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


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def _user_out(user: User) -> UserAdminOut:
    worker, rep = user.field_worker, user.ward_representative
    ward = user.ward
    return UserAdminOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_email_verified=user.is_email_verified,
        role=user.role.name,
        role_id=user.role_id,
        ward_name=ward.name if ward else None,
        ward_code=ward.code if ward else None,
        worker_status=worker.status.value if worker else None,
        rep_status=rep.status.value if rep else None,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _user_audit_payload(user: User) -> dict:
    worker, rep = user.field_worker, user.ward_representative
    return {
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.name,
        "is_active": user.is_active,
        "is_email_verified": user.is_email_verified,
        "ward": user.ward.code if user.ward else None,
        "worker_status": worker.status.value if worker else None,
        "rep_status": rep.status.value if rep else None,
    }


async def _find_role(db: AsyncSession, name: str, *, active_only: bool = False) -> Role:
    role = await db.scalar(select(Role).where(Role.name == name.strip().upper()))
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Role '{name}' does not exist.")
    if active_only and not role.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Role '{role.name}' is disabled and cannot be assigned."
        )
    return role


async def _find_ward(db: AsyncSession, code: str | None) -> Ward | None:
    if not code:
        return None
    ward = await db.scalar(select(Ward).where(Ward.code == code.strip().upper()))
    if ward is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Ward '{code}' does not exist.")
    if not ward.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ward '{ward.code}' is disabled.")
    return ward


async def _find_department(db: AsyncSession, code: str | None) -> Department | None:
    if not code:
        return None
    dept = await db.scalar(select(Department).where(Department.code == code.strip().upper()))
    if dept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Department '{code}' does not exist.")
    if not dept.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Department '{dept.code}' is disabled.")
    return dept


async def list_users(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    ward_code: str | None = None,
) -> tuple[list[UserAdminOut], int]:
    cur_page, cur_size = _page(page, page_size)
    conditions = []
    if search:
        needle = f"%{search.strip()}%"
        conditions.append(or_(User.email.ilike(needle), User.full_name.ilike(needle)))
    if role:
        conditions.append(User.role.has(Role.name == role.strip().upper()))
    if is_active is not None:
        conditions.append(User.is_active.is_(is_active))
    if ward_code:
        conditions.append(User.ward.has(Ward.code == ward_code.strip().upper()))

    stmt = select(User)
    count_stmt = select(func.count(User.id))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

    total = await db.scalar(count_stmt)
    rows = (
        await db.execute(
            stmt.options(
                selectinload(User.field_worker),
                selectinload(User.ward_representative),
                selectinload(User.ward),
                selectinload(User.role),
            )
            .order_by(User.created_at.desc(), User.id.desc())
            .offset((cur_page - 1) * cur_size)
            .limit(cur_size)
        )
    ).scalars().all()
    return [_user_out(u) for u in rows], int(total or 0)


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> UserAdminOut:
    user = await _reload_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return _user_out(user)


async def create_user(db: AsyncSession, payload: UserAdminCreate) -> UserAdminOut:
    email = payload.email.lower().strip()
    if await db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")

    role = await _find_role(db, payload.role, active_only=True)
    ward = await _find_ward(db, payload.ward_code)
    department = await _find_department(db, payload.department_code)

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role_id=role.id,
        ward_id=ward.id if ward else None,
        is_active=True,
        is_email_verified=payload.is_email_verified,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id))
    await db.flush()

    if role.name == RoleName.FIELD_WORKER.value:
        if department is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "department_code is required for a FIELD_WORKER user.",
            )
        db.add(
            FieldWorker(
                user_id=user.id,
                department_id=department.id,
                specialty=payload.specialty,
                status=payload.worker_status,
                skill_tags=payload.skill_tags,
                equipment=payload.equipment,
            )
        )
    elif role.name == RoleName.WARD_REPRESENTATIVE.value:
        if ward is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "ward_code is required for a WARD_REPRESENTATIVE user.",
            )
        db.add(
            WardRepresentative(
                user_id=user.id,
                ward_id=ward.id,
                title=payload.rep_title,
                status=payload.rep_status,
            )
        )
    await db.flush()
    return _user_out(await _reload_user(db, user.id))


async def update_user(
    db: AsyncSession, user_id: uuid.UUID, payload: UserAdminUpdate, *, actor: User
) -> UserAdminOut:
    user = await _reload_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

    data = payload.model_dump(exclude_unset=True)

    if "role" in data and data["role"] and data["role"] != user.role.name:
        role = await _find_role(db, data["role"], active_only=True)
        # A super admin must never demote their own account below SUPER_ADMIN.
        if user.id == actor.id and role.name != RoleName.SUPER_ADMIN.value:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "You cannot remove your own SUPER_ADMIN role.",
            )
        user.role_id = role.id

    if "ward_code" in data:
        user.ward_id = (await _find_ward(db, data["ward_code"])).id if data["ward_code"] else None

    if "full_name" in data and data["full_name"]:
        user.full_name = data["full_name"].strip()
    if "is_active" in data and data["is_active"] is not None:
        is_super = user.role.name == RoleName.SUPER_ADMIN.value
        if is_super and user.id == actor.id and not data["is_active"]:
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot disable your own account.")
        if is_super and not data["is_active"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A SUPER_ADMIN account cannot be disabled."
            )
        user.is_active = data["is_active"]
    if "is_email_verified" in data and data["is_email_verified"] is not None:
        user.is_email_verified = data["is_email_verified"]

    password = data.get("password")
    if password:
        user.password_hash = hash_password(password)
        # Force re-authentication everywhere after an admin password reset.
        sessions = await db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False)
            )
        )
        for record in sessions:
            record.revoked = True

    # Field-worker profile.
    if user.field_worker is not None:
        worker = user.field_worker
        if "department_code" in data:
            dept = await _find_department(db, data["department_code"])
            if dept is not None:
                worker.department_id = dept.id
        if "specialty" in data and data["specialty"] is not None:
            worker.specialty = data["specialty"]
        if "skill_tags" in data and data["skill_tags"] is not None:
            worker.skill_tags = data["skill_tags"]
        if "equipment" in data and data["equipment"] is not None:
            worker.equipment = data["equipment"]
        if "worker_status" in data and data["worker_status"] is not None:
            worker.status = data["worker_status"]
        if "home_latitude" in data or "home_longitude" in data or "base_location" in data:
            _update_worker_home(worker, data)
        if "max_active_orders" in data:
            worker.max_active_orders = data["max_active_orders"]
    elif user.role.name == RoleName.FIELD_WORKER.value and "department_code" in data:
        dept = await _find_department(db, data["department_code"])
        if dept is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "department_code is required to link a FIELD_WORKER profile.",
            )
        db.add(
            FieldWorker(
                user_id=user.id,
                department_id=dept.id,
                specialty=data.get("specialty"),
                status=data.get("worker_status", WorkerStatus.ACTIVE),
                skill_tags=data.get("skill_tags", []),
                equipment=data.get("equipment", []),
                base_location=data.get("base_location"),
            )
        )

    # Ward-representative profile.
    if user.role.name == RoleName.WARD_REPRESENTATIVE.value:
        rep = await db.scalar(
            select(WardRepresentative).where(WardRepresentative.user_id == user.id)
        )
        if rep is not None:
            if "ward_code" in data and data["ward_code"]:
                rep.ward_id = (await _find_ward(db, data["ward_code"])).id
            if "rep_title" in data and data["rep_title"] is not None:
                rep.title = data["rep_title"]
            if "rep_status" in data and data["rep_status"] is not None:
                rep.status = data["rep_status"]
        elif "ward_code" in data:
            ward = await _find_ward(db, data["ward_code"])
            db.add(
                WardRepresentative(
                    user_id=user.id,
                    ward_id=ward.id,
                    title=data.get("rep_title"),
                    status=data.get("rep_status", RepresentativeStatus.ACTIVE),
                )
            )

    await db.flush()
    await db.flush()
    return _user_out(await _reload_user(db, user.id))


async def set_user_active(
    db: AsyncSession, *, actor: User, user_id: uuid.UUID, is_active: bool
) -> UserAdminOut:
    user = await _reload_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if user.id == actor.id and not is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot disable your own account.")
    if is_active is False and user.role.name == RoleName.SUPER_ADMIN.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A SUPER_ADMIN account cannot be disabled."
        )
    user.is_active = is_active
    await db.flush()
    return _user_out(await _reload_user(db, user.id))


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
async def list_roles(db: AsyncSession) -> list[object]:
    rows = (
        await db.execute(
            select(Role, func.count(User.id))
            .outerjoin(User, User.role_id == Role.id)
            .group_by(Role.id)
            .order_by(Role.created_at.asc(), Role.name.asc())
        )
    ).all()
    return [
        {
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "is_active": role.is_active,
            "created_at": role.created_at,
            "user_count": count,
        }
        for role, count in rows
    ]


async def create_role(db: AsyncSession, payload: RoleIn) -> Role:
    name = payload.name.strip().upper()
    if await db.scalar(select(Role).where(Role.name == name)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Role '{name}' already exists.")
    role = Role(name=name, description=payload.description, is_active=True)
    db.add(role)
    await db.flush()
    return role


async def update_role(db: AsyncSession, role_id: uuid.UUID, payload: RoleUpdate) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found.")

    if payload.description is not None:
        role.description = payload.description

    if payload.is_active is not None and payload.is_active is not role.is_active:
        if role.name == RoleName.SUPER_ADMIN.value and not payload.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "The SUPER_ADMIN role cannot be disabled."
            )
        if not payload.is_active:
            assigned = await db.scalar(
                select(func.count(User.id)).where(User.role_id == role.id, User.is_active.is_(True))
            )
            if assigned:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Role '{role.name}' still has {assigned} active user(s); reassign them first.",
                )
        role.is_active = payload.is_active
    await db.flush()
    await db.refresh(role)
    return role


# --------------------------------------------------------------------------- #
# Wards & Departments
# --------------------------------------------------------------------------- #
async def list_wards(
    db: AsyncSession, *, page: int = 1, page_size: int = 25, search: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[Ward], int]:
    cur_page, cur_size = _page(page, page_size)
    conditions = []
    if search:
        needle = f"%{search.strip()}%"
        conditions.append(or_(Ward.name.ilike(needle), Ward.code.ilike(needle)))
    if is_active is not None:
        conditions.append(Ward.is_active.is_(is_active))
    total = await db.scalar(
        select(func.count(Ward.id)).where(*conditions)
        if conditions
        else select(func.count(Ward.id))
    )
    rows = (
        await db.execute(
            select(Ward)
            .where(*conditions) if conditions else select(Ward)
        )
    ).scalars().all()
    _all = list(rows)
    rows_page = _all[(cur_page - 1) * cur_size : cur_page * cur_size]
    return rows_page, int(total or 0)


async def create_ward(db: AsyncSession, payload: WardIn) -> Ward:
    code = payload.code.strip().upper()
    if await db.scalar(
        select(Ward).where(or_(Ward.code == code, Ward.name == payload.name.strip()))
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A ward with that code or name already exists."
        )
    ward = Ward(
        name=payload.name.strip(), code=code, description=payload.description, is_active=True
    )
    db.add(ward)
    await db.flush()
    return ward


async def update_ward(db: AsyncSession, ward_id: uuid.UUID, payload: WardUpdate) -> Ward:
    ward = await db.get(Ward, ward_id)
    if ward is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ward not found.")
    if payload.name is not None:
        ward.name = payload.name.strip()
    if payload.description is not None:
        ward.description = payload.description
    if payload.is_active is not None:
        ward.is_active = payload.is_active
    await db.flush()
    await db.refresh(ward)
    return ward


async def list_departments(
    db: AsyncSession, *, page: int = 1, page_size: int = 25, search: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[Department], int]:
    cur_page, cur_size = _page(page, page_size)
    conditions = []
    if search:
        needle = f"%{search.strip()}%"
        conditions.append(or_(Department.name.ilike(needle), Department.code.ilike(needle)))
    if is_active is not None:
        conditions.append(Department.is_active.is_(is_active))
    total = await db.scalar(
        select(func.count(Department.id)).where(*conditions)
        if conditions
        else select(func.count(Department.id))
    )
    rows = list(
        (
            await db.execute(
                select(Department).where(*conditions) if conditions else select(Department)
            )
        ).scalars().all()
    )
    return rows[(cur_page - 1) * cur_size : cur_page * cur_size], int(total or 0)


async def create_department(db: AsyncSession, payload: DepartmentIn) -> Department:
    code = payload.code.strip().upper()
    if await db.scalar(
        select(Department).where(
            or_(Department.code == code, Department.name == payload.name.strip())
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A department with that code or name already exists."
        )
    dept = Department(
        name=payload.name.strip(), code=code, description=payload.description, is_active=True
    )
    db.add(dept)
    await db.flush()
    return dept


async def update_department(
    db: AsyncSession, dept_id: uuid.UUID, payload: DepartmentUpdate
) -> Department:
    dept = await db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found.")
    if payload.name is not None:
        dept.name = payload.name.strip()
    if payload.description is not None:
        dept.description = payload.description
    if payload.is_active is not None:
        dept.is_active = payload.is_active
    await db.flush()
    await db.refresh(dept)
    return dept


# --------------------------------------------------------------------------- #
# Field workers
# --------------------------------------------------------------------------- #
def _update_worker_home(worker: FieldWorker, data: dict) -> None:
    """Apply Pune-scoped base/registered location fields to a field worker.

    Coordinates are co-updated (a lone latitude also validates against the
    existing longitude) and MUST fall inside the Pune municipal area — the
    worker's registered base, not a live GPS position. ``base_location`` is the
    human-readable station label (e.g. "Kothrud, Pune, Maharashtra").
    """
    if "home_latitude" in data:
        worker.home_latitude = data["home_latitude"]
    if "home_longitude" in data:
        worker.home_longitude = data["home_longitude"]
    if "base_location" in data:
        worker.base_location = data["base_location"]
    if worker.home_latitude is not None and worker.home_longitude is not None:
        try:
            GeoService().validate_pune_base_coordinates(
                worker.home_latitude, worker.home_longitude
            )
        except InvalidCoordinatesError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _worker_out(worker: FieldWorker) -> FieldWorkerOut:
    return FieldWorkerOut(
        id=worker.id,
        user_id=worker.user_id,
        email=worker.user.email,
        full_name=worker.user.full_name,
        user_active=worker.user.is_active,
        department_name=worker.department.name if worker.department else None,
        department_code=worker.department.code if worker.department else None,
        specialty=worker.specialty,
        status=worker.status,
        skill_tags=worker.skill_tags or [],
        equipment=worker.equipment or [],
        home_latitude=worker.home_latitude,
        home_longitude=worker.home_longitude,
        base_location=worker.base_location,
        max_active_orders=worker.max_active_orders,
        created_at=worker.created_at,
    )


async def list_field_workers(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    department_code: str | None = None,
    status_filter: str | None = None,
) -> tuple[list[FieldWorkerOut], int]:
    cur_page, cur_size = _page(page, page_size)
    conditions = []
    if search:
        needle = f"%{search.strip()}%"
        conditions.append(or_(FieldWorker.user.has(User.full_name.ilike(needle)),
                              FieldWorker.user.has(User.email.ilike(needle))))
    if department_code:
        conditions.append(
        FieldWorker.department.has(Department.code == department_code.strip().upper())
    )
    if status_filter:
        conditions.append(FieldWorker.status == status_filter.strip().upper())
    total = await db.scalar(
        select(func.count(FieldWorker.id)).where(*conditions)
        if conditions
        else select(func.count(FieldWorker.id))
    )
    rows = (
        await db.execute(
            select(FieldWorker)
            .options(joinedload(FieldWorker.user), joinedload(FieldWorker.department))
            .where(*conditions) if conditions else select(FieldWorker)
            .options(joinedload(FieldWorker.user), joinedload(FieldWorker.department))
        )
    ).scalars().all()
    all_rows = [r for r in rows]
    page_rows = all_rows[(cur_page - 1) * cur_size : cur_page * cur_size]
    return [_worker_out(r) for r in page_rows], int(total or 0)


async def update_field_worker(
    db: AsyncSession, worker_id: uuid.UUID, payload: FieldWorkerUpdate
) -> FieldWorkerOut:
    worker = await db.get(
        FieldWorker,
        worker_id,
        options=(joinedload(FieldWorker.user), joinedload(FieldWorker.department)),
    )
    if worker is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field worker not found.")

    data = payload.model_dump(exclude_unset=True)
    if "department_code" in data:
        dept = await _find_department(db, data["department_code"])
        if dept is not None:
            worker.department_id = dept.id
    for field in ("specialty", "skill_tags", "equipment"):
        if field in data and data[field] is not None:
            setattr(worker, field, data[field])
    if "home_latitude" in data or "home_longitude" in data or "base_location" in data:
        _update_worker_home(worker, data)
    if "max_active_orders" in data:
        worker.max_active_orders = data["max_active_orders"]
    if "status" in data and data["status"] is not None:
        worker.status = data["status"]
    await db.flush()
    fresh = await db.scalar(
        select(FieldWorker)
        .where(FieldWorker.id == worker.id)
        .options(joinedload(FieldWorker.user), joinedload(FieldWorker.department))
    )
    return _worker_out(fresh)


# --------------------------------------------------------------------------- #
# Ward representatives
# --------------------------------------------------------------------------- #
def _rep_out(rep: WardRepresentative) -> RepresentativeOut:
    return RepresentativeOut(
        id=rep.id,
        user_id=rep.user_id,
        email=rep.user.email,
        full_name=rep.user.full_name,
        user_active=rep.user.is_active,
        ward_name=rep.ward.name if rep.ward else None,
        ward_code=rep.ward.code if rep.ward else None,
        title=rep.title,
        status=rep.status,
        created_at=rep.created_at,
    )


async def list_representatives(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    ward_code: str | None = None,
    status_filter: str | None = None,
) -> tuple[list[RepresentativeOut], int]:
    cur_page, cur_size = _page(page, page_size)
    conditions = []
    if search:
        needle = f"%{search.strip()}%"
        conditions.append(or_(WardRepresentative.user.has(User.full_name.ilike(needle)),
                              WardRepresentative.user.has(User.email.ilike(needle))))
    if ward_code:
        conditions.append(WardRepresentative.ward.has(Ward.code == ward_code.strip().upper()))
    if status_filter:
        conditions.append(WardRepresentative.status == status_filter.strip().upper())
    total = await db.scalar(
        select(func.count(WardRepresentative.id)).where(*conditions)
        if conditions
        else select(func.count(WardRepresentative.id))
    )
    rows = list(
        (
            await db.execute(
                select(WardRepresentative)
                .options(joinedload(WardRepresentative.user), joinedload(WardRepresentative.ward))
                .where(*conditions)
                if conditions
                else select(WardRepresentative)
                .options(joinedload(WardRepresentative.user), joinedload(WardRepresentative.ward))
            )
        ).scalars().all()
    )
    page_reps = rows[(cur_page - 1) * cur_size : cur_page * cur_size]
    return [_rep_out(r) for r in page_reps], int(total or 0)


async def update_representative(
    db: AsyncSession, rep_id: uuid.UUID, payload: RepresentativeUpdate
) -> RepresentativeOut:
    rep = await db.get(
        WardRepresentative,
        rep_id,
        options=(joinedload(WardRepresentative.user), joinedload(WardRepresentative.ward)),
    )
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ward representative not found.")
    data = payload.model_dump(exclude_unset=True)
    if "ward_code" in data and data["ward_code"]:
        ward = await _find_ward(db, data["ward_code"])
        rep.ward_id = ward.id
    if "title" in data and data["title"] is not None:
        rep.title = data["title"]
    if "status" in data and data["status"] is not None:
        rep.status = data["status"]
    await db.flush()
    fresh = await db.scalar(
        select(WardRepresentative)
        .where(WardRepresentative.id == rep.id)
        .options(joinedload(WardRepresentative.user), joinedload(WardRepresentative.ward))
    )
    return _rep_out(fresh)


# --------------------------------------------------------------------------- #
# Complaint categories
# --------------------------------------------------------------------------- #
async def list_complaint_categories(db: AsyncSession) -> list[ComplaintCategoryConfig]:
    rows = await db.execute(
        select(ComplaintCategoryConfig).order_by(
            ComplaintCategoryConfig.sort_order.asc(), ComplaintCategoryConfig.code.asc()
        )
    )
    return list(rows.scalars().all())


async def create_complaint_category(db: AsyncSession, payload) -> ComplaintCategoryConfig:
    code = payload.code.strip().upper()
    if await db.scalar(select(ComplaintCategoryConfig).where(ComplaintCategoryConfig.code == code)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Category '{code}' already exists.")
    row = ComplaintCategoryConfig(
        code=code,
        label=payload.label.strip(),
        description=payload.description,
        is_active=True,
        sort_order=payload.sort_order,
    )
    db.add(row)
    await db.flush()
    return row


async def update_complaint_category(
    db: AsyncSession, category_id: uuid.UUID, payload
) -> ComplaintCategoryConfig:
    row = await db.get(ComplaintCategoryConfig, category_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint category not found.")
    data = payload.model_dump(exclude_unset=True)
    if "label" in data and data["label"] is not None:
        row.label = data["label"].strip()
    if "description" in data:
        row.description = data["description"]
    if "is_active" in data and data["is_active"] is not None:
        row.is_active = data["is_active"]
    if "sort_order" in data and data["sort_order"] is not None:
        row.sort_order = data["sort_order"]
    await db.flush()
    await db.refresh(row)
    return row


# --------------------------------------------------------------------------- #
# Priority weights
# --------------------------------------------------------------------------- #
async def list_priority_weights(db: AsyncSession) -> list[PriorityWeight]:
    rows = await db.execute(
        select(PriorityWeight).order_by(PriorityWeight.created_at.asc(), PriorityWeight.key.asc())
    )
    return list(rows.scalars().all())


async def create_priority_weight(db: AsyncSession, payload: PriorityWeightIn) -> PriorityWeight:
    key = payload.key.strip().lower()
    if key not in PRIORITY_WEIGHT_KEYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Priority weight key must be one of: {', '.join(sorted(PRIORITY_WEIGHT_KEYS))}.",
        )
    if await db.scalar(select(PriorityWeight).where(PriorityWeight.key == key)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Priority weight '{key}' already exists.")
    row = PriorityWeight(
        key=key, label=payload.label.strip(), weight=payload.weight, is_active=True
    )
    db.add(row)
    await db.flush()
    return row


async def update_priority_weight(
    db: AsyncSession, weight_id: uuid.UUID, payload: PriorityWeightUpdate
) -> PriorityWeight:
    row = await db.get(PriorityWeight, weight_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Priority weight not found.")
    data = payload.model_dump(exclude_unset=True)
    if "label" in data and data["label"] is not None:
        row.label = data["label"].strip()
    if "weight" in data and data["weight"] is not None:
        row.weight = data["weight"]
    if "is_active" in data and data["is_active"] is not None:
        row.is_active = data["is_active"]
    await db.flush()
    await db.refresh(row)
    return row
