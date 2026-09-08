"""Encryption helpers for secret configuration overrides (Part 27).

Policy: raw API keys are NEVER stored in the database or returned through API
responses. When a super admin chooses to override a key at runtime, the
plaintext is authenticated-encrypted with ``cryptography.Fernet`` (AES-128-CBC
+ HMAC via SHA256) using a key derived from the server's ``JWT_SECRET`` before
it is persisted in ``system_settings.value``.

``JWT_SECRET`` is a high-entropy, server-side-only secret (>= 32 bytes enforced
by ``app/core/config.py``), so the derived Fernet key is never shared with the
browser. This is defense-in-depth on top of environment-based configuration —
the recommended production path is to configure keys via environment variables
and leave ``value`` unset.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    """Derive a Fernet key from the configured JWT secret (stable per process)."""
    secret = get_settings().JWT_SECRET.encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret value for at-rest storage (never the raw value)."""
    if not isinstance(plaintext, str) or not plaintext.strip():
        raise ValueError("A secret value must be a non-empty string.")
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str | None:
    """Decrypt a stored secret token; returns None when the token is invalid."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def mask_secret(plaintext: str | None) -> str | None:
    """Return a masked preview (''••••'' + last 4 chars) for display only.

    Never exposes the full value. ``None`` input yields ``None`` so callers can
    distinguish "not configured" from an empty mask.
    """
    if not plaintext:
        return None
    if len(plaintext) <= 4:
        return "••••"
    return f"••••{plaintext[-4:]}"
