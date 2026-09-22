"""Real Nearby Infrastructure Data System — service layer (Part 35).

Replaces the per-request "demo or live-OSM" nearby lookups with a persistent,
provenance-backed facility registry built from REAL data.

Registry (``critical_locations``, reused as the existing nearby-facility
registry — no second registry is created):

* ``ingest_from_overpass`` — fetches real OpenStreetMap facilities (hospitals,
  schools, bus stops, police/fire stations, transit, public & government
  buildings, major roads) for each operational ward's bounding box, resolves
  each candidate into its ward via PostGIS point-in-polygon, de-dupes on
  (``source``, ``source_id``) and upserts with ``FOUND`` + full provenance.
  Records without parseable coordinates are stored ``PENDING_VERIFICATION``
  (never given invented coordinates).
* ``find_nearby`` — answers "what verified facilities are near this point?"
  with an explicit per-category data-quality state. A completed search that
  found nothing is ``NO_VERIFIED_RECORDS``; a lookup that could not be performed
  at all is ``DATA_UNAVAILABLE`` — the two are NEVER conflated. Categories with
  no registry coverage fall back to live Overpass and are surfaced as
  ``PENDING_VERIFICATION`` (real signal, not persisted fact).
* caching — genuine resolved answers are cached in Redis; failures never are.
* registry administration — summarize/list the registry for the officer UI.

Search-radius discipline matches the rest of the app (geography-cast metres),
distances are metre-accurate ``ST_Distance`` on a geography cast, and all
external calls degrade gracefully (never raise, never block).
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import math
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.models import CriticalLocation
from app.models.enums import CriticalLocationCategory, InfrastructureDataStatus
from app.schemas.geo import GeoPlace
from app.schemas.nearby import (
    NearbyCategorySummary,
    NearbyInfrastructureOut,
    NearbyPlace,
    RegistryAssetOut,
    RegistryCategoryCounts,
    RegistryListOut,
    RegistrySummaryOut,
    RegistrySyncOut,
)
from app.services.geo_service import (
    _OVERPASS_TAGS,
    GeoService,
    _host,
    _osm_category_for,
)

logger = logging.getLogger(__name__)

# POI categories surfaced by the real nearby pipeline (roads reported apart).
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

_NEARBY_CATEGORIES: tuple[CriticalLocationCategory, ...] = (
    *_POI_CATEGORIES,
    CriticalLocationCategory.ROAD,
)

# OSM source attribution used on every ingested record.
_OSM_DATASET = "OpenStreetMap (Overpass API, Pune, Maharashtra)"
_OSM_URL = "https://www.openstreetmap.org/about/contributors/"

_VERIFIED = InfrastructureDataStatus.FOUND


class InfrastructureRegistry:
    """Facade over the verified facility registry + nearby pipeline."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Ward bounding boxes (from the real ward boundary polygons)
    # ------------------------------------------------------------------ #
    async def _ward_bboxes(
        self, db: AsyncSession
    ) -> list[tuple[uuid.UUID, str, str, tuple[float, float, float, float]]]:
        """Return ``(ward_id, code, name, (south, west, north, east))`` per ward."""
        rows = (
            await db.execute(
                text(
                    "SELECT wb.ward_id, w.code, w.name, "
                    "ST_YMin(wb.geom) AS south, ST_XMin(wb.geom) AS west, "
                    "ST_YMax(wb.geom) AS north, ST_XMax(wb.geom) AS east "
                    "FROM ward_boundaries wb JOIN wards w ON w.id = wb.ward_id "
                    "ORDER BY w.code"
                )
            )
        ).all()
        out: list[tuple[uuid.UUID, str, str, tuple[float, float, float, float]]] = []
        for row in rows:
            if row.south is None:
                continue
            out.append(
                (
                    row.ward_id,
                    row.code,
                    row.name,
                    (float(row.south), float(row.west), float(row.north), float(row.east)),
                )
            )
        return out

    # ------------------------------------------------------------------ #
    # Overpass ingestion (real data)
    # ------------------------------------------------------------------ #
    def _overpass_endpoint(self) -> str:
        return (self._settings.OVERPASS_URL or self._settings.GIS_OVERPASS_URL).strip()

    def _overpass_endpoints(self) -> list[str]:
        primary = self._overpass_endpoint()
        endpoints = [primary] if primary else []
        for mirror in self._settings.GIS_OVERPASS_MIRRORS.split(","):
            endpoint = mirror.strip()
            if endpoint and endpoint not in endpoints:
                endpoints.append(endpoint)
        return endpoints

    @staticmethod
    def _build_bbox_query(
        tags: list[str], bbox: tuple[float, float, float, float], limit: int
    ) -> str:
        south, west, north, east = bbox
        blocks = "".join(
            f"node{t}({south},{west},{north},{east});way{t}({south},{west},{north},{east});"
            for t in tags
        )
        return f"[out:json][timeout:30];({blocks});out center tags {int(limit)};"

    async def _overpass_bbox_get(
        self,
        url: str,
        query: str,
        timeout: float,
        client: httpx.AsyncClient | None,
    ) -> httpx.Response:
        headers = {"User-Agent": "curl/8.4.0"}
        if client is not None:
            return await client.get(url, params={"data": query}, timeout=timeout, headers=headers)
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as c:
            return await c.get(url, params={"data": query})

    @staticmethod
    def _parse_candidates(
        data: dict[str, Any],
        category: CriticalLocationCategory | None,
    ) -> list[dict[str, Any]]:
        """Raw Overpass elements -> candidate records (validated coordinates)."""
        candidates: list[dict[str, Any]] = []
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
            if not (math.isfinite(lat) and math.isfinite(lon)):
                continue
            resolved = _osm_category_for(el_tags)
            cat = category if category is not None else resolved
            if cat == CriticalLocationCategory.OTHER:
                continue
            etype = el.get("type") or "node"
            source_id = f"{etype}/{el.get('id')}"
            name = el_tags.get("name") or el_tags.get("operator") or _fallback_name(cat)
            candidates.append(
                {
                    "name": name,
                    "category": cat,
                    "latitude": lat,
                    "longitude": lon,
                    "address": (el_tags.get("addr:full") or el_tags.get("addr:street") or None),
                    "source_id": source_id,
                    "source_url": f"https://www.openstreetmap.org/{etype}/{el.get('id')}",
                    "tags": el_tags,
                    "kind": _kind_from_tags(el_tags, cat),
                }
            )
        return candidates

    async def _fetch_bbox_candidates(
        self,
        bbox: tuple[float, float, float, float],
        category: CriticalLocationCategory,
        client: httpx.AsyncClient | None = None,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
        """Fetch real facilities in a ward bbox; returns ``(candidates, ok, source)``.

        The bulk-import budget (``INFRASTRUCTURE_IMPORT_*``) is intentionally
        more generous than the per-request live fallback because a ward-bbox
        query is substantially heavier than the small radius lookup.
        """
        tags = list(_OVERPASS_TAGS.get(category, ()))
        if not tags:
            return [], False, "no-live-equivalent"
        query = self._build_bbox_query(
            tags, bbox, int(self._settings.INFRASTRUCTURE_IMPORT_LIMIT_PER_CATEGORY)
        )
        timeout = float(
            timeout if timeout is not None else self._settings.INFRASTRUCTURE_IMPORT_TIMEOUT_SECONDS
        )
        retries = int(
            max_retries
            if max_retries is not None
            else self._settings.INFRASTRUCTURE_IMPORT_MAX_RETRIES
        )
        attempts = max(1, retries + 1)
        for endpoint in self._overpass_endpoints():
            for _ in range(attempts):
                try:
                    r = await self._overpass_bbox_get(endpoint, query, timeout, client)
                except httpx.HTTPError as exc:
                    logger.warning("Overpass %s bbox request failed: %s", endpoint, exc)
                    continue
                if r.status_code in (429, 502, 503, 504):
                    logger.warning(
                        "Overpass %s returned HTTP %s for %s in %s",
                        endpoint,
                        r.status_code,
                        category.value,
                        "bbox",
                    )
                    continue
                if r.status_code != 200:
                    logger.warning("Overpass %s returned HTTP %s", endpoint, r.status_code)
                    continue
                try:
                    data = r.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Overpass %s unparseable JSON: %s", endpoint, exc)
                    continue
                candidates = self._parse_candidates(data, category)
                return candidates, True, _host(endpoint)
        return [], False, None

    async def _resolve_wards(
        self,
        db: AsyncSession,
        points: list[tuple[str, float, float]],
    ) -> dict[str, uuid.UUID | None]:
        """Map candidate keys -> ward_id via PostGIS point-in-polygon (bulk)."""
        if not points:
            return {}
        entries = ", ".join(
            f"('{key}', ST_SetSRID(ST_MakePoint({lon!r}, {lat!r}), 4326))"
            for key, lat, lon in points
        )
        sql = (
            "SELECT p.k AS k, wb.ward_id AS ward_id FROM "
            f"(VALUES {entries}) AS p(k, geom) "
            "JOIN ward_boundaries wb ON ST_Contains(wb.geom, p.geom)"
        )
        rows = (await db.execute(text(sql))).all()
        result: dict[str, uuid.UUID | None] = {key: None for key, *_ in points}
        for row in rows:
            result[row.k] = row.ward_id
        return result

    @staticmethod
    def _dedupe_candidates(
        candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """Drop intra-batch duplicates by ``(source_id, category, name, coords)``.

        Returns ``(unique, dropped)``. Cross-run de-duplication is enforced by
        the partial unique index on (``source``, ``source_id``).
        """
        seen: set[tuple[str, str, str]] = set()
        unique: list[dict[str, Any]] = []
        dropped = 0
        for cand in candidates:
            key = (
                cand["source_id"],
                cand["category"].value,
                f"{cand['latitude']:.6f},{cand['longitude']:.6f}",
            )
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            unique.append(cand)
        return unique, dropped

    async def _upsert_candidates(
        self,
        db: AsyncSession,
        candidates: list[dict[str, Any]],
        *,
        source: str,
        source_dataset: str,
        source_url: str | None,
        ward_map: dict[str, uuid.UUID | None],
        batch_id: str,
        counts: RegistryCategoryCounts,
    ) -> None:
        """Idempotent upsert keyed on ``(source, source_id)`` (real provenance)."""
        if not candidates:
            return
        now = datetime.now(UTC)
        source_ids = [c["source_id"] for c in candidates]
        existing_rows = (
            (
                await db.execute(
                    select(CriticalLocation).where(
                        CriticalLocation.source == source,
                        CriticalLocation.source_id.in_(source_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing = {row.source_id: row for row in existing_rows}

        for cand in candidates:
            ward_id = ward_map.get(cand.get("_key", "")) or None
            metadata = {
                "osm_tags": cand.get("tags") or {},
                "kind": cand.get("kind"),
                "import_batch": batch_id,
                "imported_at": now.isoformat(),
            }
            row = existing.get(cand["source_id"])
            if row is not None:
                changed = (
                    row.name != cand["name"]
                    or row.latitude != cand["latitude"]
                    or row.longitude != cand["longitude"]
                    or row.address != cand["address"]
                    or row.ward_id != ward_id
                    or row.verification_status != _VERIFIED
                    or not row.is_active
                )
                row.name = cand["name"]
                row.latitude = cand["latitude"]
                row.longitude = cand["longitude"]
                row.address = cand["address"]
                row.asset_metadata = metadata
                row.ward_id = ward_id
                row.verification_status = _VERIFIED
                row.last_verified_at = now
                row.is_demo = False
                row.is_active = True
                row.geom = f"SRID=4326;POINT({cand['longitude']} {cand['latitude']})"
                if changed:
                    counts.updated += 1
                else:
                    counts.skipped_duplicate += 1
                continue
            counts.inserted += 1
            db.add(
                CriticalLocation(
                    name=cand["name"],
                    category=cand["category"],
                    latitude=cand["latitude"],
                    longitude=cand["longitude"],
                    address=cand["address"],
                    is_demo=False,
                    source=source,
                    source_dataset=source_dataset,
                    source_url=cand.get("source_url") or source_url,
                    source_id=cand["source_id"],
                    verification_status=_VERIFIED,
                    last_verified_at=now,
                    asset_metadata=metadata,
                    ward_id=ward_id,
                    is_active=True,
                    geom=f"SRID=4326;POINT({cand['longitude']} {cand['latitude']})",
                )
            )

    async def ingest_from_overpass(
        self,
        db: AsyncSession,
        client: httpx.AsyncClient | None = None,
        *,
        force: bool = False,
        progress: Callable[[str, str, bool, int], None] | None = None,
    ) -> RegistrySyncOut:
        """Ingest REAL OpenStreetMap facilities for every operational ward.

        Ward x category fetches run under a bounded concurrency across the
        configured mirrors with the dedicated import timeout/retry budget, so a
        busy provider degrades gracefully instead of stalling the run. The main
        pass is followed by up to ``INFRASTRUCTURE_IMPORT_BACKFILL_ROUNDS``
        backfill rounds (with a short delay between rounds) that retry only the
        (ward x category) buckets which failed transiently — a region's category
        is never left permanently uncovered by a one-off provider hiccup (the
        historical root cause of "same GPS, different categories" between
        installations). A bucket that still fails every round is counted as
        failed; no record is ever fabricated.

        ``progress(ward_code, category, ok, fetched)`` is invoked after every
        completed ward x category outcome so long-running imports stay
        observable; each completed task is committed immediately so an
        interrupted run never discards already-verified facilities.
        """
        started_at = datetime.now(UTC)
        started_mono = time.monotonic()
        bboxes = await self._ward_bboxes(db)
        by_category = {
            cat: RegistryCategoryCounts(category=cat.value) for cat in _NEARBY_CATEGORIES
        }
        batch_id = started_at.strftime("%Y%m%d%H%M%S%f")

        tasks = [
            (ward_id, code, name, bbox, category)
            for ward_id, code, name, bbox in bboxes
            for category in _NEARBY_CATEGORIES
        ]
        concurrency = max(1, int(self._settings.INFRASTRUCTURE_IMPORT_CONCURRENCY))
        backfill_rounds = max(0, int(self._settings.INFRASTRUCTURE_IMPORT_BACKFILL_ROUNDS))
        backfill_delay = max(
            0.0, float(self._settings.INFRASTRUCTURE_IMPORT_BACKFILL_DELAY_SECONDS)
        )
        transient_errors = 0

        async def run(
            ward_code: str,
            bbox: tuple[float, float, float, float],
            category: CriticalLocationCategory,
        ):
            try:
                candidates, ok, _endpoint = await self._fetch_bbox_candidates(
                    bbox, category, client
                )
            except Exception as exc:  # noqa: BLE001 - never fail the whole sync
                logger.warning("Ingest %s/%s failed: %s", ward_code, category.value, exc)
                return ward_code, category, [], False
            return ward_code, category, candidates, ok

        pending = tasks
        for round_index in range(backfill_rounds + 1):
            is_final = round_index >= backfill_rounds
            still_failed: list[Any] = []
            for chunk_start in range(0, len(pending), max(1, concurrency)):
                chunk = pending[chunk_start : chunk_start + max(1, concurrency)]
                outcomes = await asyncio.gather(
                    *[run(code, bbox, category) for _, code, _name, bbox, category in chunk]
                )
                for task, (c_code, c_cat, candidates, ok) in zip(chunk, outcomes):
                    _ward_id, code, _name, _bbox, category = task
                    counts = by_category[category]
                    if not ok:
                        if is_final:
                            transient_errors += 1
                            counts.failed += 1
                            if progress is not None:
                                progress(c_code, c_cat.value, False, 0)
                        else:
                            still_failed.append(task)
                        continue
                    counts.fetched += len(candidates)
                    unique, dropped = self._dedupe_candidates(candidates)
                    counts.skipped_duplicate += dropped
                    for cand in unique:
                        cand["_key"] = f"{code}:{cand['source_id']}"
                    ward_map = await self._resolve_wards(
                        db, [(c["_key"], c["latitude"], c["longitude"]) for c in unique]
                    )
                    await self._upsert_candidates(
                        db,
                        unique,
                        source="openstreetmap",
                        source_dataset=_OSM_DATASET,
                        source_url=_OSM_URL,
                        ward_map=ward_map,
                        batch_id=batch_id,
                        counts=counts,
                    )
                    await db.commit()
                    if progress is not None:
                        progress(code, category.value, True, len(unique))
            if not still_failed:
                break
            if backfill_delay > 0 and not is_final:
                await asyncio.sleep(backfill_delay)
            pending = still_failed

        finished_at = datetime.now(UTC)
        fetched_total = sum(c.fetched for c in by_category.values())
        inserted = sum(c.inserted for c in by_category.values())
        updated = sum(c.updated for c in by_category.values())
        skipped = sum(c.skipped_duplicate for c in by_category.values())
        failed = sum(c.failed for c in by_category.values())
        message = (
            f"Imported {inserted} new + updated {updated} real Pune facilities "
            f"(skipped {skipped} unchanged, {failed} ward/category buckets still failed "
            f"after {backfill_rounds} backfill round(s)). "
            f"Source: {_OSM_DATASET}."
        )
        return RegistrySyncOut(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=round(time.monotonic() - started_mono, 2),
            source="openstreetmap",
            source_dataset=_OSM_DATASET,
            source_url=_OSM_URL,
            wards_covered=len(bboxes),
            fetched_total=fetched_total,
            inserted=inserted,
            updated=updated,
            skipped_duplicate=skipped,
            skipped_unparseable=0,
            failed_total=failed,
            by_category=list(by_category.values()),
            message=message,
        )

    # ------------------------------------------------------------------ #
    # File ingestion for genuine external (gov/UDISE/OpenCity) datasets
    # ------------------------------------------------------------------ #
    async def ingest_from_file(
        self,
        db: AsyncSession,
        path: str,
        *,
        source: str,
        source_dataset: str,
        source_url: str | None,
    ) -> RegistrySyncOut:
        """Ingest a normalized CSV/JSON dataset from disk (real import artifacts).

        Expected CSV columns: ``name``, ``category`` (CriticalLocationCategory
        value or label), ``latitude``, ``longitude``, ``address``, ``source_id``.
        Records whose coordinates are missing are kept as ``PENDING_VERIFICATION``
        registry candidates — never given invented coordinates.
        """
        started_at = datetime.now(UTC)
        started_mono = time.monotonic()
        batch_id = started_at.strftime("%Y%m%d%H%M%S%f")
        fp = Path(path)
        if not fp.is_file():
            raise FileNotFoundError(f"Dataset file not found: {path}")

        raw: list[dict[str, Any]] = []
        if fp.suffix.lower() == ".csv":
            with fp.open(newline="", encoding="utf-8-sig") as fh:
                raw = [dict(row) for row in csv.DictReader(fh)]
        else:
            payload = json.loads(fp.read_text(encoding="utf-8"))
            raw = payload.get("features", payload) if isinstance(payload, dict) else payload

        by_category: dict[CriticalLocationCategory, RegistryCategoryCounts] = {}
        for cat in _NEARBY_CATEGORIES:
            by_category.setdefault(cat, RegistryCategoryCounts(category=cat.value))
        by_category.setdefault(
            CriticalLocationCategory.OTHER, RegistryCategoryCounts(category="OTHER")
        )

        candidates: list[dict[str, Any]] = []
        for idx, entry in enumerate(raw):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            cat = _category_from_input(entry.get("category") or "OTHER")
            counts = by_category.setdefault(cat, RegistryCategoryCounts(category=cat.value))
            lat = _num(entry.get("latitude"))
            lon = _num(entry.get("longitude"))
            source_id = str(entry.get("source_id") or f"{source}:{idx}").strip()
            if lat is None or lon is None or not (math.isfinite(lat) and math.isfinite(lon)):
                # Honest candidate: no coordinates -> never invent any.
                db.add(
                    CriticalLocation(
                        name=name,
                        category=cat,
                        latitude=None,
                        longitude=None,
                        address=entry.get("address") or None,
                        is_demo=False,
                        source=source,
                        source_dataset=source_dataset,
                        source_url=source_url,
                        source_id=source_id,
                        verification_status=InfrastructureDataStatus.PENDING_VERIFICATION,
                        last_verified_at=None,
                        asset_metadata={
                            "import_batch": batch_id,
                            "imported_at": started_at.isoformat(),
                            "source_row": idx,
                            "unlocated": True,
                        },
                        is_active=True,
                        geom=None,
                    )
                )
                counts.inserted += 1
                continue
            candidates.append(
                {
                    "name": name,
                    "category": cat,
                    "latitude": lat,
                    "longitude": lon,
                    "address": entry.get("address") or None,
                    "source_id": source_id,
                    "source_url": source_url,
                    "tags": {},
                    "kind": None,
                }
            )
            counts.fetched += 1

        unique, dropped = self._dedupe_candidates(candidates)
        for cand in unique:
            cand["_key"] = f"file:{source}:{cand['source_id']}"
        ward_map = await self._resolve_wards(
            db, [(c["_key"], c["latitude"], c["longitude"]) for c in unique]
        )
        # Route file candidates into their category counters by inserting through
        # a lightweight path that mirrors the OSM upsert.
        grouped: dict[CriticalLocationCategory, list[dict[str, Any]]] = {}
        for cand in unique:
            grouped.setdefault(cand["category"], []).append(cand)
        for cat, items in grouped.items():
            counts = by_category[cat]
            await self._upsert_candidates(
                db,
                items,
                source=source,
                source_dataset=source_dataset,
                source_url=source_url,
                ward_map=ward_map,
                batch_id=batch_id,
                counts=counts,
            )
        await db.commit()

        finished_at = datetime.now(UTC)
        return RegistrySyncOut(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=round(time.monotonic() - started_mono, 2),
            source=source,
            source_dataset=source_dataset,
            source_url=source_url,
            wards_covered=0,
            fetched_total=sum(c.fetched for c in by_category.values()),
            inserted=sum(c.inserted for c in by_category.values()),
            updated=sum(c.updated for c in by_category.values()),
            skipped_duplicate=sum(c.skipped_duplicate for c in by_category.values()),
            skipped_unparseable=0,
            failed_total=0,
            by_category=[
                c
                for c in by_category.values()
                if c.category == "OTHER" or c.fetched or c.inserted or c.updated
            ],
            message="",
        )

    # ------------------------------------------------------------------ #
    # Registry-aware nearby search (honest data-quality states)
    # ------------------------------------------------------------------ #
    async def _registry_counts(
        self, db: AsyncSession, categories: list[CriticalLocationCategory]
    ) -> dict[CriticalLocationCategory, int]:
        """Active verified records per category (registry coverage)."""
        rows = (
            await db.execute(
                select(
                    CriticalLocation.category,
                    func.count(CriticalLocation.id),
                )
                .where(
                    CriticalLocation.is_active.is_(True),
                    CriticalLocation.verification_status == _VERIFIED,
                    CriticalLocation.category.in_(categories),
                    CriticalLocation.geom.is_not(None),
                )
                .group_by(CriticalLocation.category)
            )
        ).all()
        return {
            CriticalLocationCategory(r[0].value if hasattr(r[0], "value") else r[0]): int(r[1])
            for r in rows
        }

    async def _nearby_from_registry(
        self,
        db: AsyncSession,
        latitude: float,
        longitude: float,
        radius_m: float,
        categories: list[CriticalLocationCategory],
        limit: int,
    ) -> dict[CriticalLocationCategory, list[CriticalLocation]]:
        """Distance-sorted registry records within ``radius_m`` (PostGIS)."""
        gh = Geography(geometry_type="POINT", srid=4326)
        point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
        rows = (
            (
                await db.execute(
                    select(CriticalLocation)
                    .where(
                        CriticalLocation.is_active.is_(True),
                        CriticalLocation.verification_status == _VERIFIED,
                        CriticalLocation.geom.is_not(None),
                        CriticalLocation.category.in_(categories),
                        ST_DWithin(CriticalLocation.geom.cast(gh), point.cast(gh), radius_m),
                    )
                    .order_by(ST_Distance(CriticalLocation.geom.cast(gh), point.cast(gh)).asc())
                    .limit(int(limit))
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[CriticalLocationCategory, list[CriticalLocation]] = {}
        for row in rows:
            grouped.setdefault(row.category, []).append(row)
        return grouped

    async def resolve_category(
        self,
        db: AsyncSession,
        *,
        latitude: float,
        longitude: float,
        radius_m: float,
        category: CriticalLocationCategory,
        limit: int = 20,
        client: httpx.AsyncClient | None = None,
        registry_has: dict[CriticalLocationCategory, int] | None = None,
        geo_service: GeoService | None = None,
    ) -> NearbyCategorySummary:
        """Resolve one category with an honest data-quality state.

        ``geo_service`` may be passed so callers (e.g. ``GeoService.geo_lookup``)
        can inject their own instance — preserving monkeypatched test/fallback
        behavior — instead of the default minted instance.
        """
        # Protect against wildly large / negative radius from callers.
        radius = min(max(float(radius_m), 0.0), float(self._settings.GIS_MAX_RADIUS_M))
        nearby = await self._nearby_from_registry(
            db, latitude, longitude, radius, [category], limit
        )
        rows = nearby.get(category, [])
        if rows:
            places = [_to_nearby_place(row, latitude, longitude) for row in rows]
            return NearbyCategorySummary(
                category=category,
                status=InfrastructureDataStatus.FOUND,
                count=len(places),
                places=places,
                note=(
                    f"{len(places)} verified {_label(category).lower()}(s) within {int(radius)} m."
                ),
            )

        registry_has = registry_has or {}
        known = registry_has.get(category, 0)
        if known > 0:
            return NearbyCategorySummary(
                category=category,
                status=InfrastructureDataStatus.NO_VERIFIED_RECORDS,
                count=0,
                places=[],
                note=(
                    f"No verified {_label(category).lower()} within {int(radius)} m "
                    "(verified records exist in the registry; none are in range)."
                ),
            )

        # No registry coverage for the category at all → live real fallback.
        # (The geo service's own _fetch_overpass honours GIS_OVERPASS_ENABLED and
        # the mirror/retry budget; here we simply delegate.)
        geo = geo_service or GeoService(settings=self._settings)
        raw_places, ok, _source, _cached = await geo._fetch_overpass(
            latitude, longitude, radius, category, limit, client
        )
        if not ok:
            return NearbyCategorySummary(
                category=category,
                status=InfrastructureDataStatus.DATA_UNAVAILABLE,
                count=0,
                places=[],
                note=(
                    "No verified registry coverage and the live lookup could not be "
                    "performed — nothing is claimed about this area right now."
                ),
            )
        return NearbyCategorySummary(
            category=category,
            status=InfrastructureDataStatus.PENDING_VERIFICATION,
            count=len(raw_places),
            places=[_nearby_place_from_geo(p, category) for p in raw_places],
            note=(
                "Live OpenStreetMap candidates (not yet verified): real nearby "
                "facilities indexed from the live source while the registry "
                "covers this category."
            ),
        )

    async def find_nearby(
        self,
        db: AsyncSession,
        *,
        latitude: float,
        longitude: float,
        radius_m: float | None = None,
        categories: list[CriticalLocationCategory] | None = None,
        limit: int = 20,
        client: httpx.AsyncClient | None = None,
        use_cache: bool = True,
        geo_service: GeoService | None = None,
    ) -> tuple[NearbyInfrastructureOut, bool]:
        """Data-quality-aware nearby infrastructure answer for a coordinate."""
        geosvc = GeoService(settings=self._settings)
        geosvc.validate_coordinates(latitude, longitude)
        radius = float(
            radius_m if radius_m is not None else self._settings.INFRASTRUCTURE_SEARCH_RADIUS_METERS
        )
        cats = categories or list(_NEARBY_CATEGORIES)

        cache_key = self._cache_key(latitude, longitude, radius, cats)
        if use_cache:
            cached, hit = await self._query_cache(cache_key)
            if hit and isinstance(cached, dict):
                try:
                    return NearbyInfrastructureOut(**cached), True
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Registry cache payload invalid (%s): %s", cache_key, exc)

        registry_has = await self._registry_counts(db, cats)
        summaries: list[NearbyCategorySummary] = []
        live_used = False
        for category in cats:
            summary = await self.resolve_category(
                db,
                latitude=latitude,
                longitude=longitude,
                radius_m=radius,
                category=category,
                limit=limit,
                client=client,
                registry_has=registry_has,
                geo_service=geo_service,
            )
            if summary.status == InfrastructureDataStatus.PENDING_VERIFICATION:
                live_used = True
            summaries.append(summary)

        states = {s.status for s in summaries}
        if InfrastructureDataStatus.DATA_UNAVAILABLE in states:
            search_status = "degraded"
        elif InfrastructureDataStatus.PENDING_VERIFICATION in states:
            search_status = "partial"
        else:
            search_status = "resolved"

        out = NearbyInfrastructureOut(
            latitude=latitude,
            longitude=longitude,
            radius_m=radius,
            categories=summaries,
            search_status=search_status,
            registry_total=sum(registry_has.values()),
            registry_categories={cat.value: count for cat, count in registry_has.items() if count},
            live_fallback_used=live_used,
            query_id=uuid.uuid4().hex[:12],
            cached=False,
            resolved_at=datetime.now(UTC),
        )
        if use_cache:
            await self._store_cache(cache_key, out.model_dump(mode="json"))
        return out, False

    # ------------------------------------------------------------------ #
    # Registry administration
    # ------------------------------------------------------------------ #
    async def registry_summary(self, db: AsyncSession) -> RegistrySummaryOut:
        total = int(await db.scalar(select(func.count(CriticalLocation.id))) or 0)
        by_source_rows = (
            await db.execute(
                select(CriticalLocation.source, func.count(CriticalLocation.id)).group_by(
                    CriticalLocation.source
                )
            )
        ).all()
        by_status_rows = (
            await db.execute(
                select(
                    CriticalLocation.verification_status, func.count(CriticalLocation.id)
                ).group_by(CriticalLocation.verification_status)
            )
        ).all()
        by_category_rows = (
            await db.execute(
                select(CriticalLocation.category, func.count(CriticalLocation.id)).group_by(
                    CriticalLocation.category
                )
            )
        ).all()
        unlocated = int(
            await db.scalar(
                select(func.count(CriticalLocation.id)).where(
                    CriticalLocation.latitude.is_(None),
                    CriticalLocation.longitude.is_(None),
                )
            )
            or 0
        )
        verified = int(
            await db.scalar(
                select(func.count(CriticalLocation.id)).where(
                    CriticalLocation.verification_status == _VERIFIED
                )
            )
            or 0
        )
        pending = int(
            await db.scalar(
                select(func.count(CriticalLocation.id)).where(
                    CriticalLocation.verification_status
                    == InfrastructureDataStatus.PENDING_VERIFICATION
                )
            )
            or 0
        )
        last = await db.scalar(select(func.max(CriticalLocation.last_verified_at)))
        return RegistrySummaryOut(
            total=total,
            verified=verified,
            pending=pending,
            unlocated=unlocated,
            by_category={
                (r[0].value if hasattr(r[0], "value") else str(r[0])): int(r[1])
                for r in by_category_rows
            },
            by_status={
                (r[0].value if hasattr(r[0], "value") else str(r[0])): int(r[1])
                for r in by_status_rows
            },
            by_source={
                (str(r[0]) if r[0] is not None else "legacy"): int(r[1]) for r in by_source_rows
            },
            last_verified_at=last,
        )

    async def list_registry(
        self,
        db: AsyncSession,
        *,
        category: CriticalLocationCategory | None = None,
        verification_status: InfrastructureDataStatus | None = None,
        source: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> RegistryListOut:
        stmt = (
            select(CriticalLocation)
            .options(selectinload(CriticalLocation.ward))
            .order_by(
                CriticalLocation.last_verified_at.desc().nulls_last(),
                CriticalLocation.name.asc(),
            )
        )
        if category is not None:
            stmt = stmt.where(CriticalLocation.category == category)
        if verification_status is not None:
            stmt = stmt.where(CriticalLocation.verification_status == verification_status)
        if source:
            stmt = stmt.where(CriticalLocation.source == source)
        total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = (await db.execute(stmt.limit(int(limit)).offset(int(offset)))).scalars().all()
        items = [_registry_asset_out(r) for r in rows]
        return RegistryListOut(items=items, total=total, limit=int(limit), offset=int(offset))

    # ------------------------------------------------------------------ #
    # Redis cache (only genuine resolved answers are cached; failures never)
    # ------------------------------------------------------------------ #
    def _cache_namespace(self) -> str:
        return self._settings.CONTEXT_CACHE_NAMESPACE.rstrip(":")

    def _cache_key(
        self,
        latitude: float,
        longitude: float,
        radius_m: float,
        categories: list[CriticalLocationCategory],
    ) -> str:
        bucket = ",".join(c.value for c in categories)
        return (
            f"{self._cache_namespace()}:nearby-registry:"
            f"{bucket}:{latitude:.5f},{longitude:.5f}:{int(radius_m)}"
        )

    async def _query_cache(self, key: str) -> tuple[Any | None, bool]:
        if not self._settings.GIS_CACHE_ENABLED:
            return None, False
        try:
            client = await get_redis()
            raw = await client.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Registry cache GET failed (%s): %s", key, exc)
            return None, False
        if raw is None:
            return None, False
        try:
            return json.loads(raw), True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Registry cache payload unreadable (%s): %s", key, exc)
            return None, False

    async def _store_cache(self, key: str, payload: Any) -> None:
        if not self._settings.GIS_CACHE_ENABLED or payload is None:
            return
        try:
            client = await get_redis()
            await client.set(
                key,
                json.dumps(payload),
                ex=int(self._settings.INFRASTRUCTURE_CACHE_TTL_SECONDS),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Registry cache SET failed (%s): %s", key, exc)


# --------------------------------------------------------------------------- #
# Module helpers
# --------------------------------------------------------------------------- #
def _label(category: CriticalLocationCategory) -> str:
    return {
        CriticalLocationCategory.HOSPITAL: "Hospital",
        CriticalLocationCategory.SCHOOL: "School",
        CriticalLocationCategory.BUS_STOP: "Bus stop",
        CriticalLocationCategory.POLICE_STATION: "Police station",
        CriticalLocationCategory.FIRE_STATION: "Fire station",
        CriticalLocationCategory.TRANSPORT: "Transit",
        CriticalLocationCategory.PUBLIC_FACILITY: "Public facility",
        CriticalLocationCategory.GOVERNMENT_BUILDING: "Government building",
        CriticalLocationCategory.ROAD: "Major road",
        CriticalLocationCategory.OTHER: "Facility",
    }.get(category, "Facility")


def _fallback_name(category: CriticalLocationCategory) -> str:
    return {
        CriticalLocationCategory.HOSPITAL: "Hospital",
        CriticalLocationCategory.SCHOOL: "School",
        CriticalLocationCategory.BUS_STOP: "Bus stop",
        CriticalLocationCategory.POLICE_STATION: "Police station",
        CriticalLocationCategory.FIRE_STATION: "Fire station",
        CriticalLocationCategory.TRANSPORT: "Transit",
        CriticalLocationCategory.PUBLIC_FACILITY: "Public facility",
        CriticalLocationCategory.GOVERNMENT_BUILDING: "Government building",
        CriticalLocationCategory.ROAD: "Major road",
    }.get(category, "Facility")


def _kind_from_tags(tags: dict[str, str], category: CriticalLocationCategory) -> str | None:
    for key in ("amenity", "healthcare", "office", "highway", "railway", "public_transport"):
        value = tags.get(key)
        if value:
            return f"{key}={value}"
    return category.value.lower()


def _to_nearby_place(row: CriticalLocation, latitude: float, longitude: float) -> NearbyPlace:
    distance = None
    if row.latitude is not None and row.longitude is not None:
        distance = GeoService.calculate_distance(latitude, longitude, row.latitude, row.longitude)
    metadata = row.asset_metadata or {}
    return NearbyPlace(
        id=str(row.id),
        name=row.name,
        category=row.category,
        address=row.address,
        latitude=row.latitude,
        longitude=row.longitude,
        distance_m=round(distance, 1) if distance is not None else None,
        verification_status=row.verification_status,
        source=row.source,
        source_dataset=row.source_dataset,
        kind=metadata.get("kind"),
        is_demo=row.is_demo,
    )


def _nearby_place_from_geo(place: GeoPlace, category: CriticalLocationCategory) -> NearbyPlace:
    return NearbyPlace(
        id=None,
        name=place.name,
        category=category,
        address=place.address,
        latitude=place.latitude,
        longitude=place.longitude,
        distance_m=round(place.distance_m, 1) if place.distance_m is not None else None,
        verification_status=InfrastructureDataStatus.PENDING_VERIFICATION,
        source="openstreetmap",
        source_dataset=_OSM_DATASET,
        is_demo=False,
    )


def _registry_asset_out(row: CriticalLocation) -> RegistryAssetOut:
    ward = row.ward
    return RegistryAssetOut(
        id=str(row.id),
        name=row.name,
        category=row.category,
        address=row.address,
        latitude=row.latitude,
        longitude=row.longitude,
        source=row.source,
        source_dataset=row.source_dataset,
        source_url=row.source_url,
        source_id=row.source_id,
        verification_status=row.verification_status,
        last_verified_at=row.last_verified_at,
        ward_id=str(row.ward_id) if row.ward_id else None,
        ward_code=ward.code if ward else None,
        ward_name=ward.name if ward else None,
        is_demo=row.is_demo,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _category_from_input(value: Any) -> CriticalLocationCategory:
    s = str(value or "OTHER").strip().upper().replace(" ", "_")
    if s in CriticalLocationCategory.__members__:
        return CriticalLocationCategory(s)
    return CriticalLocationCategory.OTHER


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_infrastructure_registry(settings: Settings | None = None) -> InfrastructureRegistry:
    return InfrastructureRegistry(settings=settings or get_settings())
