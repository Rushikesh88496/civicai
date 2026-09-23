"""Open-Meteo weather fetch, shared by the Context Agent (Part 11) and the
Priority Engine's weather collector (Part 12).

Real forecast data, cached in Redis with a TTL. A cache hit skips the upstream
call and marks ``cached=True``; a miss fetches live then stores; when Redis is
unreachable (or caching is disabled) the call degrades to a live Open-Meteo
call. Any upstream failure returns ``WeatherContext(available=False)`` — the
caller reports ``DATA_UNAVAILABLE`` instead of inventing a condition.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.cache import cache_get_json, cache_key, cache_set_json
from app.core.config import Settings
from app.schemas.context import ContextSource, WeatherContext, WeatherForecastDay

logger = logging.getLogger(__name__)

# Open-Meteo returns JSON arrays in the same order as the requested variables.
_CURRENT_FIELDS = [
    "temperature_2m",
    "precipitation",
    "rain",
    "weather_code",
    "wind_speed_10m",
    "precipitation_probability",
]
_DAILY_FIELDS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
]

# Rough WMO weather-code -> human label (subset adequate for the UI card).
_WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Light rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


async def fetch_weather(
    *,
    settings: Settings,
    latitude: float,
    longitude: float,
    client: httpx.AsyncClient | None = None,
) -> tuple[WeatherContext, ContextSource | None]:
    """Fetch current + short forecast weather for a coordinate.

    Chained fallback, newest first:
    1. Redis cache hit (``cached=True``) — TTL enforced by Redis.
    2. Live Open-Meteo call — stored into Redis for future hits.
    3. Open-Meteo unreachable/garbage -> ``available=False``, graceful.
    """
    retrieved = datetime.now(UTC)
    past_days = max(0, int(settings.WEATHER_PAST_DAYS))
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join(_CURRENT_FIELDS),
        "daily": ",".join(_DAILY_FIELDS),
        "forecast_days": settings.WEATHER_FORECAST_DAYS,
        "timezone": "auto",
    }
    if past_days > 0:
        params["past_days"] = past_days
    key = cache_key(settings, "weather", f"{latitude:.5f},{longitude:.5f}")

    # 1) Cache hit.
    cached_payload, is_hit = await cache_get_json(settings, key)
    if is_hit and isinstance(cached_payload, dict) and cached_payload.get("_payload"):
        return (
            _parse_weather_payload(cached_payload["_payload"], cached=True, past_days=past_days),
            None,
        )

    # 2) Live call, retried up to the configured budget.
    retries = max(0, int(settings.WEATHER_MAX_RETRIES))
    try:
        url = f"{settings.WEATHER_BASE_URL.rstrip('/')}"
        timeout = settings.WEATHER_TIMEOUT_SECONDS

        async def _get() -> dict[str, Any]:
            if client is None:
                async with httpx.AsyncClient(timeout=timeout) as ac:
                    resp = await ac.get(url, params=params)
            else:
                resp = await client.get(url, params=params)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Open-Meteo HTTP {resp.status_code} for {params.get('latitude')},"
                    f"{params.get('longitude')}"
                )
            return resp.json()

        payload: dict[str, Any] = {}
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                payload = await _get()
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 - retried, then degrades
                last_exc = exc
                if attempt == retries:
                    break
                await asyncio.sleep(min(4.0, 0.5 * (2**attempt)))
        if last_exc is not None:
            raise last_exc

        weather = _parse_weather_payload(payload, cached=False, past_days=past_days)
        if weather.available:
            await cache_set_json(
                settings,
                key,
                {"_payload": payload, "_retrieved_at": retrieved.isoformat()},
                int(settings.WEATHER_CACHE_TTL_SECONDS),
            )
        source = ContextSource(
            name="open-meteo",
            source_type="http",
            retrieved_at=retrieved,
            params=_coerce_params(params),
        )
        return weather, source
    except Exception as exc:  # noqa: BLE001 - weather failure never fails scoring
        logger.warning("Open-Meteo unavailable for (%s, %s): %s", latitude, longitude, exc)
        return WeatherContext(available=False), None


def _parse_weather_payload(
    payload: dict[str, Any], *, cached: bool, past_days: int = 0
) -> WeatherContext:
    """Map an Open-Meteo JSON payload onto a ``WeatherContext``."""
    current = payload.get("current", {}) or {}
    daily = payload.get("daily", {}) or {}
    values = {k: current.get(k) for k in _CURRENT_FIELDS}
    temperature = _num(values.get("temperature_2m"))
    precipitation = _num(values.get("precipitation"))
    rain = _num(values.get("rain"))
    wind = _num(values.get("wind_speed_10m"))
    prob_current = _num(values.get("precipitation_probability"))
    wcode = values.get("weather_code")
    code = int(wcode) if isinstance(wcode, (int, float)) else None

    dates = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    psum = daily.get("precipitation_sum") or []
    pprob = daily.get("precipitation_probability_max") or []

    # With past_days=N the first N daily rows are the trailing past-days window
    # (ordered most-recent past day first); today + forecast follow.
    past_len = int(past_days)
    recent_sum = 0.0
    recent_rows = dates[:past_len] if past_len > 0 else []
    for i in range(len(recent_rows)):
        value = _num(psum[i]) if i < len(psum) else None
        if value is not None:
            recent_sum += max(0.0, value)

    forecast: list[WeatherForecastDay] = []
    for i, d in enumerate(dates):
        if i < past_len:
            # Past-day rows are not part of the forecast the UI shows today.
            continue
        forecast.append(
            WeatherForecastDay(
                date=str(d),
                temperature_max=_num(tmax[i]) if i < len(tmax) else None,
                temperature_min=_num(tmin[i]) if i < len(tmin) else None,
                precipitation_sum=_num(psum[i]) if i < len(psum) else None,
            )
        )

    forecast_prob_values = [
        value
        for i in range(past_len, len(dates))
        if i < len(pprob)
        for value in [_num(pprob[i])]
        if value is not None
    ]
    forecast_prob_max = max(forecast_prob_values) if forecast_prob_values else None

    provided = any(
        v is not None
        for v in (temperature, precipitation, rain, wind, code, prob_current)
    )
    return WeatherContext(
        temperature_c=temperature,
        precipitation_mm=precipitation,
        rain_mm=rain,
        wind_speed_kmh=wind,
        weather_code=code,
        condition=_WMO_CODES.get(code) if code is not None else None,
        precipitation_probability_pct=prob_current,
        forecast_precipitation_probability_max_pct=forecast_prob_max,
        recent_precipitation_sum_mm=recent_sum if recent_rows else None,
        cached=cached,
        retrieved_at=datetime.now(UTC),
        available=provided,
        forecast=forecast,
    )


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_params(params: dict[str, object]) -> dict[str, object]:
    """Ensure params are JSON-serializable for the provenance record."""
    return {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in params.items()}
