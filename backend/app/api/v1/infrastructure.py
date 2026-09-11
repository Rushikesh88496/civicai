"""Predictive Infrastructure Maintenance API (Part 24).

Officer-only predictive-maintenance risk dashboard:

- GET  /infrastructure/status       — active infra model + evaluation metrics
- POST /infrastructure/train        — retrain now (persists artifact + registry)
- GET  /infrastructure/assets       — registered infrastructure assets
- POST /infrastructure/assets       — register a new asset
- GET  /infrastructure/predictions  — live inference: predicted risk per asset
- POST /infrastructure/predictions/{id}/review   — officer review decision
- POST /infrastructure/predictions/{id}/work-orders — optional preventive WO

Every response is labelled ``ai_prediction`` with a disclaimer; outputs use
"predicted risk" / "recommended inspection" wording, never "will fail".
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.infrastructure import (
    InfrastructureAssetIn,
    InfrastructureAssetOut,
    InfrastructurePredictions,
    InfrastructureReviewIn,
    InfrastructureReviewOut,
    InfrastructureStatus,
    InfrastructureTrainingOut,
    PreventiveWorkOrderIn,
    PreventiveWorkOrderOut,
)
from app.services import infra_service

router = APIRouter(prefix="/infrastructure", tags=["infrastructure"])

_CITY_ROLES = (RoleName.OFFICER.value, RoleName.ADMIN.value)


def _require_city(user: User) -> User:
    if user.role.name not in _CITY_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Predictive infrastructure is a city-wide officer tool.",
        )
    return user


@router.get("/status", response_model=InfrastructureStatus)
async def get_status(
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> InfrastructureStatus:
    _require_city(user)
    return await infra_service.get_status(db)


@router.post("/train", response_model=InfrastructureTrainingOut)
async def train(
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> InfrastructureTrainingOut:
    _require_city(user)
    return await infra_service.train(db, user)


@router.get("/assets", response_model=list[InfrastructureAssetOut])
async def get_assets(
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[InfrastructureAssetOut]:
    _require_city(user)
    return await infra_service.list_assets(db)


@router.post("/assets", response_model=InfrastructureAssetOut, status_code=status.HTTP_201_CREATED)
async def create_asset(
    payload: InfrastructureAssetIn,
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> InfrastructureAssetOut:
    _require_city(user)
    return await infra_service.register_asset(db, payload)


@router.get("/predictions", response_model=InfrastructurePredictions)
async def get_predictions(
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> InfrastructurePredictions:
    _require_city(user)
    return await infra_service.get_predictions(db, user)


@router.post("/predictions/{prediction_id}/review", response_model=InfrastructureReviewOut)
async def review_prediction(
    prediction_id: uuid.UUID,
    payload: InfrastructureReviewIn,
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> InfrastructureReviewOut:
    _require_city(user)
    out = await infra_service.review_prediction(
        db, user, prediction_id, payload.decision, payload.note
    )
    if out is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found.")
    return out


@router.post(
    "/predictions/{prediction_id}/work-orders",
    response_model=PreventiveWorkOrderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_work_order(
    prediction_id: uuid.UUID,
    payload: PreventiveWorkOrderIn,
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> PreventiveWorkOrderOut:
    _require_city(user)
    out = await infra_service.create_preventive_work_order(
        db,
        user,
        prediction_id,
        department=payload.department,
        recommended_action=payload.recommended_action,
        due_at=payload.due_at,
        note=payload.note,
    )
    if out is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found.")
    return out
