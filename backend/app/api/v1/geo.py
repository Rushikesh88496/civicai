"""GIS / Ward detection & spatial intelligence API (Part 10).

Endpoints expose the spatial-intelligence service over raw coordinates:
* ``POST /geo/lookup`` — full payload (reverse address, containing ward, nearby
  roads, hospitals, schools, bus stops, critical infrastructure).
* ``GET /geo/wards`` — wards + boundary rings for map rendering.
* ``POST /geo/distance`` — great-circle distance between two coordinates.

All endpoints require an authenticated user (any role). Coordinates are validated
(300 < lat < 90, -180 < lng < 180) and the lookup radius is server-clamped, so
arbitrary/out-of-range input is rejected cleanly rather than reaching PostGIS.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.geo import (
    GeoDistanceIn,
    GeoDistanceOut,
    GeoLookupIn,
    GeoLookupOut,
    WardListOut,
)
from app.services.geo_service import InvalidCoordinatesError, get_geo_service

router = APIRouter(prefix="/geo", tags=["geo"])


@router.post("/lookup", response_model=GeoLookupOut)
async def geo_lookup(
    payload: GeoLookupIn,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> GeoLookupOut:
    """Return spatial intelligence for the given coordinates."""
    try:
        return await get_geo_service().geo_lookup(
            db, payload.latitude, payload.longitude, payload.radius_m
        )
    except InvalidCoordinatesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/wards", response_model=WardListOut)
async def geo_wards(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> WardListOut:
    """Return wards (with demo boundary rings) for the map."""
    return await get_geo_service().list_wards(db)


@router.post("/distance", response_model=GeoDistanceOut)
async def geo_distance(
    payload: GeoDistanceIn,
    _db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> GeoDistanceOut:
    """Return the great-circle distance between two coordinates."""
    service = get_geo_service()
    service.validate_coordinates(payload.latitude_a, payload.longitude_a)
    service.validate_coordinates(payload.latitude_b, payload.longitude_b)
    distance_m = service.calculate_distance(
        payload.latitude_a,
        payload.longitude_a,
        payload.latitude_b,
        payload.longitude_b,
    )
    return GeoDistanceOut(distance_km=distance_m / 1000.0, distance_m=distance_m)
