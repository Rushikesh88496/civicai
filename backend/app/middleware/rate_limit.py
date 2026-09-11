"""Rate-limiting configuration for CivicAgent using slowapi.

Applies per-IP rate limits with Redis-backed storage when available,
falling back to an in-memory limiter for local development.

Route-specific limits are defined on the router and can be overridden
per-endpoint using ``@limiter.limit(...)`` decorators.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from app.core.config import get_settings

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Build the limiter — Redis when available, memory fallback otherwise.
# ---------------------------------------------------------------------------

_settings = get_settings()
_storage_uri: str | None = _settings.REDIS_URL or None

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri,
    default_limits=["120/minute"],  # sane global fallback
    headers_enabled=True,
    enabled=_settings.RATE_LIMIT_ENABLED,
    # When Redis is configured but unreachable, degrade to an in-memory limiter
    # instead of raising 500s on every request (exactly what happens before
    # Redis first comes up in a fresh environment).
    in_memory_fallback_enabled=True,
)


# ---------------------------------------------------------------------------
# Custom error handler — returns a clean JSON 429.
# ---------------------------------------------------------------------------


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Render rate-limit errors as a structured JSON response."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please slow down and try again later.",
            "retry_after": getattr(exc, "retry_after", None),
        },
    )


# ---------------------------------------------------------------------------
# Pre-defined endpoint limit strings (used in main.py / router files).
# ---------------------------------------------------------------------------

LIMIT_LOGIN = "5/minute"
LIMIT_REGISTER = "3/minute"
LIMIT_PASSWORD_RESET = "3/minute"
LIMIT_FILE_UPLOAD = "20/minute"
LIMIT_ADMIN = "60/minute"
LIMIT_GENERAL = "120/minute"
LIMIT_AI_ACTION = "30/minute"
