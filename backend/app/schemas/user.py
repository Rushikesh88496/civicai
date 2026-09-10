"""User-facing response schemas for identity endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.complaint import WardOut


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None


class UserProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    phone: str | None = None
    address: str | None = None
    city: str | None = None
    avatar_url: str | None = None
    timezone: str | None = None
    language: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    is_email_verified: bool
    role: RoleOut
    profile: UserProfileOut | None = None
    # The citizen's registered ward (Part 31). Required for citizens, None for
    # staff that don't belong to a single ward.
    ward: WardOut | None = None
    created_at: datetime
    updated_at: datetime


class UpdateProfileIn(BaseModel):
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=500)
    timezone: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=10)


class MeResponse(BaseModel):
    user: UserOut


class WorkerStatusOut(BaseModel):
    status: str
    department_code: str | None = None
    specialty: str | None = None


class RepresentativeOut(BaseModel):
    status: str
    ward_code: str | None = None
    title: str | None = None
