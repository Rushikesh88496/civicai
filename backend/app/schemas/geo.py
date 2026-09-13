"""Schemas for the GIS / Ward detection & spatial intelligence endpoints (Part 10).

The GIS service resolves raw coordinates (latitude / longitude) into a reverse
geocoded address, the containing ward (via point-in-polygon on demo boundaries),
nearby roads, hospitals, schools, bus stops, and general critical infrastructure.
Every boundary / facility carries an ``is_demo`` flag so the UI can label
illustrative (non-authoritative) data with the configured demo label.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import CriticalLocationCategory


class GeoLookupIn(BaseModel):
    """Coordinates (and optional radius) for a spatial-intelligence lookup."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: float | None = Field(default=None, gt=0)


class GeoPlace(BaseModel):
    """A single nearby facility / critical infrastructure record."""

    # DB-sourced places have an id; live OSM (Overpass) places have none.
    id: uuid.UUID | None = None
    name: str
    category: CriticalLocationCategory
    address: str | None = None
    latitude: float
    longitude: float
    distance_m: float | None = None
    is_demo: bool = True


class WardBoundaryOut(BaseModel):
    """A ward with its display metadata and (optionally) its boundary ring."""

    ward_id: uuid.UUID
    name: str
    code: str
    description: str | None = None
    # Administrative geography of the operational ward.
    city: str = "Pune"
    state: str = "Maharashtra"
    country: str = "India"
    is_demo: bool = False
    # A GeoJSON-style ring of [lng, lat] vertices (EPSG:4326). Omitted when the
    # caller only needs the ward list, included for map rendering.
    geometry: list[list[float]] | None = None
    # Ward label anchor [lng, lat] (from ST_Centroid), for map labels.
    centroid: list[float] | None = None


class WardDetected(BaseModel):
    """The ward that contains a given coordinate, if the boundaries cover it."""

    ward_id: uuid.UUID
    name: str
    code: str
    description: str | None = None
    city: str = "Pune"
    state: str = "Maharashtra"
    country: str = "India"
    is_demo: bool = False


class ReverseGeocodeOut(BaseModel):
    """Result of reverse-geocoding a coordinate (via OpenStreetMap Nominatim)."""

    address: str | None = None
    display_name: str | None = None
    source: str = "nominatim"
    # True when the reverse geocoder was unavailable and we returned a local
    # (e.g. ward-based) fallback rather than a true address.
    degraded: bool = False


class GeoLookupOut(BaseModel):
    """Full spatial intelligence payload for a set of coordinates."""

    latitude: float
    longitude: float
    address: ReverseGeocodeOut | None = None
    ward: WardDetected | None = None
    nearby_roads: list[GeoPlace] = Field(default_factory=list)
    hospitals: list[GeoPlace] = Field(default_factory=list)
    schools: list[GeoPlace] = Field(default_factory=list)
    bus_stops: list[GeoPlace] = Field(default_factory=list)
    police_stations: list[GeoPlace] = Field(default_factory=list)
    fire_stations: list[GeoPlace] = Field(default_factory=list)
    public_facilities: list[GeoPlace] = Field(default_factory=list)
    government_buildings: list[GeoPlace] = Field(default_factory=list)
    critical_infrastructure: list[GeoPlace] = Field(default_factory=list)
    # Whether REAL nearby infrastructure could be resolved for this coordinate:
    #   "available"   — at least one facility was found (DB or live OSM).
    #   "empty"       — every lookup succeeded but nothing exists within range.
    #   "unavailable" — the live (OSM) lookup failed and the DB had no data, so
    #                   "no facilities" is NOT a claim. The UI must show a
    #                   distinct "temporarily unavailable" state.
    nearby_status: str = "available"
    radius_m: float
    demo_label: str
    calculated_at: datetime


class GeoDistanceIn(BaseModel):
    """Two coordinates whose great-circle distance should be computed."""

    latitude_a: float = Field(ge=-90, le=90)
    longitude_a: float = Field(ge=-180, le=180)
    latitude_b: float = Field(ge=-90, le=90)
    longitude_b: float = Field(ge=-180, le=180)


class GeoDistanceOut(BaseModel):
    distance_km: float
    distance_m: float


class WardListOut(BaseModel):
    wards: list[WardBoundaryOut]
