"""Request/response schemas for the Super-Admin Panel (Part 27).

The panel exposes management CRUD for users, roles, wards, departments, field
workers, ward representatives, complaint categories, SLA rules, priority weights
and the secure system configuration, plus the administrative audit trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import is_strong_password
from app.models.enums import RepresentativeStatus, WorkerStatus


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    is_active: bool
    created_at: datetime


class RoleListItem(RoleOut):
    user_count: int = 0


class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    description: str | None = Field(default=None, max_length=255)


class RoleUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class WardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    description: str | None = None
    is_active: bool
    created_at: datetime


class WardIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=255)


class WardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    description: str | None = None
    is_active: bool
    created_at: datetime


class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=255)


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    is_email_verified: bool
    role: str
    role_id: uuid.UUID | None = None
    ward_name: str | None = None
    ward_code: str | None = None
    worker_status: str | None = None
    rep_status: str | None = None
    created_at: datetime
    updated_at: datetime


class UserAdminCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=2, max_length=50)
    ward_code: str | None = None
    is_email_verified: bool = False
    # Field-worker profile (ignored unless role == FIELD_WORKER).
    department_code: str | None = None
    specialty: str | None = Field(default=None, max_length=150)
    worker_status: WorkerStatus = WorkerStatus.ACTIVE
    skill_tags: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    # Ward-representative profile (ignored unless role == WARD_REPRESENTATIVE).
    rep_title: str | None = Field(default=None, max_length=150)
    rep_status: RepresentativeStatus = RepresentativeStatus.ACTIVE

    @field_validator("password")
    @classmethod
    def _check_strength(cls, v: str) -> str:
        ok, reason = is_strong_password(v)
        if not ok:
            raise ValueError(reason or "Weak password.")
        return v

    @field_validator("role")
    @classmethod
    def _normalize_role(cls, v: str) -> str:
        return v.strip().upper()


class UserAdminUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: str | None = Field(default=None, min_length=2, max_length=50)
    ward_code: str | None = None
    is_active: bool | None = None
    is_email_verified: bool | None = None
    # Field-worker profile (applied only when the user holds the worker role).
    department_code: str | None = None
    specialty: str | None = Field(default=None, max_length=150)
    worker_status: WorkerStatus | None = None
    skill_tags: list[str] | None = None
    equipment: list[str] | None = None
    home_latitude: float | None = None
    home_longitude: float | None = None
    max_active_orders: int | None = Field(default=None, ge=0)
    # Ward-representative profile (applied only when the user holds the role).
    rep_title: str | None = Field(default=None, max_length=150)
    rep_status: RepresentativeStatus | None = None

    @field_validator("password")
    @classmethod
    def _check_strength(cls, v: str) -> str:
        ok, reason = is_strong_password(v)
        if not ok:
            raise ValueError(reason or "Weak password.")
        return v

    @field_validator("role")
    @classmethod
    def _normalize_role(cls, v: str) -> str:
        return v.strip().upper()


class FieldWorkerOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    full_name: str
    user_active: bool
    department_name: str | None = None
    department_code: str | None = None
    specialty: str | None = None
    status: WorkerStatus
    skill_tags: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    home_latitude: float | None = None
    home_longitude: float | None = None
    max_active_orders: int | None = None
    created_at: datetime


class FieldWorkerUpdate(BaseModel):
    department_code: str | None = None
    specialty: str | None = Field(default=None, max_length=150)
    status: WorkerStatus | None = None
    skill_tags: list[str] | None = None
    equipment: list[str] | None = None
    home_latitude: float | None = None
    home_longitude: float | None = None
    max_active_orders: int | None = Field(default=None, ge=0)


class RepresentativeOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    full_name: str
    user_active: bool
    ward_name: str | None = None
    ward_code: str | None = None
    title: str | None = None
    status: RepresentativeStatus
    created_at: datetime


class RepresentativeUpdate(BaseModel):
    ward_code: str | None = None
    title: str | None = Field(default=None, max_length=150)
    status: RepresentativeStatus | None = None


class ComplaintCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    label: str
    description: str | None = None
    is_active: bool
    sort_order: int
    created_at: datetime


class ComplaintCategoryIn(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9_]+$")
    label: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=255)
    sort_order: int = Field(default=0, ge=0)


class ComplaintCategoryUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class PriorityWeightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    label: str
    weight: float
    is_active: bool
    updated_at: datetime


class PriorityWeightIn(BaseModel):
    key: str = Field(min_length=3, max_length=32)
    label: str = Field(min_length=1, max_length=120)
    weight: float = Field(gt=0)


class PriorityWeightUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    weight: float | None = Field(default=None, gt=0)
    is_active: bool | None = None


class ConfigItemOut(BaseModel):
    key: str
    label: str
    category: str
    value_type: str
    is_secret: bool
    is_editable: bool
    configured: bool
    # Secrets are NEVER returned in full — only a masked preview.
    masked: str | None = None
    # Effective (non-secret) value when the override or environment default is set.
    value: str | int | float | bool | None = None
    source: str  # "env" | "override"
    updated_at: datetime | None = None


class ConfigUpdateIn(BaseModel):
    # For secrets this is the new key value request; for non-secrets the raw
    # override value. ``None`` clears any stored override (revert to env).
    value: str | int | float | bool | None = None


class ConfigTestOut(BaseModel):
    key: str
    configured: bool
    reachable: bool = False
    message: str
    latency_ms: int | None = None
    detail: dict[str, Any] | None = None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None = None
    actor_email: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    ip_address: str | None = None
    created_at: datetime


class AuditLogsPage(BaseModel):
    items: list[AuditLogOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25


class UsersPage(BaseModel):
    items: list[UserAdminOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25


class WardsPage(BaseModel):
    items: list[WardOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25


class DepartmentsPage(BaseModel):
    items: list[DepartmentOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25


class FieldWorkersPage(BaseModel):
    items: list[FieldWorkerOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25


class RepresentativesPage(BaseModel):
    items: list[RepresentativeOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25


class AdminSummary(BaseModel):
    users: int = 0
    active_users: int = 0
    roles: int = 0
    wards: int = 0
    active_wards: int = 0
    departments: int = 0
    field_workers: int = 0
    representatives: int = 0
    complaint_categories: int = 0
    system_settings: int = 0
    audit_logs: int = 0
