"""Citizen satisfaction rating schemas (Part 22)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RatingIn(BaseModel):
    rating: int = Field(ge=1, le=5, description="Star score from 1 (worst) to 5 (best).")
    comment: str | None = Field(default=None, max_length=500)


class RatingOut(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID
    rating: int
    comment: str | None = None
    created_at: datetime
