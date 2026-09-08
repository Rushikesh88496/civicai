"""Redis-backed access-token blacklist for CivicAgent.

Provides a thin Redis-based JTI blacklist used to revoke access tokens on
logout, user disable, or password reset.  Tokens carry a TTL equal to their
remaining expiry so entries are automatically cleaned up.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from redis import asyncio as aioredis

from app.core.config import get_settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_KEY_PREFIX = "civicagent:token:blacklist:"
_DEFAULT_TTL_SECONDS = 30 * 60  # matches ACCESS_TOKEN_EXPIRE_MINUTES

_redis: aioredis.Redis | None = None
_last_failure_at: float | None = None
_RETRY_AFTER_SECONDS = 10.0


async def _get_redis() -> aioredis.Redis | None:
    """Return (and lazily create) the shared async Redis connection.

    Failures are cached with a short backoff so a down Redis only costs one
    connection attempt every ``_RETRY_AFTER_SECONDS`` instead of stalling every
    request with a connect timeout.
    """
    global _redis, _last_failure_at  # noqa: PLW0603
    settings = get_settings()
    if not settings.REDIS_URL:
        return None
    if _redis is not None:
        return _redis
    if _last_failure_at is not None:
        if time.monotonic() - _last_failure_at < _RETRY_AFTER_SECONDS:
            return None
    try:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        await _redis.ping()
        _last_failure_at = None
    except Exception:
        logger.warning("Redis unavailable; token blacklist disabled", exc_info=True)
        _redis = None
        _last_failure_at = time.monotonic()
        return None
    return _redis


async def blacklist_token(jti: str, ttl_seconds: int | None = None) -> None:
    """Add a token JTI to the blacklist with an optional TTL."""
    r = await _get_redis()
    if r is None:
        return
    ttl = ttl_seconds or _DEFAULT_TTL_SECONDS
    key = f"{_KEY_PREFIX}{jti}"
    try:
        await r.setex(key, ttl, "1")
    except Exception:
        logger.warning("Failed to blacklist token jti=%s", jti, exc_info=True)


async def is_blacklisted(jti: str) -> bool:
    """Return True if the given JTI is in the blacklist."""
    r = await _get_redis()
    if r is None:
        return False
    key = f"{_KEY_PREFIX}{jti}"
    try:
        return bool(await r.exists(key))
    except Exception:
        logger.warning("Redis blacklist check failed for jti=%s", jti, exc_info=True)
        return False
