"""FastAPI dependencies for authentication and authorization (RBAC)."""

from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.blacklist import is_blacklisted
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)


def _credentials_exc() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from a valid access token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _credentials_exc()

    try:
        claims = decode_token(credentials.credentials, "access")
    except jwt.PyJWTError as exc:
        raise _credentials_exc() from exc

    # Check token blacklist (logout / disable / password-reset).
    jti = claims.get("jti")
    if jti and await is_blacklisted(jti):
        raise _credentials_exc()

    try:
        user_id = uuid.UUID(claims["sub"])
    except (ValueError, KeyError) as exc:
        raise _credentials_exc() from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _credentials_exc()
    return user


def require_roles(*allowed: str):
    """Return a dependency that restricts an endpoint to the given role names.

    e.g. ``@router.get(..., dependencies=[Depends(require_roles("ADMIN"))])``
    """
    allowed_set = set(allowed)

    async def _role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role.name not in allowed_set:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You do not have permission to perform this action.",
            )
        return user

    return _role_checker
