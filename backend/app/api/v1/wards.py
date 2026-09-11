"""Public ward endpoints (Part 31).

Only ACTIVE reference wards are exposed, and the endpoint requires no
authentication: the sign-up page renders its ward picker from here before the
citizen has an account.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import Ward
from app.schemas.ward import PublicWardOut

router = APIRouter(prefix="/wards", tags=["wards"])


@router.get("", response_model=list[PublicWardOut])
async def list_active_wards(db: AsyncSession = Depends(get_db)) -> list[Ward]:
    """Return all wards a new citizen may register under (active only)."""
    rows = await db.scalars(select(Ward).where(Ward.is_active.is_(True)).order_by(Ward.code))
    return list(rows)
