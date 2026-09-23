"""Real-data collectors for the Priority Engine (Part 12, rebuilt).

``PriorityDataService.collect`` gathers every input the deterministic engine
scores against, straight from the live system — PostGIS infrastructure registry
(with per-facility metre distances), Open-Meteo weather (current + forecast),
real complaint counts (affected population & report pressure, recurrence), the
complaint's evidence signals, and its stored severity. Nothing is fabricated:
when a signal cannot be resolved, its component is marked ``DATA_UNAVAILABLE`` /
``INSUFFICIENT_DATA`` (never a guessed number) and the engine reports it
honestly. Confirmed duplicates are excluded from every count so the same
incident is never double-counted.

This replaces the legacy flow in which the Priority Agent only re-read a prior
``agent="context"`` run (which could be stale or missing entirely) — the score
now always reflects the current situation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from geoalchemy2 import Geography
from geoalchemy2.functions import ST_DWithin, ST_MakePoint, ST_SetSRID
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import AgentRun, Complaint, ComplaintLocation, ComplaintMedia
from app.models.enums import ComplaintCategory, ComplaintStatus, CorrelationMatchStatus
from app.services import weather_service
from app.services.infrastructure_registry import InfrastructureRegistry
from app.services.priority_engine import (
    EvidenceInput,
    FacilityInput,
    HistoricalInput,
    InfrastructureInput,
    PopulationInput,
    PriorityDataBundle,
    SeverityInput,
    WeatherInput,
)

logger = logging.getLogger(__name__)

# Radius keys used by the affected-population component (250/500/1000 m).
_DENSITY_RADII = (250.0, 500.0, 1000.0)

# Complaint statuses that mean the issue is genuinely closed (not "unresolved").
_RESOLVED_STATUSES = frozenset(
    {
        ComplaintStatus.RESOLVED.value,
        ComplaintStatus.CLOSED.value,
        ComplaintStatus.CITIZEN_VERIFIED.value,
    }
)

# Sensitive categories that raise the population component when adjacent.
_SENSITIVE_CATEGORIES = frozenset(
    {"SCHOOL", "HOSPITAL", "FIRE_STATION", "POLICE_STATION", "TRANSPORT", "BUS_STOP"}
)


def _resolved_enum() -> list[ComplaintStatus]:
    return [ComplaintStatus(s) for s in _RESOLVED_STATUSES]


class PriorityDataService:
    """Collects the real context inputs used to score one complaint."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        registry: InfrastructureRegistry | None = None,
        weather_client=None,
    ) -> None:
        self._settings = settings or get_settings()
        self._registry = registry
        self._weather_client = weather_client

    async def collect(self, db: AsyncSession, complaint: Complaint) -> PriorityDataBundle:
        """Gather all real inputs for a single scoring pass."""
        settings = self._settings
        now = datetime.now(UTC)
        ward_id = complaint.ward_id
        location = complaint.complaint_location
        latitude = location.latitude if location else None
        longitude = location.longitude if location else None

        category = (complaint.category.value if complaint.category else "OTHER") or "OTHER"

        severity = SeverityInput(
            severity=complaint.priority.value if complaint.priority else "LOW",
            calculated_at=now,
        )

        excluded_ids = await self._confirmed_duplicate_ids(db, complaint.id)

        infrastructure = await self._collect_infrastructure(
            db, settings, latitude, longitude, now
        )
        weather = await self._collect_weather(settings, latitude, longitude, now)
        historical = await self._collect_historical(
            db,
            settings,
            complaint_id=complaint.id,
            category=category,
            ward_id=ward_id,
            latitude=latitude,
            longitude=longitude,
            excluded_ids=excluded_ids,
            now=now,
        )
        population = await self._collect_population(
            db,
            settings,
            complaint_id=complaint.id,
            ward_id=ward_id,
            latitude=latitude,
            longitude=longitude,
            excluded_ids=excluded_ids,
            infrastructure_facilities=infrastructure.facilities if infrastructure else [],
            now=now,
        )
        evidence = await self._collect_evidence(
            db,
            complaint=complaint,
            category=category,
            nearby_30d=historical.nearby_30d if historical else 0,
            now=now,
        )

        return PriorityDataBundle(
            category=category,
            severity=severity,
            infrastructure=infrastructure,
            weather=weather,
            historical=historical,
            population=population,
            evidence=evidence,
        )

    async def _confirmed_duplicate_ids(
        self, db: AsyncSession, complaint_id: uuid.UUID
    ) -> set[uuid.UUID]:
        """Ids of complaints CONFIRMED as duplicates of ``complaint_id``."""
        return await self._confirmed_pairs(db, complaint_id)

    async def _confirmed_pairs(self, db: AsyncSession, complaint_id: uuid.UUID) -> set[uuid.UUID]:
        from app.models import ComplaintCorrelation

        cols = (
            ComplaintCorrelation.source_complaint_id,
            ComplaintCorrelation.target_complaint_id,
        )
        rows = (
            (
                await db.execute(
                    select(*cols)
                    .where(
                        ComplaintCorrelation.status == CorrelationMatchStatus.CONFIRMED,
                        ComplaintCorrelation.source_complaint_id == complaint_id,
                    )
                )
            )
            .all()
        )
        rows2 = (
            (
                await db.execute(
                    select(*cols)
                    .where(
                        ComplaintCorrelation.status == CorrelationMatchStatus.CONFIRMED,
                        ComplaintCorrelation.target_complaint_id == complaint_id,
                    )
                )
            )
            .all()
        )
        excluded: set[uuid.UUID] = set()
        for src, tgt in [*rows, *rows2]:
            excluded.add(tgt if src == complaint_id else src)
        return excluded

    async def _collect_infrastructure(
        self,
        db: AsyncSession,
        settings: Settings,
        latitude: float | None,
        longitude: float | None,
        now: datetime,
    ) -> InfrastructureInput | None:
        radius = float(settings.INFRASTRUCTURE_SEARCH_RADIUS_METERS)
        if latitude is None or longitude is None:
            return InfrastructureInput(
                status="DATA_UNAVAILABLE",
                radius_m=radius,
                calculated_at=now,
                explanation="Complaint has no coordinates; nearby lookup skipped.",
            )
        try:
            if self._registry is None:
                self._registry = InfrastructureRegistry(settings=settings)
            out, _cached = await self._registry.find_nearby(
                db, latitude=latitude, longitude=longitude, radius_m=radius
            )
        except Exception as exc:  # noqa: BLE001 - degrade, never fail scoring
            logger.warning(
                "Infrastructure collection failed for (%s, %s): %s", latitude, longitude, exc
            )
            return InfrastructureInput(
                status="DATA_UNAVAILABLE",
                radius_m=radius,
                calculated_at=now,
                explanation="Nearby-infrastructure lookup could not be performed.",
            )

        facilities: list[FacilityInput] = []
        statuses: set[str] = set()
        for summary in out.categories:
            cat_value = summary.category.value if hasattr(summary.category, "value") else str(
                summary.category
            )
            statuses.add(summary.status.value)
            for place in summary.places:
                facilities.append(
                    FacilityInput(
                        name=place.name,
                        category=cat_value,
                        distance_m=place.distance_m,
                        verification=place.verification_status.value,
                        record_id=place.id,
                    )
                )
        facilities.sort(key=lambda f: (f.distance_m if f.distance_m is not None else float("inf")))

        found = "FOUND" in statuses
        pending = "PENDING_VERIFICATION" in statuses
        unavailable = "DATA_UNAVAILABLE" in statuses
        if found:
            status = "FOUND"
        elif pending:
            status = "PARTIAL_DATA"
        elif unavailable:
            status = "DATA_UNAVAILABLE"
        else:
            status = "NO_VERIFIED_RECORDS"

        return InfrastructureInput(
            facilities=facilities,
            status=status,
            radius_m=float(out.radius_m),
            calculated_at=now,
            explanation=(
                f"Registry/OSM lookup within {float(out.radius_m):.0f} m "
                f"({', '.join(sorted(statuses))})."
            ),
        )

    async def _collect_weather(
        self,
        settings: Settings,
        latitude: float | None,
        longitude: float | None,
        now: datetime,
    ) -> WeatherInput | None:
        if latitude is None or longitude is None:
            return WeatherInput(
                status="DATA_UNAVAILABLE",
                calculated_at=now,
                explanation="Complaint has no coordinates; weather lookup skipped.",
            )
        weather, _source = await weather_service.fetch_weather(
            settings=settings,
            latitude=latitude,
            longitude=longitude,
            client=self._weather_client,
        )
        if not weather.available:
            return WeatherInput(
                status="DATA_UNAVAILABLE",
                calculated_at=now,
                explanation="Open-Meteo unavailable; nothing claimed about the weather.",
            )
        forecast_precip = (
            max(
                (
                    float(d.precipitation_sum)
                    for d in (weather.forecast or [])
                    if d.precipitation_sum is not None
                ),
                default=None,
            )
            if weather.forecast
            else None
        )
        return WeatherInput(
            condition=weather.condition,
            rain_mm=weather.rain_mm,
            precipitation_mm=weather.precipitation_mm,
            forecast_precip_mm=forecast_precip,
            recent_precip_mm=weather.recent_precipitation_sum_mm,
            precip_probability_pct=weather.forecast_precipitation_probability_max_pct,
            threshold_mm=float(settings.PRIORITY_WEATHER_RAIN_MM),
            status="AVAILABLE",
            calculated_at=now,
            explanation=(
                "Real Open-Meteo current + recent + next-days forecast conditions."
            ),
        )

    async def _collect_historical(
        self,
        db: AsyncSession,
        settings: Settings,
        *,
        complaint_id: uuid.UUID,
        category: str,
        ward_id: uuid.UUID | None,
        latitude: float | None,
        longitude: float | None,
        excluded_ids: set[uuid.UUID],
        now: datetime,
    ) -> HistoricalInput:
        window_7d = now - timedelta(hours=float(settings.PRIORITY_HISTORICAL_WINDOW_HOURS))
        window_30d = now - timedelta(hours=float(settings.PRIORITY_HISTORICAL_WINDOW_30D_HOURS))
        radius = float(settings.PRIORITY_REPORT_RADIUS_M)

        async def _ward_count(since: datetime, same_category_only: bool = False) -> int:
            if ward_id is None:
                return 0
            stmt = select(func.count(Complaint.id)).where(
                Complaint.ward_id == ward_id,
                Complaint.id != complaint_id,
                Complaint.created_at >= since,
            )
            if same_category_only:
                stmt = stmt.where(Complaint.category == ComplaintCategory(category))
            return int(await db.scalar(stmt) or 0)

        async def _nearby_count(
            since: datetime,
            radius_m: float,
            same_category_only: bool = False,
            unresolved_only: bool = False,
        ) -> int:
            if latitude is None or longitude is None:
                return 0
            point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
            gh = Geography(geometry_type="POINT", srid=4326)
            stmt = (
                select(func.count(Complaint.id))
                .join(ComplaintLocation, ComplaintLocation.complaint_id == Complaint.id)
                .where(
                    ST_DWithin(ComplaintLocation.geom.cast(gh), point.cast(gh), radius_m),
                    Complaint.id != complaint_id,
                    Complaint.created_at >= since,
                )
            )
            if same_category_only:
                stmt = stmt.where(Complaint.category == ComplaintCategory(category))
            if unresolved_only:
                stmt = stmt.where(~Complaint.status.in_(_resolved_enum()))
            if excluded_ids:
                stmt = stmt.where(Complaint.id.not_in(excluded_ids))
            return int((await db.execute(stmt)).scalar() or 0)

        proximity_known = latitude is not None and longitude is not None
        if ward_id is None and not proximity_known:
            return HistoricalInput(
                status="INSUFFICIENT_DATA",
                calculated_at=now,
                explanation="No ward and no coordinates — historical signal unavailable.",
            )

        return HistoricalInput(
            same_category_nearby_7d=await _nearby_count(
                window_7d, radius, same_category_only=True
            ),
            same_category_nearby_30d=await _nearby_count(
                window_30d, radius, same_category_only=True
            ),
            nearby_7d=await _nearby_count(window_7d, radius),
            nearby_30d=await _nearby_count(window_30d, radius),
            cluster_250m_30d=await _nearby_count(window_30d, 250.0),
            ward_30d=await _ward_count(window_30d),
            unresolved_similar_nearby=await _nearby_count(
                window_30d, radius, same_category_only=True, unresolved_only=True
            ),
            duplicates_excluded=len(excluded_ids),
            status="AVAILABLE",
            calculated_at=now,
        )

    async def _collect_population(
        self,
        db: AsyncSession,
        settings: Settings,
        *,
        complaint_id: uuid.UUID,
        ward_id: uuid.UUID | None,
        latitude: float | None,
        longitude: float | None,
        excluded_ids: set[uuid.UUID],
        infrastructure_facilities: list[FacilityInput],
        now: datetime,
    ) -> PopulationInput:
        window_7d = now - timedelta(hours=float(settings.PRIORITY_REPORT_WINDOW_HOURS))
        window_30d = now - timedelta(hours=float(settings.PRIORITY_HISTORICAL_WINDOW_30D_HOURS))
        radii = tuple(
            float(r) for r in settings.PRIORITY_DENSITY_RADII_M or _DENSITY_RADII
        )

        proximity_known = latitude is not None and longitude is not None
        if not proximity_known:
            return PopulationInput(
                status="INSUFFICIENT_DATA",
                population_status="DATA_UNAVAILABLE",
                calculated_at=now,
                explanation="No coordinates — report pressure unavailable.",
            )

        point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
        gh = Geography(geometry_type="POINT", srid=4326)

        async def _count(radius_m: float, since: datetime, unresolved_only: bool = False) -> int:
            stmt = (
                select(func.count(Complaint.id))
                .join(ComplaintLocation, ComplaintLocation.complaint_id == Complaint.id)
                .where(
                    ST_DWithin(ComplaintLocation.geom.cast(gh), point.cast(gh), radius_m),
                    Complaint.id != complaint_id,
                    Complaint.created_at >= since,
                )
            )
            if unresolved_only:
                stmt = stmt.where(~Complaint.status.in_(_resolved_enum()))
            if excluded_ids:
                stmt = stmt.where(Complaint.id.not_in(excluded_ids))
            return int((await db.execute(stmt)).scalar() or 0)

        async def _unique_reporters(radius_m: float, since: datetime) -> int:
            stmt = (
                select(func.count(distinct(Complaint.user_id)))
                .join(ComplaintLocation, ComplaintLocation.complaint_id == Complaint.id)
                .where(
                    ST_DWithin(ComplaintLocation.geom.cast(gh), point.cast(gh), radius_m),
                    Complaint.id != complaint_id,
                    Complaint.created_at >= since,
                )
            )
            if excluded_ids:
                stmt = stmt.where(Complaint.id.not_in(excluded_ids))
            return int(await db.scalar(stmt) or 0)

        reports_7d = {int(r): await _count(r, window_7d) for r in radii}
        reports_30d = {int(r): await _count(r, window_30d) for r in radii}
        unique_7d = await _unique_reporters(1000.0, window_7d)
        unique_30d = await _unique_reporters(1000.0, window_30d)
        unresolved_7d = await _count(1000.0, window_7d, unresolved_only=True)
        unresolved_30d = await _count(1000.0, window_30d, unresolved_only=True)

        spread = await db.scalar(
            select(func.max(func.st_distance(ComplaintLocation.geom.cast(gh), point.cast(gh)))).where(  # noqa: E501
                ComplaintLocation.complaint_id != complaint_id,
                ComplaintLocation.complaint_id.in_(
                    select(Complaint.id).join(
                        ComplaintLocation,
                        ComplaintLocation.complaint_id == Complaint.id,
                    ).where(
                        Complaint.id != complaint_id,
                        Complaint.created_at >= window_30d,
                        ST_DWithin(ComplaintLocation.geom.cast(gh), point.cast(gh), 1000.0),
                    )
                ),
            )
        )
        spread_float = float(spread) if isinstance(spread, (int, float)) else None

        sensitive_band = float(settings.PRIORITY_SENSITIVE_FACILITY_BAND_M)
        sensitive_facilities: list[FacilityInput] = [
            f
            for f in infrastructure_facilities
            if str(f.category).upper() in _SENSITIVE_CATEGORIES
            and f.distance_m is not None
            and f.distance_m <= sensitive_band
        ]
        sensitive = len(sensitive_facilities)

        population_available = bool(settings.PRIORITY_POPULATION_DENSITY_AVAILABLE)
        return PopulationInput(
            reports_7d=reports_7d,
            reports_30d=reports_30d,
            unique_reporters_7d=unique_7d,
            unique_reporters_30d=unique_30d,
            unresolved_reports_7d=unresolved_7d,
            unresolved_reports_30d=unresolved_30d,
            spread_max_distance_m=spread_float,
            sensitive_facilities_nearby=sensitive,
            sensitive_facilities=sensitive_facilities,
            population=None,
            population_status=(
                "AVAILABLE" if population_available else "DATA_UNAVAILABLE"
            ),
            status="AVAILABLE",
            calculated_at=now,
        )

    async def _collect_evidence(
        self,
        db: AsyncSession,
        *,
        complaint: Complaint,
        category: str,
        nearby_30d: int,
        now: datetime,
    ) -> EvidenceInput:
        location = complaint.complaint_location
        has_gps = location is not None and location.latitude is not None

        media_count = int(
            await db.scalar(
                select(func.count(ComplaintMedia.id)).where(
                    ComplaintMedia.complaint_id == complaint.id
                )
            )
            or 0
        )

        latest_triage = await db.scalar(
            select(AgentRun)
            .where(AgentRun.agent == "triage", AgentRun.complaint_id == complaint.id)
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )
        latest_vision = await db.scalar(
            select(AgentRun)
            .where(AgentRun.agent == "vision", AgentRun.complaint_id == complaint.id)
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )

        triage_ok = (
            latest_triage is not None
            and latest_triage.status.value == "SUCCEEDED"
            and latest_triage.structured_result is not None
        )
        vision_ok = (
            latest_vision is not None
            and latest_vision.status.value == "SUCCEEDED"
            and latest_vision.structured_result is not None
        )

        triage_confidence = None
        if triage_ok:
            triage_confidence = float(
                (latest_triage.structured_result or {}).get("confidence") or 0.0
            )
        vision_confidence = None
        vision_mismatch = None
        if vision_ok:
            vision_result = latest_vision.structured_result or {}
            vision_confidence = float(vision_result.get("confidence") or 0.0)
            vision_mismatch = bool(vision_result.get("mismatch_detected") or False)

        structured = (category or "OTHER").upper() != "OTHER"

        # No resolvable evidence at all -> INSUFFICIENT_DATA (never guess).
        if (
            not has_gps
            and (complaint.description or "").strip() == ""
            and media_count == 0
            and not structured
            and not triage_ok
            and not vision_ok
        ):
            return EvidenceInput(
                has_gps=False,
                description_chars=0,
                media_count=0,
                category_structured=structured,
                status="INSUFFICIENT_DATA",
                calculated_at=now,
                explanation="No evidence signal is present on the complaint.",
            )

        status = "PARTIAL" if not (triage_ok or vision_ok) else "AVAILABLE"
        return EvidenceInput(
            has_gps=has_gps,
            gps_source=location.source if location is not None else None,
            gps_accuracy_m=location.accuracy_m if location is not None else None,
            description_chars=len(complaint.description or ""),
            media_count=media_count,
            category_structured=structured,
            triage_available=triage_ok,
            triage_confidence=triage_confidence,
            vision_available=vision_ok,
            vision_confidence=vision_confidence,
            vision_mismatch=vision_mismatch,
            corroborating_reports_30d=nearby_30d,
            status=status,
            calculated_at=now,
        )
