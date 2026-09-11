"""Password hashing and JWT handling for CivicAgent.

Passwords are hashed with Argon2id (argon2-cffi) and never stored in plaintext.
Tokens are JSON Web Tokens signed with the configured secret.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_settings = get_settings()

_hasher = PasswordHasher(
    time_cost=_settings.PASSWORD_HASH_TIME_COST,
    memory_cost=_settings.PASSWORD_HASH_MEMORY_COST,
    parallelism=_settings.PASSWORD_HASH_PARALLELISM,
)

_PASSWORD_RULES = (
    r"(?=.*[a-z])"  # at least one lowercase
    r"(?=.*[A-Z])"  # at least one uppercase
    r"(?=.*\d)"  # at least one digit
    r"(?=.*[^A-Za-z0-9])"  # at least one special character
)
_PASSWORD_PATTERN = re.compile(_PASSWORD_RULES)

# Reasonable guard against pathologically huge inputs (DoS).
_MAX_EMAIL_LEN = 255
_MAX_PASSWORD_LEN = 128
_MIN_PASSWORD_LEN = 8


def hash_password(password: str) -> str:
    """Return an Argon2id hash of the password (plaintext is never stored)."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its Argon2id hash; returns False on any failure."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError, VerifyMismatchError):
        return False


def is_strong_password(password: str) -> tuple[bool, str | None]:
    """Validate password strength. Returns (ok, reason)."""
    if len(password) < _MIN_PASSWORD_LEN:
        return False, f"Password must be at least {_MIN_PASSWORD_LEN} characters."
    if len(password) > _MAX_PASSWORD_LEN:
        return False, f"Password must be at most {_MAX_PASSWORD_LEN} characters."
    if not _PASSWORD_PATTERN.match(password):
        return (
            False,
            "Password must contain uppercase, lowercase, a number, and a special character.",
        )
    return True, None


def _now() -> datetime:
    return datetime.now(UTC)


def _create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    settings = _settings
    now = _now()
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(user_id: str, role: str) -> str:
    """Short-lived access token with the user's role embedded for fast RBAC."""
    return _create_token(
        subject=user_id,
        token_type="access",
        expires_delta=timedelta(minutes=_settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims={"role": role},
    )


def create_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    """Create a refresh token.

    Returns (token, jti, expires_at). The jti is persisted server-side to support
    revocation.
    """
    expires_at = _now() + timedelta(days=_settings.REFRESH_TOKEN_EXPIRE_DAYS)
    token = _create_token(
        subject=user_id,
        token_type="refresh",
        expires_delta=timedelta(days=_settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    decoded = jwt.decode(  # decode ourselves to pull out the jti
        token,
        _settings.JWT_SECRET,
        algorithms=[_settings.JWT_ALGORITHM],
        audience=_settings.JWT_AUDIENCE,
        issuer=_settings.JWT_ISSUER,
    )
    return token, str(decoded["jti"]), expires_at


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """Validate a token (signature, expiry, issuer, audience, type) and return claims."""
    settings = _settings
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
        options={"require": ["exp", "iat", "sub", "jti", "type"]},
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Token is not a {expected_type} token")
    return payload
