"""Predictive Civic Hotspots API (Part 23).

City-wide, officer-only predictive risk mapping:

- GET  /hotspots/status      — active model info + evaluation metrics
- POST /hotspots/train       — retrain now (persists artifact + registry row)
- GET  /hotspots/predictions — live inference: risk score + expected volume per
                               grid cell for the next horizon (AI Prediction)

Every response is explicitly labelled ``ai_prediction`` with a disclaimer so the
decision-support forecast is never conflated with confirmed incident data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.hotspots import HotspotPredictions, HotspotStatus, HotspotTrainingOut
from app.services import hotspot_service

router = APIRouter(prefix="/hotspots", tags=["hotspots"])

_CITY_ROLES = (RoleName.OFFICER.value, RoleName.ADMIN.value)


def _require_city(user: User) -> User:
    if user.role.name not in _CITY_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Predictive hotspots are a city-wide officer tool.",
        )
    return user


@router.get("/status", response_model=HotspotStatus)
async def get_status(
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> HotspotStatus:
    _require_city(user)
    return await hotspot_service.get_status(db)


@router.post("/train", response_model=HotspotTrainingOut)
async def train(
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> HotspotTrainingOut:
    _require_city(user)
    return await hotspot_service.train_hotspots(db, user)


@router.get("/predictions", response_model=HotspotPredictions)
async def get_predictions(
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> HotspotPredictions:
    _require_city(user)
    return await hotspot_service.get_predictions(db, user)
