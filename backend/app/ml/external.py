"""External feature providers for the hotspot pipeline (Part 23, Part 36).

The model mixes *complaint-history* features (always available: trailing counts,
category mix, seasonality, location) with *context* features that may or may not
be available depending on the environment:

* **Rain** — the demo city has no historical weather store. Training reports it
  unavailable (0.0). Live inference can optionally fetch the current
  Open-Meteo precipitation for the city, but the safe default reports the value
  as *unavailable* (0.0).
* **Population** — training and live inference use ward-level resident counts as
  a city proxy, when wards exist.
* **Infrastructure age** — always reported unavailable for the hotspot pipeline.

Every provider is a ``Callable[[str, datetime], ExternalFeatures]`` returning a
tiny, bounded, always-serializable dataclass so the feature extractor treats
training and live providers identically. Values are scaled to 0..1-ish units so
the model never depends on raw magnitudes. Nothing here fabricates complaint
locations: cells and coordinates come only from real complaint records.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExternalFeatures:
    """Bounded external context for one cell at one reference date."""

    # Normalized rainfall (mm/day, log1p-scaled).
    rainfall_mm: float = 0.0
    rainfall_available: bool = False
    # Person-density proxy, normalized to ~0..1.
    population_density: float = 0.0
    population_available: bool = False
    # Infrastructure age in years, normalized to ~0..1.
    infra_age: float = 0.0
    infra_available: bool = False


ContextProvider = Callable[[str, datetime], ExternalFeatures]


def _log1p_x(v: float) -> float:
    import math

    return math.log1p(max(0.0, v))


def _bbox_corners(settings: Settings) -> tuple[float, float, float, float]:
    min_lat, min_lon, max_lat, max_lon = [float(p) for p in settings.HOTSPOT_BBOX.split(",")]
    return min_lat, min_lon, max_lat, max_lon


# --------------------------------------------------------------------------- #
# Live providers (degrade gracefully; never raise)
# --------------------------------------------------------------------------- #
class LiveContextProvider:
    """Provider factory bound to live lookup values supplied by the service layer.

    ``population_per_cell`` maps cell_id -> ward resident density; ``rain_mm``
    is a citywide current precipitation value (or None = unavailable).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        population_per_cell: dict[str, float] | None = None,
        rain_mm: float | None = None,
        rain_available: bool = False,
    ) -> None:
        self._settings = settings
        self._population = population_per_cell or {}
        self._rain_mm = rain_mm
        self._rain_available = rain_available

    def provider(self) -> ContextProvider:
        def _provide(cell_id: str, ref: datetime) -> ExternalFeatures:
            pop = self._population.get(cell_id, 0.0)
            pop_norm = min(1.0, pop / 5000.0) if pop > 0 else 0.0
            rain = self._rain_mm if self._rain_mm is not None else 0.0
            return ExternalFeatures(
                rainfall_mm=round(_log1p_x(rain), 4),
                rainfall_available=self._rain_available,
                population_density=round(pop_norm, 4),
                population_available=bool(pop_norm > 0),
                infra_age=0.0,
                infra_available=False,
            )

        return _provide


async def fetch_citywide_rainfall(settings: Settings) -> tuple[float | None, bool]:
    """Best-effort current precipitation (mm) for the demo city via Open-Meteo.

    Offline by default (``HOTSPOT_RAINFALL_FETCH`` False). When enabled the
    result is cached like the weather-context calls; on any failure the value is
    reported unavailable rather than raising. This is the **only** rainwater
    source that ever touches the network at inference time.
    """
    if not settings.HOTSPOT_RAINFALL_FETCH:
        return None, False
    key = f"{settings.CONTEXT_CACHE_NAMESPACE}:hotspots:rain"
    cache_val, hit = await cache_get_json(settings, key)
    if hit and cache_val is not None:
        return float(cache_val["precipitation"]), True
    try:
        import httpx

        min_lat, min_lon, max_lat, _ = _bbox_corners(settings)
        center_lat = (min_lat + max_lat) / 2
        resp = httpx.get(
            settings.WEATHER_BASE_URL,
            params={
                "latitude": center_lat,
                "longitude": min_lon,
                "current": "precipitation",
            },
            timeout=settings.WEATHER_TIMEOUT_SECONDS,
            headers={"User-Agent": "CivicAgent/0.1 (predictive-hotspots)"},
        )
        resp.raise_for_status()
        value = float(resp.json()["current"]["precipitation"])
        await cache_set_json(
            settings, key, {"precipitation": value}, settings.WEATHER_CACHE_TTL_SECONDS
        )
        return value, True
    except Exception as exc:  # noqa: BLE001 - provider must degrade, never break
        logger.warning("Rainfall provider unavailable (degrading to 0): %s", exc)
        return None, False


async def fetch_infra_citywide_rainfall(settings: Settings) -> tuple[float | None, bool]:
    """Current citywide precipitation for the infrastructure pipeline (Part 24).

    Identical semantics to ``fetch_citywide_rainfall`` but gated by
    ``INFRA_RAINFALL_FETCH`` and cached under its own key so the two pipelines
    never share state.
    """
    if not settings.INFRA_RAINFALL_FETCH:
        return None, False
    key = f"{settings.CONTEXT_CACHE_NAMESPACE}:infra:rain"
    cache_val, hit = await cache_get_json(settings, key)
    if hit and cache_val is not None:
        return float(cache_val["precipitation"]), True
    try:
        import httpx

        min_lat, min_lon, max_lat, _ = _bbox_corners(settings)
        center_lat = (min_lat + max_lat) / 2
        resp = httpx.get(
            settings.WEATHER_BASE_URL,
            params={
                "latitude": center_lat,
                "longitude": min_lon,
                "current": "precipitation",
            },
            timeout=settings.WEATHER_TIMEOUT_SECONDS,
            headers={"User-Agent": "CivicAgent/0.1 (predictive-infrastructure)"},
        )
        resp.raise_for_status()
        value = float(resp.json()["current"]["precipitation"])
        await cache_set_json(
            settings, key, {"precipitation": value}, settings.WEATHER_CACHE_TTL_SECONDS
        )
        return value, True
    except Exception as exc:  # noqa: BLE001 - provider must degrade, never break
        logger.warning("Infra rainfall provider unavailable (degrading to 0): %s", exc)
        return None, False


def now_utc() -> datetime:
    return datetime.now(UTC)
