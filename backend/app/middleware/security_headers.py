"""HTTP security headers middleware for CivicAgent.

Adds standard security headers to every response:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: camera=(), microphone=(), geolocation=(self)
- X-XSS-Protection: 0 (modern browsers; relying on CSP instead)
- Strict-Transport-Security: max-age=15768000; includeSubDomains (when not localhost)
- Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline';
  style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:;
  connect-src 'self' ws: wss:
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach hardening headers to every HTTP response."""

    _HEADERS: dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(self)",
        "X-XSS-Protection": "0",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' ws: wss:"
        ),
    }

    _HSTS_HEADER = "Strict-Transport-Security"
    _HSTS_VALUE = "max-age=15768000; includeSubDomains"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for key, value in self._HEADERS.items():
            response.headers[key] = value
        # HSTS only over HTTPS (not localhost / dev HTTP).
        if request.url.scheme == "https":
            response.headers[self._HSTS_HEADER] = self._HSTS_VALUE
        return response
