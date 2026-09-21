"""GIS / Ward detection & spatial intelligence service (Part 10).

Given a latitude / longitude this service answers:
* ``reverse_geocode()`` — human-readable street address via OpenStreetMap's
  public Nominatim reverse geocoder.
* ``find_ward()`` — the ward polygon (from ``ward_boundaries``) that contains the
  point, via PostGIS ``ST_Contains``. The four reference boundaries are the real
  CivicAgent operational wards for Pune (WARD-1..WARD-4), stored in EPSG:4326.
* ``find_nearby_places()`` — hospitals, schools, bus stops, roads and other
  critical infrastructure within a radius, via PostGIS ``ST_DWithin`` on a
  geography cast (metre-accurate). When the verified ``critical_locations``
  table has nothing for a category the lookup falls back to LIVE OSM data via
  the public Overpass API, and degrades to an empty list (UI: "Nearby
  infrastructure data unavailable") on any remote failure.
* ``calculate_distance()`` — great-circle (haversine) distance, pure math.

External-API discipline (Nominatim / Overpass are *not* authoritative and
enforce rate limits): every remote call is time-bounded and degrades gracefully
on timeout / 429 / connection or JSON failure — it never raises and never blocks
the request. No API key is required.

Ward boundaries are operational-zone approximations anchored on verified Pune
locality coordinates (not the full official PMC tessellation) and are persisted
with ``is_demo=False``; any boundary/facility that IS illustrative demo data
remains flagged ``is_demo=True`` so callers can label it with ``GIS_DEMO_LABEL``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.models import (
    CriticalLocation,
    Ward,
    WardBoundary,
)
from app.models.enums import (
    CriticalLocationCategory,
    InfrastructureDataStatus,
)
from app.schemas.geo import (
    GeoLookupOut,
    GeoPlace,
    ReverseGeocodeOut,
    WardBoundaryOut,
    WardDetected,
    WardListOut,
)

logger = logging.getLogger(__name__)

# Allowed coordinate ranges for GPS lat/lng (WGS 84).
_MIN_LAT, _MAX_LAT = -90.0, 90.0
_MIN_LNG, _MAX_LNG = -180.0, 180.0

# Registered/base locations for field workers are restricted to the Pune
# Municipal Corporation area (Maharashtra, India) — Katraj ~18.45S to Pimpri
# ~18.63N, Hinjewadi ~73.74W to Hadapsar/Kharadi ~73.95E. This is a metro-wide
# guard so a base location is never a random nation/world-wide point, while the
# seed + admin flows place each worker at a distinct real locality inside it.
# The four operational ward polygons (WARD-1..WARD-4) lie within these bounds.
_PUNE_LAT_MIN, _PUNE_LAT_MAX = 18.42, 18.66
_PUNE_LON_MIN, _PUNE_LON_MAX = 73.72, 73.97

# Live-infrastructure tags (Overpass QL snippets) mapped from the DB category.
# Each maps to REAL OpenStreetMap data so a fresh Pune seed still returns a real
# nearby-facility surface from OSM. ROAD / PUBLIC_FACILITY / GOVERNMENT_BUILDING
# previously had no equivalent and returned nothing; they now have live queries
# (major roads, and community/public + government POIs). Categories still absent
# here have no OSM equivalent (e.g. a generic "OTHER" is only DB-seeded).
_OVERPASS_TAGS: dict[CriticalLocationCategory, tuple[str, ...]] = {
    CriticalLocationCategory.HOSPITAL: (
        '["amenity"="hospital"]',
        '["healthcare"="hospital"]',
        '["amenity"="clinic"]',
        '["healthcare"="clinic"]',
    ),
    CriticalLocationCategory.SCHOOL: (
        '["amenity"="school"]',
        '["amenity"="kindergarten"]',
        '["amenity"="college"]',
        '["amenity"="university"]',
    ),
    CriticalLocationCategory.BUS_STOP: (
        '["highway"="bus_stop"]',
        '["amenity"="bus_station"]',
        '["public_transport"="platform"]',
    ),
    CriticalLocationCategory.POLICE_STATION: ('["amenity"="police"]',),
    CriticalLocationCategory.FIRE_STATION: ('["amenity"="fire_station"]',),
    CriticalLocationCategory.TRANSPORT: ('["railway"~"^(station|halt)$"]',),
    CriticalLocationCategory.PUBLIC_FACILITY: (
        '["amenity"~"^(community_centre|library|marketplace|market|post_office|place_of_worship|theatre|cinema|sports_centre|swimming_pool|arts_centre|park)$"]',
    ),
    CriticalLocationCategory.GOVERNMENT_BUILDING: (
        '["office"="government"]',
        '["amenity"="townhall"]',
    ),
    # Major roads (as POI-style centre points from way centres).
    CriticalLocationCategory.ROAD: (
        '["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]',
    ),
}
# OSM key/value rules used to resolve the correct category for each element of a
# combined query (a category=None Overpass fetch returns every bucket at once).
_OSM_CATEGORY_RULES: dict[CriticalLocationCategory, tuple[tuple[str, frozenset[str]], ...]] = {
    CriticalLocationCategory.HOSPITAL: (
        ("amenity", frozenset({"hospital", "clinic"})),
        ("healthcare", frozenset({"hospital", "clinic"})),
    ),
    CriticalLocationCategory.SCHOOL: (
        ("amenity", frozenset({"school", "kindergarten", "college", "university"})),
    ),
    CriticalLocationCategory.BUS_STOP: (
        ("highway", frozenset({"bus_stop"})),
        ("amenity", frozenset({"bus_station"})),
        ("public_transport", frozenset({"platform"})),
    ),
    CriticalLocationCategory.POLICE_STATION: (("amenity", frozenset({"police"})),),
    CriticalLocationCategory.FIRE_STATION: (("amenity", frozenset({"fire_station"})),),
    CriticalLocationCategory.TRANSPORT: (("railway", frozenset({"station", "halt"})),),
    CriticalLocationCategory.ROAD: (
        (
            "highway",
            frozenset({"motorway", "trunk", "primary", "secondary", "tertiary"}),
        ),
    ),
    CriticalLocationCategory.PUBLIC_FACILITY: (
        (
            "amenity",
            frozenset(
                {
                    "community_centre",
                    "library",
                    "marketplace",
                    "market",
                    "post_office",
                    "place_of_worship",
                    "theatre",
                    "cinema",
                    "sports_centre",
                    "swimming_pool",
                    "arts_centre",
                    "park",
                }
            ),
        ),
    ),
    CriticalLocationCategory.GOVERNMENT_BUILDING: (
        ("office", frozenset({"government"})),
        ("building", frozenset({"government"})),
        ("amenity", frozenset({"townhall", "government"})),
    ),
}
# POI categories surfaced as the "critical infrastructure" union (roads excluded;
# roads are reported separately as nearby major roads).
_POI_CATEGORIES: tuple[CriticalLocationCategory, ...] = (
    CriticalLocationCategory.HOSPITAL,
    CriticalLocationCategory.SCHOOL,
    CriticalLocationCategory.BUS_STOP,
    CriticalLocationCategory.POLICE_STATION,
    CriticalLocationCategory.FIRE_STATION,
    CriticalLocationCategory.TRANSPORT,
    CriticalLocationCategory.PUBLIC_FACILITY,
    CriticalLocationCategory.GOVERNMENT_BUILDING,
)


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

    def validate_pune_base_coordinates(self, latitude: float, longitude: float) -> None:
        """Raise ``InvalidCoordinatesError`` if the point is outside the Pune metro area.

        Used for field-worker *base* (registered) locations only — the actual
        GPS position of a worker is never restricted this way.
        """
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not (_PUNE_LAT_MIN <= latitude <= _PUNE_LAT_MAX)
            or not (_PUNE_LON_MIN <= longitude <= _PUNE_LON_MAX)
        ):
            raise InvalidCoordinatesError(
                "Invalid base location: coordinates must be inside the Pune municipal "
                f"area (lat {_PUNE_LAT_MIN}..{_PUNE_LAT_MAX}, "
                f"lon {_PUNE_LON_MIN}..{_PUNE_LON_MAX})."
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
            city=ward.city,
            state=ward.state,
            country=ward.country,
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

        Live-infrastructure fallback: when the verified ``critical_locations``
        table has no rows for a category (as on a fresh Pune seed), real
        OpenStreetMap facilities are fetched from the Overpass API and returned
        as non-demo places. Any remote failure (or ``GIS_OVERPASS_ENABLED`` =
        false) keeps the result empty so the UI shows the distinct
        "temporarily unavailable" state instead of stale demo data.
        """
        places = await self._find_nearby_db(db, latitude, longitude, radius_m, category, limit)
        if not places:
            places = await self._overpass_find(latitude, longitude, radius_m, category, limit)
        return places

    async def _find_nearby_db(
        self,
        db: AsyncSession,
        latitude: float,
        longitude: float,
        radius_m: float,
        category: CriticalLocationCategory | None = None,
        limit: int = 20,
    ) -> list[GeoPlace]:
        """Database-only nearby lookup (no live fallback).

        ``geo_lookup`` calls this directly so it can track the live lookup
        outcome independently for the ``nearby_status`` field.
        """
        self.validate_coordinates(latitude, longitude)
        radius = min(max(radius_m, 0.0), self._settings.GIS_MAX_RADIUS_M)
        gh = Geography(geometry_type="POINT", srid=4326)
        point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)

        stmt = (
            select(CriticalLocation)
            .where(
                CriticalLocation.is_active.is_(True),
                CriticalLocation.verification_status == InfrastructureDataStatus.FOUND,
                CriticalLocation.geom.is_not(None),
                ST_DWithin(CriticalLocation.geom.cast(gh), point.cast(gh), radius),
            )
            .order_by(ST_Distance(CriticalLocation.geom.cast(gh), point.cast(gh)).asc())
            .limit(int(limit))
        )
        if category is not None:
            stmt = stmt.where(CriticalLocation.category == category)

        rows = (await db.execute(stmt)).scalars().all()
        places: list[GeoPlace] = []
        for loc in rows:
            if loc.latitude is None or loc.longitude is None:
                continue
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
        places.sort(key=lambda p: p.distance_m or math.inf)
        return places[:limit]

    async def _overpass_find(
        self,
        latitude: float,
        longitude: float,
        radius_m: float,
        category: CriticalLocationCategory | None,
        limit: int = 20,
        client: httpx.AsyncClient | None = None,
    ) -> list[GeoPlace]:
        """Query the OSM Overpass API for real facilities around a coordinate.

        Backwards-compatible wrapper over ``_fetch_overpass``: returns the real
        facilities or an empty list (never raises). ``client`` lets tests
        inject a mocked transport.
        """
        places, _ok, _source, _cached = await self._fetch_overpass(
            latitude, longitude, radius_m, category, limit, client
        )
        return places

    async def _fetch_overpass(
        self,
        latitude: float,
        longitude: float,
        radius_m: float,
        category: CriticalLocationCategory | None,
        limit: int = 20,
        client: httpx.AsyncClient | None = None,
    ) -> tuple[list[GeoPlace], bool, str | None, bool]:
        """Fetch + parse REAL OpenStreetMap facilities around a coordinate.

        Returns ``(places, ok, source, cached)``. ``ok`` is True only when a
        live Overpass endpoint returned a parseable 200 response — an empty
        ``elements`` array counts as success (the query genuinely found
        nothing). ``source`` is the serving endpoint host (or ``"cache"``) and
        ``cached`` marks a Redis-cache hit. A failed fetch returns
        ``([], False, None, False)`` so callers can show the distinct
        "temporarily unavailable" state instead of silently reporting
        "no facilities within range".

        Each expected failure (disabled, timeout, HTTP 429/5xx, unparseable
        body) falls through to the configured mirror endpoints with a small
        retry budget before giving up.
        """
        if not self._settings.GIS_OVERPASS_ENABLED:
            return [], False, None, False

        tags: list[str] = []
        if category is None:
            tags = [t for block in _OVERPASS_TAGS.values() for t in block]
        else:
            tags = list(_OVERPASS_TAGS.get(category, ()))
        if not tags:
            return [], True, "no-live-equivalent", False

        cache_key = self._cache_key_for(category, latitude, longitude, radius_m)
        cached_payload, is_hit = await self._query_infra_cache(cache_key)
        if is_hit and isinstance(cached_payload, list):
            places = [GeoPlace(**entry) for entry in cached_payload if isinstance(entry, dict)]
            return places, True, "cache", True

        query = self._build_overpass_query(tags, latitude, longitude, int(radius_m), int(limit))
        timeout = float(self._settings.GIS_OVERPASS_TIMEOUT_SECONDS)
        endpoints = self._overpass_endpoints()
        attempts = max(1, int(self._settings.GIS_OVERPASS_MAX_RETRIES) + 1)
        for endpoint in endpoints:
            for _ in range(attempts):
                try:
                    r = await self._overpass_get(endpoint, query, timeout, client)
                except httpx.HTTPError as exc:
                    logger.warning("Overpass %s request failed: %s", endpoint, exc)
                    continue
                if r.status_code != 200:
                    logger.warning(
                        "Overpass %s returned HTTP %s for %s",
                        endpoint,
                        r.status_code,
                        cache_key,
                    )
                    continue
                try:
                    data = r.json()
                except Exception as exc:
                    logger.warning("Overpass %s returned unparseable JSON: %s", endpoint, exc)
                    continue
                places = self._parse_overpass_elements(data, category, latitude, longitude)
                places = places[:limit]
                places.sort(key=lambda p: p.distance_m or math.inf)
                # Cache genuine live successes only (an empty result is real
                # "no facilities", a failure is never cached).
                await self._store_infra_cache(
                    cache_key, [p.model_dump(mode="json") for p in places]
                )
                return places, True, f"overpass:{_host(endpoint)}", False
        return [], False, None, False

    @classmethod
    def _parse_overpass_elements(
        cls,
        data: dict[str, Any],
        category: CriticalLocationCategory | None,
        latitude: float,
        longitude: float,
    ) -> list[GeoPlace]:
        """Convert an Overpass JSON payload into distance-sorted ``GeoPlace``s.

        Each element's own OSM tags are resolved to the correct category via
        ``_OSM_CATEGORY_RULES`` (used when ``category`` is None so a combined
        fetch partitions itself into the right buckets).
        """
        places: list[GeoPlace] = []
        for el in data.get("elements", []):
            if not isinstance(el, dict):
                continue
            el_tags = el.get("tags") or {}
            if "lat" in el and "lon" in el:
                lat, lon = float(el["lat"]), float(el["lon"])
            else:
                center = el.get("center")
                if not center:
                    continue
                lat, lon = float(center["lat"]), float(center["lon"])
            resolved = _osm_category_for(el_tags)
            resolved_category = category if category is not None else resolved
            name = (
                el_tags.get("name")
                or el_tags.get("operator")
                or cls._osm_fallback_name(resolved_category)
            )
            places.append(
                GeoPlace(
                    id=None,
                    name=name,
                    category=resolved_category,
                    address=el_tags.get("addr:full")
                    or el_tags.get("addr:street")
                    or None,
                    latitude=lat,
                    longitude=lon,
                    distance_m=GeoService.calculate_distance(
                        latitude, longitude, lat, lon
                    ),
                    is_demo=False,
                )
            )
        places.sort(key=lambda p: p.distance_m or math.inf)
        return places

    @staticmethod
    def _build_overpass_query(
        tags: list[str], latitude: float, longitude: float, radius_m: int, limit: int
    ) -> str:
        """Build a compact Overpass QL query returning node + way centers."""
        blocks = "".join(
            f"node{t}(around:{radius_m},{latitude},{longitude});"
            f"way{t}(around:{radius_m},{latitude},{longitude});"
            for t in tags
        )
        return (
            "[out:json][timeout:15];"
            f"({blocks});out center tags {limit};"
        )

    @staticmethod
    def _osm_fallback_name(category: CriticalLocationCategory | None) -> str:
        """Human label for an unnamed OSM element in a category lookup."""
        labels = {
            CriticalLocationCategory.HOSPITAL: "Hospital",
            CriticalLocationCategory.SCHOOL: "School",
            CriticalLocationCategory.BUS_STOP: "Bus Stop",
            CriticalLocationCategory.POLICE_STATION: "Police Station",
            CriticalLocationCategory.FIRE_STATION: "Fire Station",
            CriticalLocationCategory.TRANSPORT: "Railway Station",
            CriticalLocationCategory.PUBLIC_FACILITY: "Public Facility",
            CriticalLocationCategory.GOVERNMENT_BUILDING: "Government Building",
            CriticalLocationCategory.ROAD: "Major Road",
        }
        value = labels.get(category) if category is not None else None
        return value or "Nearby facility"

    @staticmethod
    async def _overpass_get(
        url: str,
        query: str,
        timeout: float,
        client: httpx.AsyncClient | None,
    ) -> httpx.Response:
        """GET the Overpass interpreter with the QL as the ``data`` parameter.

        GET (rather than a POST body) is far more reliable against the shared
        community endpoints, which frequently rate-limit or 504 bulk POSTs. The
        ``overpass-api.de`` front-end whitelists the curl user-agent but
        rejects other default clients (406), so the query is sent with a
        curl-style agent.
        """
        headers = {"User-Agent": "curl/8.4.0"}
        if client is not None:
            return await client.get(
                url, params={"data": query}, timeout=timeout, headers=headers
            )
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as c:
            return await c.get(url, params={"data": query})

    def _overpass_endpoints(self) -> list[str]:
        """Primary endpoint + configured mirrors, deduplicated, primary first."""
        endpoints = [self._settings.GIS_OVERPASS_URL]
        for mirror in self._settings.GIS_OVERPASS_MIRRORS.split(","):
            endpoint = mirror.strip()
            if endpoint and endpoint not in endpoints:
                endpoints.append(endpoint)
        return endpoints

    def _cache_namespace(self) -> str:
        ns = self._settings.CONTEXT_CACHE_NAMESPACE
        return ns.rstrip(":")

    def _cache_key_for(
        self,
        category: CriticalLocationCategory | None,
        latitude: float,
        longitude: float,
        radius_m: float,
    ) -> str:
        """Redis key namespacing real nearby-infrastructure results.

        Coordinates are rounded to 5 decimals (~1 m) so nearby lookups share a
        cache entry, while each category + radius stays isolated.
        """
        bucket = (category.value if category is not None else "all").lower()
        return (
            f"{self._cache_namespace()}:nearby:{bucket}:"
            f"{latitude:.5f},{longitude:.5f}:{int(radius_m)}"
        )

    async def _query_infra_cache(self, key: str) -> tuple[Any | None, bool]:
        """Read a cached nearby-infrastructure payload (graceful when Redis is
        down or caching is disabled). Returns ``(payload, is_hit)``."""
        if not self._settings.GIS_CACHE_ENABLED:
            return None, False
        try:
            client = await get_redis()
            raw = await client.get(key)
        except Exception as exc:
            logger.warning("Infrastructure cache GET failed (%s): %s", key, exc)
            return None, False
        if raw is None:
            return None, False
        try:
            return json.loads(raw), True
        except Exception as exc:
            logger.warning("Infrastructure cache payload unreadable (%s): %s", key, exc)
            return None, False

    async def _store_infra_cache(self, key: str, payload: Any) -> None:
        """Persist a genuine live Overpass result (graceful when Redis is down
        or caching is disabled). Never called for failed lookups."""
        if not self._settings.GIS_CACHE_ENABLED or payload is None:
            return
        try:
            client = await get_redis()
            await client.set(
                key, json.dumps(payload), ex=int(self._settings.GIS_CACHE_TTL_SECONDS)
            )
        except Exception as exc:
            logger.warning("Infrastructure cache SET failed (%s): %s", key, exc)

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

        # Registering the real pipeline (lazy import: the registry module
        # imports this module at module level).
        from app.services.infrastructure_registry import InfrastructureRegistry

        registry = InfrastructureRegistry(settings=self._settings)
        critical_radius = float(self._settings.GIS_CRITICAL_RADIUS_M)
        categories = (*_POI_CATEGORIES, CriticalLocationCategory.ROAD)
        limits = {
            CriticalLocationCategory.ROAD: 10,
        }
        registry_has = await registry._registry_counts(db, categories)
        by_category: dict[CriticalLocationCategory, list[GeoPlace]] = {}
        statuses: dict[CriticalLocationCategory, InfrastructureDataStatus] = {}
        for category in categories:
            summary = await registry.resolve_category(
                db,
                latitude=latitude,
                longitude=longitude,
                radius_m=critical_radius,
                category=category,
                limit=limits.get(category, 20),
                client=None,
                registry_has=registry_has,
                geo_service=self,
            )
            statuses[category] = summary.status
            places: list[GeoPlace] = []
            for place in summary.places:
                if place.latitude is None or place.longitude is None:
                    continue
                places.append(
                    GeoPlace(
                        id=uuid.UUID(place.id) if place.id else None,
                        name=place.name,
                        category=place.category,
                        address=place.address,
                        latitude=place.latitude,
                        longitude=place.longitude,
                        distance_m=place.distance_m,
                        is_demo=place.is_demo,
                    )
                )
            by_category[category] = places

        poi = list(_POI_CATEGORIES)
        found_any = any(by_category[c] for c in poi)
        if found_any:
            nearby_status = "available"
        elif any(
            statuses.get(c) == InfrastructureDataStatus.DATA_UNAVAILABLE for c in poi
        ):
            nearby_status = "unavailable"
        else:
            nearby_status = "empty"

        critical = [p for c in poi for p in by_category[c]]
        critical.sort(key=lambda p: p.distance_m or math.inf)

        return GeoLookupOut(
            latitude=latitude,
            longitude=longitude,
            address=address,
            ward=ward,
            nearby_roads=by_category[CriticalLocationCategory.ROAD],
            hospitals=by_category[CriticalLocationCategory.HOSPITAL],
            schools=by_category[CriticalLocationCategory.SCHOOL],
            bus_stops=by_category[CriticalLocationCategory.BUS_STOP],
            police_stations=by_category[CriticalLocationCategory.POLICE_STATION],
            fire_stations=by_category[CriticalLocationCategory.FIRE_STATION],
            public_facilities=by_category[CriticalLocationCategory.PUBLIC_FACILITY],
            government_buildings=by_category[
                CriticalLocationCategory.GOVERNMENT_BUILDING
            ],
            critical_infrastructure=critical,
            nearby_status=nearby_status,
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
            centroid = await self._boundary_centroid(db, boundary.id)
            wards.append(
                WardBoundaryOut(
                    ward_id=ward.id,
                    name=ward.name,
                    code=ward.code,
                    description=ward.description,
                    city=ward.city,
                    state=ward.state,
                    country=ward.country,
                    is_demo=boundary.is_demo,
                    geometry=rings,
                    centroid=centroid,
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

    async def _boundary_centroid(
        self, db: AsyncSession, boundary_id: uuid.UUID
    ) -> list[float] | None:
        """Return the ward boundary's centroid as ``[lng, lat]`` (for labels)."""
        from sqlalchemy import text

        if boundary_id is None:
            return None
        result = await db.execute(
            text(
                "SELECT ST_AsGeoJSON(ST_Transform(ST_Force2D(centroid), 4326)) "
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
        if coords and len(coords) >= 2:
            return [float(coords[0]), float(coords[1])]
        return None


def get_geo_service(settings: Settings | None = None) -> GeoService:
    return GeoService(settings=settings or get_settings())


def _osm_category_for(tags: dict[str, Any]) -> CriticalLocationCategory:
    """Resolve the correct category for an OSM element from its tag values."""
    lowered = {key: (value or "").strip().lower() for key, value in tags.items()}
    for category, rules in _OSM_CATEGORY_RULES.items():
        for key, values in rules:
            value = lowered.get(key)
            if value and value in values:
                return category
    return CriticalLocationCategory.OTHER


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return url
