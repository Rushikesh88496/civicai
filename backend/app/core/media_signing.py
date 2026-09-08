"""Short-lived signed URLs for locally-served media (Part 28, 1F).

Uploaded evidence is exposed at ``/media/<key>``. Plain files must never be
reachable without authentication, but browser ``<img>``/``<video>`` tags cannot
send ``Authorization`` headers — so each generated URL carries an HMAC token
with a short expiry. The ``/media`` route accepts either this token or a valid
Bearer access token.
"""

from __future__ import annotations

import hashlib
import hmac
import time


def sign_media_token(
    key: str,
    *,
    secret: str,
    ttl_seconds: int,
    now: float | None = None,
) -> str:
    """Return an ``<exp>.<digest>`` token for ``key`` valid for ``ttl_seconds``."""
    expires = int((now if now is not None else time.time()) + ttl_seconds)
    digest = _digest(key, expires, secret)
    return f"{expires}.{digest}"


def verify_media_token(
    key: str,
    token: str,
    *,
    secret: str,
    now: float | None = None,
    skew_seconds: float = 30.0,
) -> bool:
    """Return True when ``token`` is an unexpired valid signature for ``key``."""
    try:
        expires_part, _, digest = token.partition(".")
        expires = int(expires_part)
    except (TypeError, ValueError):
        return False
    current = now if now is not None else time.time()
    if current > expires + skew_seconds or expires > current + skew_seconds + 900:
        return False
    expected = _digest(key, expires, secret)
    return hmac.compare_digest(expected, digest)


def _digest(key: str, expires: int, secret: str) -> str:
    message = f"{key}|{expires}".encode()
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
