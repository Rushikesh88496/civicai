"""Schemas for the Real Nearby Infrastructure Data System (Part 35).

The officer/admin surface consumes three things:

* ``NearbyInfrastructureOut`` — the data-quality-aware "what is near this
  point?" answer resolved against the verified registry (PostGIS), with an
  explicit per-category state. ``DATA_UNAVAILABLE`` is never presented as
  "zero facilities"; ``PENDING_VERIFICATION`` marks live, unpersisted signal.
* ``RegistryAssetOut`` / ``RegistrySummaryOut`` — the verified facility
  registry (admin view): provenance (source / dataset / url / id), the
  data-quality state and freshness for every record.
* ``RegistrySyncOut`` — the result of an ingestion run (source, per-category
  fetched / inserted / updated / skipped counts, dedupe totals, duration).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    CriticalLocationCategory,
    InfrastructureDataStatus,
)


class NearbyPlace(BaseModel):
    """A single verified (or pending) nearby facility record."""

    id: str | None = None
    name: str
    category: CriticalLocationCategory
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_m: float | None = None
    verification_status: InfrastructureDataStatus = InfrastructureDataStatus.FOUND
    source: str | None = None
    source_dataset: str | None = None
    # OSM-level address / operator detail where known.
    kind: str | None = None
    is_demo: bool = False


class NearbyCategorySummary(BaseModel):
    """Per-category nearby result with its honest data-quality state."""

    category: CriticalLocationCategory
    status: InfrastructureDataStatus
    count: int = 0
    places: list[NearbyPlace] = Field(default_factory=list)
    # Human-readable explanation of the reported state.
    note: str = ""


class NearbyInfrastructureIn(BaseModel):
    """Request for the registry-aware nearby-infrastructure lookup."""

    latitude: float
    longitude: float
    # Server-clamped to ([0, GIS_MAX_RADIUS_M]); defaults to
    # INFRASTRUCTURE_SEARCH_RADIUS_METERS.
    radius_m: float | None = None
    # Optional category subset (defaults to the full nearby POI set).
    categories: list[CriticalLocationCategory] | None = None
    # Max facilities surfaced per category.
    limit: int = Field(default=20, ge=1, le=50)
    use_cache: bool = True


class NearbyInfrastructureOut(BaseModel):
    """The resolved nearby-infrastructure answer for a coordinate."""

    latitude: float
    longitude: float
    radius_m: float
    categories: list[NearbyCategorySummary]
    # Overall state:
    #   "resolved" — every category resolved from verified data.
    #   "partial"  — some categories resolved, others live/pending or degraded.
    #   "degraded" — at least one category could not be performed at all.
    search_status: str = "resolved"
    # Provenance of the answer (registry dataset count / live fallback used).
    registry_total: int = 0
    registry_categories: dict[str, int] = Field(default_factory=dict)
    live_fallback_used: bool = False
    query_id: str | None = None
    cached: bool = False
    resolved_at: datetime


class RegistryAssetOut(BaseModel):
    """A verified facility registry record."""

    id: str
    name: str
    category: CriticalLocationCategory
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    source: str | None = None
    source_dataset: str | None = None
    source_url: str | None = None
    source_id: str | None = None
    verification_status: InfrastructureDataStatus
    last_verified_at: datetime | None = None
    ward_id: str | None = None
    ward_code: str | None = None
    ward_name: str | None = None
    is_demo: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RegistrySummaryOut(BaseModel):
    """Aggregated state of the verified facility registry."""

    total: int
    verified: int
    pending: int
    unlocated: int
    by_category: dict[str, int]
    by_status: dict[str, int]
    by_source: dict[str, int]
    last_verified_at: datetime | None = None


class RegistryListOut(BaseModel):
    items: list[RegistryAssetOut]
    total: int
    limit: int
    offset: int


class RegistryCategoryCounts(BaseModel):
    category: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_duplicate: int = 0
    skipped_unparseable: int = 0
    failed: int = 0


class RegistrySyncOut(BaseModel):
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    source: str
    source_dataset: str | None = None
    source_url: str | None = None
    wards_covered: int = 0
    fetched_total: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_duplicate: int = 0
    skipped_unparseable: int = 0
    failed_total: int = 0
    by_category: list[RegistryCategoryCounts] = Field(default_factory=list)
    message: str = ""


class RegistrySyncIn(BaseModel):
    # source == "openstreetmap" runs the live Overpass ingestion; any other
    # value is reserved for file/API-based dataset ingestion.
    source: str = "openstreetmap"
    # Optional file path for a locally downloaded dataset (CSV/JSON) when a
    # verified external dataset is available on disk.
    file_path: str | None = None
    force: bool = False


__all__ = [
    "NearbyCategorySummary",
    "NearbyInfrastructureIn",
    "NearbyInfrastructureOut",
    "NearbyPlace",
    "RegistryAssetOut",
    "RegistryCategoryCounts",
    "RegistryListOut",
    "RegistrySummaryOut",
    "RegistrySyncIn",
    "RegistrySyncOut",
]
