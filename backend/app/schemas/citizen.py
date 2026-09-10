"""Response schemas for the citizen dashboard."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ComplaintOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    title: str
    description: str | None = None
    location: str | None = None
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime


class ComplaintSummary(BaseModel):
    total: int
    open: int
    in_progress: int
    resolved: int
    escalated: int


class WardRepresentativeOut(BaseModel):
    name: str
    email: str
    title: str | None = None
    status: str | None = None


class WardInfoOut(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None
    representative: WardRepresentativeOut | None = None


class DashboardResponse(BaseModel):
    complaints: ComplaintSummary
    recent_complaints: list[ComplaintOut]
    ward: WardInfoOut
