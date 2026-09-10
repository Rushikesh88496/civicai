"""Public ward schemas (Part 31).

Only active reference wards are exposed, on a deliberately tiny public endpoint
so the registration page can offer a ward picker before the citizen signs in.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class PublicWardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    is_active: bool = True
