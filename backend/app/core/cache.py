"""Redis cache helpers for the Context Enrichment Agent (Part 11).

External lookups (e.g. Open-Meteo weather) can be cached in Redis with a TTL to
avoid hammering upstream APIs for repeat runs on the same coordinates. The
helpers here add three behaviours on top of the raw client in ``app.core.redis``:

* **Hit / miss / TTL** — ``cache_get_json`` only returns a hit for a key that
  exists *and* Redis reports as live (Redis enforces the TTL, so an expired key
  is simply absent → miss).
* **Graceful fallback** — Redis is a *soft* dependency. If it is unreachable or
  errors, ``cache_get_json`` returns ``(None, False)`` (a miss) and
  ``cache_set_json`` is a no-op, so the agent simply fetches live and succeeds.
  Callers must never treat a cache error as fatal.
* **Namespacing** — keys are built under ``settings.CONTEXT_CACHE_NAMESPACE`` to
  avoid collisions with other cached data.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import Settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


def cache_key(settings: Settings, *parts: str) -> str:
    """Build a namespaced Redis key from the configured namespace and parts."""
    return ":".join([settings.CONTEXT_CACHE_NAMESPACE, *parts])


async def cache_get_json(settings: Settings, key: str) -> tuple[Any | None, bool]:
    """Return ``(value, is_hit)`` for a cached JSON string.

    ``is_hit`` is ``True`` only when a live, unexpired value was read from Redis.
    On a miss or any Redis error we return ``(None, False)`` so callers fall back
    to a live retrieval. Graceful fallback is the contract — this never raises.
    """
    if not settings.WEATHER_CACHE_ENABLED or not key:
        return None, False
    try:
        client = await get_redis()
        raw = await client.get(key)
        if raw is None:
            return None, False
        return json.loads(raw), True
    except Exception as exc:  # noqa: BLE001 - cache must never break the agent
        logger.warning("Redis cache get failed for %r (falling back to live): %s", key, exc)
        return None, False


async def cache_set_json(settings: Settings, key: str, value: Any, ttl: int) -> None:
    """Cache ``value`` serialized as JSON under ``key`` with a TTL (seconds).

    Never raises on Redis failure — a failed write simply means the next run
    fetches live again.
    """
    if not settings.WEATHER_CACHE_ENABLED or not key:
        return
    try:
        client = await get_redis()
        await client.set(key, json.dumps(value), ex=ttl)
    except Exception as exc:  # noqa: BLE001 - cache write must not be fatal
        logger.warning("Redis cache set failed for %r (ignored): %s", key, exc)


async def cache_delete(settings: Settings, key: str) -> None:
    """Remove a key (best-effort; never raises)."""
    if not settings.WEATHER_CACHE_ENABLED or not key:
        return
    try:
        client = await get_redis()
        await client.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis cache delete failed for %r (ignored): %s", key, exc)
