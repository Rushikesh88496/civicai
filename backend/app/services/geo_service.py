"""GIS / Ward detection & spatial intelligence service (Part 10).

Given a latitude / longitude this service answers:
* ``reverse_geocode()`` — human-readable street address via OpenStreetMap's
  public Nominatim reverse geocoder.
* ``find_ward()`` — the ward polygon (from ``ward_boundaries``) that contains the
  point, via PostGIS ``ST_Contains``.
* ``find_nearby_places()`` — hospitals, schools, bus stops, roads and other
  critical infrastructure within a radius, via PostGIS ``ST_DWithin`` on a
  geography cast (metre-accurate).
* ``calculate_distance()`` — great-circle (haversine) distance, pure math.

External-API discipline (Nominatim is *not* authoritative and enforces rate
limits): every remote call is time-bounded, retried a bounded number of times,
and degrades gracefully to a local fallback on timeout / 429 / connection or
JSON failure — it never raises and never blocks the request. No API key is
required (multiple providers, if ever needed, would be configured via env vars,
not secrets in code).

Authoritative ward boundaries require a municipal data source. The seeded
``ward_boundaries`` are illustrative and flagged ``is_demo=True``, so callers can
label them with the configured ``GIS_DEMO_LABEL`` and never present them as
authoritative.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import UTC, datetime

import httpx
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import (
    CriticalLocation,
    Ward,
    WardBoundary,
)
from app.models.enums import CriticalLocationCategory
from app.schemas.geo import (
    GeoLookupOut,
    GeoPlace,
    ReverseGeocodeOut,
    WardBoundaryOut,
    WardDetected,
    WardListOut,
)

# Allowed coordinate ranges for GPS lat/lng (WGS 84).
_MIN_LAT, _MAX_LAT = -90.0, 90.0
_MIN_LNG, _MAX_LNG = -180.0, 180.0


class InvalidCoordinatesError(ValueError):
    """Raised when latitude/longitude fall outside the supported range."""


class GeoService:
    """Stateless facade over the PostGIS + OpenStreetMap lookups."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Coordinate validation
    # ------------------------------------------------------------------ #
    def validate_coordinates(self, latitude: float, longitude: float) -> None:
        """Raise ``InvalidCoordinatesError`` if the coordinate is out of range."""
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not (_MIN_LAT <= latitude <= _MAX_LAT)
            or not (_MIN_LNG <= longitude <= _MAX_LNG)
        ):
            raise InvalidCoordinatesError(
                "Invalid coordinates: latitude must be in [-90, 90] and longitude in [-180, 180]."
            )

    # ------------------------------------------------------------------ #
    # Haversine distance (pure, testable without a DB)
    # ------------------------------------------------------------------ #
    @staticmethod
    def calculate_distance(
        latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
    ) -> float:
        """Return the great-circle distance in metres (haversine)."""
        earth_radius_m = 6371008.8
        lat_a = math.radians(latitude_a)
        lat_b = math.radians(latitude_b)
        d_lat = math.radians(latitude_b - latitude_a)
        d_lng = math.radians(longitude_b - longitude_a)

        h = math.sin(d_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lng / 2) ** 2
        h = min(1.0, max(0.0, h))
        return 2 * earth_radius_m * math.asin(math.sqrt(h))

    # ------------------------------------------------------------------ #
    # Reverse geocoding (OpenStreetMap Nominatim, graceful degradation)
    # ------------------------------------------------------------------ #
    async def reverse_geocode(
        self,
        latitude: float,
        longitude: float,
        client: httpx.AsyncClient | None = None,
    ) -> ReverseGeocodeOut:
        """Reverse-geocode coordinates to an address via Nominatim.

        On any remote failure (timeout, rate limit, network error, unparseable
        payload) returns a ``ReverseGeocodeOut`` with ``degraded=True`` and a
        ``None`` address rather than raising — so ward detection never blocks on
        an external provider.
        """
        self.validate_coordinates(latitude, longitude)
        url = f"{self._settings.GIS_BASE_URL.rstrip('/')}/reverse"
        params = {
            "lat": latitude,
            "lon": longitude,
            "format": "jsonv2",
            "zoom": 18,
            "addressdetails": 1,
        }
        headers = {"User-Agent": self._settings.GIS_NOMINATIM_USERAGENT}
        timeout = self._settings.GIS_NOMINATIM_TIMEOUT_SECONDS
        retries = max(0, int(self._settings.GIS_NOMINATIM_MAX_RETRIES))

        for attempt in range(retries + 1):
            try:
                r = await self._nominatim_get(url, params, headers, timeout, client)
                if r.status_code == 200 and r.content:
                    data = r.json()
                    display = data.get("display_name")
                    if display:
                        return ReverseGeocodeOut(
                            address=display,
                            display_name=display,
                            source="nominatim",
                            degraded=False,
                        )
                # 429 rate-limit 5xx → retry up to the budget.
                if r.status_code in (429, 500, 502, 503, 504):
                    if attempt == retries:
                        break
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                # Any other code / no usable body → treat as "not resolved".
                return ReverseGeocodeOut(
                    address=None,
                    display_name=None,
                    source="nominatim",
                    degraded=True,
                )
            except Exception:  # timeout / transport errors
                if attempt == retries:
                    break
                await asyncio.sleep(0.2 * (attempt + 1))

        return ReverseGeocodeOut(address=None, display_name=None, source="nominatim", degraded=True)

    async def _nominatim_get(
        self,
        url: str,
        params: dict,
        headers: dict,
        timeout: float,
        client: httpx.AsyncClient | None,
    ) -> httpx.Response:
        if client is not None:
            return await client.get(url, params=params, headers=headers, timeout=timeout)
        async with httpx.AsyncClient(timeout=timeout) as c:
            return await c.get(url, params=params, headers=headers)

    # ------------------------------------------------------------------ #
    # Ward detection (point-in-polygon via PostGIS)
    # ------------------------------------------------------------------ #
    async def find_ward(
        self, db: AsyncSession, latitude: float, longitude: float
    ) -> WardDetected | None:
        """Return the ward whose boundary polygon contains the coordinate.

        Uses ``ST_Contains`` on ``ward_boundaries.geom``. Returns ``None`` when
        the coordinate falls outside every (demo / supported) boundary.
        """
        self.validate_coordinates(latitude, longitude)
        point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
        result = await db.execute(
            select(WardBoundary, Ward)
            .join(Ward, WardBoundary.ward_id == Ward.id)
            .where(func.ST_Contains(WardBoundary.geom, point))
        )
        found = result.first()
        if found is None:
            return None
        boundary, ward = found
        return WardDetected(
            ward_id=ward.id,
            name=ward.name,
            code=ward.code,
            description=ward.description,
            is_demo=boundary.is_demo,
        )

    # ------------------------------------------------------------------ #
    # Nearby & critical-infrastructure lookup (PostGIS ST_DWithin)
    # ------------------------------------------------------------------ #
    async def find_nearby_places(
        self,
        db: AsyncSession,
        latitude: float,
        longitude: float,
        radius_m: float,
        category: CriticalLocationCategory | None = None,
        limit: int = 20,
    ) -> list[GeoPlace]:
        """Return critical/public facilities within ``radius_m`` of the point.

        Distances are metre-accurate via a geography cast. ``radius_m`` is
        clamped to ``GIS_MAX_RADIUS_M``.
        """
        self.validate_coordinates(latitude, longitude)
        radius = min(max(radius_m, 0.0), self._settings.GIS_MAX_RADIUS_M)
        gh = Geography(geometry_type="POINT", srid=4326)
        point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)

        stmt = (
            select(CriticalLocation)
            .where(ST_DWithin(CriticalLocation.geom.cast(gh), point.cast(gh), radius))
            .order_by(ST_Distance(CriticalLocation.geom.cast(gh), point.cast(gh)).asc())
            .limit(int(limit))
        )
        if category is not None:
            stmt = stmt.where(CriticalLocation.category == category)

        rows = (await db.execute(stmt)).scalars().all()
        places: list[GeoPlace] = []
        for loc in rows:
            places.append(
                GeoPlace(
                    id=loc.id,
                    name=loc.name,
                    category=loc.category,
                    address=loc.address,
                    latitude=loc.latitude,
                    longitude=loc.longitude,
                    distance_m=self.calculate_distance(
                        latitude, longitude, loc.latitude, loc.longitude
                    ),
                    is_demo=loc.is_demo,
                )
            )
        # Order by computed distance (the ordering below handles equal distances).
        places.sort(key=lambda p: p.distance_m or math.inf)
        return places[:limit]

    # ------------------------------------------------------------------ #
    # Full lookup facade + ward list for the map
    # ------------------------------------------------------------------ #
    async def geo_lookup(
        self,
        db: AsyncSession,
        latitude: float,
        longitude: float,
        radius_m: float | None = None,
    ) -> GeoLookupOut:
        """Run all spatial-intelligence lookups for a coordinate in one call."""
        self.validate_coordinates(latitude, longitude)
        radius = float(radius_m if radius_m is not None else self._settings.GIS_DEFAULT_RADIUS_M)

        address, ward = await asyncio.gather(
            self.reverse_geocode(latitude, longitude),
            self.find_ward(db, latitude, longitude),
        )

        critical_radius = float(self._settings.GIS_CRITICAL_RADIUS_M)
        nearby_roads, hospitals, schools, bus_stops, critical = await asyncio.gather(
            self.find_nearby_places(db, latitude, longitude, radius, CriticalLocationCategory.ROAD),
            self.find_nearby_places(
                db, latitude, longitude, critical_radius, CriticalLocationCategory.HOSPITAL
            ),
            self.find_nearby_places(
                db, latitude, longitude, critical_radius, CriticalLocationCategory.SCHOOL
            ),
            self.find_nearby_places(
                db, latitude, longitude, critical_radius, CriticalLocationCategory.BUS_STOP
            ),
            self.find_nearby_places(db, latitude, longitude, critical_radius),
        )

        return GeoLookupOut(
            latitude=latitude,
            longitude=longitude,
            address=address,
            ward=ward,
            nearby_roads=nearby_roads,
            hospitals=hospitals,
            schools=schools,
            bus_stops=bus_stops,
            critical_infrastructure=critical,
            radius_m=radius,
            demo_label=self._settings.GIS_DEMO_LABEL,
            calculated_at=datetime.now(UTC),
        )

    async def list_wards(self, db: AsyncSession) -> WardListOut:
        """Return wards with boundary rings (geometry) for the map."""
        rows = (
            await db.execute(
                select(WardBoundary, Ward)
                .join(Ward, WardBoundary.ward_id == Ward.id)
                .order_by(Ward.name.asc())
            )
        ).all()
        wards: list[WardBoundaryOut] = []
        for boundary, ward in rows:
            rings = await self._boundary_rings(db, boundary.id)
            wards.append(
                WardBoundaryOut(
                    ward_id=ward.id,
                    name=ward.name,
                    code=ward.code,
                    description=ward.description,
                    is_demo=boundary.is_demo,
                    geometry=rings,
                )
            )
        return WardListOut(wards=wards)

    async def _boundary_rings(
        self, db: AsyncSession, boundary_id: uuid.UUID
    ) -> list[list[float]] | None:
        """Extract the outer ring of a ward boundary polygon as [lng, lat] pairs."""
        from sqlalchemy import text

        result = await db.execute(
            text(
                "SELECT ST_AsGeoJSON(ST_Transform(ST_Force2D(geom), 4326)) "
                "FROM ward_boundaries WHERE id = :bid"
            ),
            {"bid": boundary_id},
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        import json

        data = json.loads(row)
        coords = data.get("coordinates")
        if not coords:
            return None
        # Polygon → outer ring (defensive for PolygonZ etc.).
        ring = coords[0] if isinstance(coords, list) and coords else None
        if ring is None:
            return None
        return [[float(lng), float(lat)] for lng, lat in ring]


def get_geo_service(settings: Settings | None = None) -> GeoService:
    return GeoService(settings=settings or get_settings())
