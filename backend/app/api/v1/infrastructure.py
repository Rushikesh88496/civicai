"""Predictive Infrastructure Maintenance API (Part 24).

Officer-only predictive-maintenance risk dashboard:

- GET  /infrastructure/status       — active infra model + evaluation metrics
- POST /infrastructure/train        — retrain now (persists artifact + registry)
- GET  /infrastructure/assets       — registered infrastructure assets
- POST /infrastructure/assets       — register a new asset
- GET  /infrastructure/predictions  — live inference: predicted risk per asset
- POST /infrastructure/predictions/{id}/review   — officer review decision
- POST /infrastructure/predictions/{id}/work-orders — optional preventive WO

Real Nearby Infrastructure Data System (Part 35) — verified facility registry:

- POST /infrastructure/nearby           — data-quality-aware nearby lookup
- GET  /infrastructure/registry         — verified registry (list + filters)
- GET  /infrastructure/registry/summary — registry aggregates
- POST /infrastructure/registry/sync    — ingest real data (OSM/file)

Every response is labelled ``ai_prediction`` with a disclaimer; outputs use
"predicted risk" / "recommended inspection" wording, never "will fail".
Registry records carry visible provenance (source / dataset / verification
state) so demo placeholders are never passed off as real facilities.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import (
    CriticalLocationCategory,
    InfrastructureDataStatus,
    RoleName,
)
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
from app.schemas.nearby import (
    NearbyInfrastructureIn,
    NearbyInfrastructureOut,
    RegistryListOut,
    RegistrySummaryOut,
    RegistrySyncIn,
    RegistrySyncOut,
)
from app.services import audit_service, infra_service
from app.services.geo_service import InvalidCoordinatesError
from app.services.infrastructure_registry import get_infrastructure_registry

logger = logging.getLogger(__name__)

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


# --------------------------------------------------------------------------- #
# Real Nearby Infrastructure Data System (Part 35)
# --------------------------------------------------------------------------- #
@router.post("/nearby", response_model=NearbyInfrastructureOut)
async def nearby_infrastructure(
    payload: NearbyInfrastructureIn,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> NearbyInfrastructureOut:
    """Return the data-quality-aware nearby infrastructure answer.

    Resolves each category against the verified facility registry (PostGIS)
    with an honest per-category state (FOUND / NO_VERIFIED_RECORDS /
    PENDING_VERIFICATION / DATA_UNAVAILABLE). Uncached successful answers are
    cached in Redis; failures are never cached.
    """
    service = get_infrastructure_registry()
    try:
        out, cached = await service.find_nearby(
            db,
            latitude=payload.latitude,
            longitude=payload.longitude,
            radius_m=payload.radius_m,
            categories=payload.categories,
            limit=payload.limit,
            use_cache=payload.use_cache,
        )
    except InvalidCoordinatesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if cached:
        out.cached = True
    return out


@router.get("/registry/summary", response_model=RegistrySummaryOut)
async def registry_summary(
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> RegistrySummaryOut:
    """Return registry aggregates (totals by source / status / category)."""
    _require_city(user)
    return await get_infrastructure_registry().registry_summary(db)


@router.get("/registry", response_model=RegistryListOut)
async def registry_list(
    category: CriticalLocationCategory | None = Query(default=None),
    verification_status: InfrastructureDataStatus | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> RegistryListOut:
    """Return verified-registry records with optional filters."""
    _require_city(user)
    return await get_infrastructure_registry().list_registry(
        db,
        category=category,
        verification_status=verification_status,
        source=source,
        limit=limit,
        offset=offset,
    )


@router.post("/registry/sync", response_model=RegistrySyncOut)
async def registry_sync(
    payload: RegistrySyncIn,
    user: User = Depends(require_roles(*_CITY_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> RegistrySyncOut:
    """Run a registry ingestion.

    ``source="openstreetmap"`` fetches REAL facilities for every operational
    ward from the Overpass API and upserts them with full provenance (deduped
    on source_id). A non-openstreetmap source requires a local ``file_path``
    to a normalized CSV/JSON dataset. Every record is real — no demo rows and
    never invented coordinates.
    """
    _require_city(user)
    service = get_infrastructure_registry()
    try:
        if payload.source == "openstreetmap":
            out = await service.ingest_from_overpass(
                db, force=payload.force
            )
        else:
            if not payload.file_path:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="File-based ingestion requires a file_path.",
                )
            out = await service.ingest_from_file(
                db,
                payload.file_path,
                source=payload.source,
                source_dataset=payload.source,
                source_url=None,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidCoordinatesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    await audit_service.record_audit(
        db,
        actor_id=user.id,
        action="infrastructure.registry.sync",
        entity_type="critical_locations",
        after={
            "source": out.source,
            "wards_covered": out.wards_covered,
            "fetched_total": out.fetched_total,
            "inserted": out.inserted,
            "updated": out.updated,
            "skipped_duplicate": out.skipped_duplicate,
            "failed_total": out.failed_total,
        },
    )
    await db.commit()
    logger.info("Registry sync by %s: %s", user.email, out.message)
    return out
