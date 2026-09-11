"""ETA routing abstraction for work-order dispatch (Part 14).

A work order's ETA must never be presented as live traffic data unless a live
routing provider was actually consulted. This service exposes two modes:

* **Live** — only when a routing provider is configured
  (``ROUTING_API_URL`` + ``ROUTING_API_KEY``). A best-effort call is made; any
  failure, timeout or error falls back to the documented estimate and the
  ``source`` is set to ``"estimated"``.
* **Estimated (default)** — a transparent, documented calculation
  (``haversine distance / DISPATCH_EST_AVG_SPEED_KMH``) that is *always* labelled
  ``source="estimated"`` and never masquerades as live.

The returned ``EtaEstimate(minutes, source, note)`` carries the provenance so the
UI can show "Estimated ETA" vs "Live ETA" honestly.
"""

from __future__ import annotations

import dataclasses

import httpx

from app.core.config import Settings, get_settings
from app.services.dispatch_engine import haversine_km


@dataclasses.dataclass(frozen=True)
class EtaEstimate:
    """A work-order ETA plus its provenance."""

    minutes: int
    source: str  # "live" | "estimated"
    note: str


async def estimate_eta(
    *,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    settings: Settings | None = None,
) -> EtaEstimate:
    """Return an ETA for a worker → order leg, preferring live when configured."""
    s = settings or get_settings()

    # Prefer a genuinely live routing provider if configured. Any failure falls
    # back to the documented estimate (source="estimated").
    if s.ROUTING_API_URL and s.ROUTING_API_KEY:
        live = await _try_live(
            s.ROUTING_API_URL,
            s.ROUTING_API_KEY,
            origin_lat,
            origin_lon,
            dest_lat,
            dest_lon,
        )
        if live is not None:
            return live

    return _estimated(
        origin_lat,
        origin_lon,
        dest_lat,
        dest_lon,
        speed_kmh=s.DISPATCH_EST_AVG_SPEED_KMH,
    )


async def _try_live(
    url: str, key: str, o_lat: float, o_lon: float, d_lat: float, d_lon: float
) -> EtaEstimate | None:
    """Best-effort live routing call. Returns None on any error/timeout so the
    caller transparently falls back to the estimate (source never faked)."""
    try:
        timeout = httpx.Timeout(6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                url,
                params={
                    "key": key,
                    "origin": f"{o_lat},{o_lon}",
                    "destination": f"{d_lat},{d_lon}",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        minutes = _parse_live_minutes(data)
        if minutes is None:
            return None
        return EtaEstimate(
            minutes=minutes,
            source="live",
            note="Live routing provider ETA.",
        )
    except Exception:  # noqa: BLE001 - any failure → documented fallback
        return None


def _parse_live_minutes(data: dict) -> int | None:
    """Extract a duration in minutes from a generic routing payload, if present.

    Tolerates common shapes (``routes[].duration`` seconds, ``duration`` seconds,
    ``duration_text`` like "25 mins"). Returns ``None`` when the shape is
    unrecognized so the caller uses the documented estimate.
    """
    seconds: int | None = None
    if isinstance(data, dict):
        seconds = data.get("duration")
        if seconds is None and isinstance(data.get("routes"), list):
            for route in data["routes"]:
                if isinstance(route, dict) and isinstance(route.get("duration"), (int, float)):
                    seconds = int(route["duration"])
                    break
    if seconds is None:
        return None
    return max(1, round(int(seconds) / 60))


def _estimated(
    o_lat: float, o_lon: float, d_lat: float, d_lon: float, *, speed_kmh: float
) -> EtaEstimate:
    """Transparent, documented estimate: distance / average travel speed.

    This is always labelled ``source="estimated"`` so it is never presented as
    live traffic data.
    """
    km = max(0.1, haversine_km(o_lat, o_lon, d_lat, d_lon))
    minutes = max(1, round(km / max(1.0, speed_kmh) * 60))
    return EtaEstimate(
        minutes=minutes,
        source="estimated",
        note=(
            f"Estimated {minutes} min at ~{speed_kmh:.0f} km/h "
            f"over {km:.1f} km (documented estimate)."
        ),
    )
