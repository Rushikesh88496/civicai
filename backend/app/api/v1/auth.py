"""Authentication API endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.blacklist import blacklist_token
from app.core.security import decode_token
from app.db.session import get_db
from app.middleware.rate_limit import (
    LIMIT_LOGIN,
    LIMIT_PASSWORD_RESET,
    LIMIT_REGISTER,
    limiter,
)
from app.models import User
from app.schemas.auth import (
    AuthResponse,
    ForgotPasswordIn,
    ForgotPasswordResponse,
    LoginIn,
    MessageResponse,
    RefreshIn,
    RegisterIn,
    ResetPasswordIn,
    TokenPair,
)
from app.schemas.user import MeResponse, UpdateProfileIn, UserProfileOut
from app.services import auth_service
from app.services.audit_service import (
    ACTION_LOGIN,
    ACTION_LOGOUT,
    ACTION_PASSWORD_RESET,
    ACTION_REGISTER,
    record_audit,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register", response_model=AuthResponse, status_code=201)
@limiter.limit(LIMIT_REGISTER)
async def register(
    request: Request,
    response: Response,
    payload: RegisterIn,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    result = await auth_service.register_user(db, payload)
    await record_audit(
        db,
        actor_id=None,
        action=ACTION_REGISTER,
        entity_type="user",
        entity_id=str(result.user.id),
        after={"email": result.user.email, "role": result.user.role.name},
        ip_address=_client_ip(request),
    )
    await db.commit()
    return result


@router.post("/login", response_model=AuthResponse)
@limiter.limit(LIMIT_LOGIN)
async def login(
    request: Request,
    response: Response,
    payload: LoginIn,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    result = await auth_service.login_user(db, payload.email, payload.password)
    await record_audit(
        db,
        actor_id=result.user.id,
        action=ACTION_LOGIN,
        entity_type="user",
        entity_id=str(result.user.id),
        after={"email": result.user.email, "role": result.user.role.name},
        ip_address=_client_ip(request),
    )
    await db.commit()
    return result


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshIn, db: AsyncSession = Depends(get_db)) -> TokenPair:
    return await auth_service.refresh_access_token(db, payload.refresh_token)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    payload: RefreshIn,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    result = await auth_service.logout_user(db, payload.refresh_token)
    user_id = _sub_of(payload.refresh_token, "refresh")
    # Blacklist the access token that was used in the Authorization header.
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header[7:]
        try:
            import time

            claims = decode_token(raw_token, "access")
            jti = claims.get("jti")
            exp = claims.get("exp")
            if jti and exp:
                ttl = max(int(exp - time.time()), 1)
                await blacklist_token(jti, ttl)
        except Exception:
            pass  # best-effort blacklist; logout still succeeds
    await record_audit(
        db,
        actor_id=None if user_id is None else uuid.UUID(user_id),
        action=ACTION_LOGOUT,
        entity_type="user",
        entity_id=user_id or (payload.refresh_token[:16] + "..."),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return result


def _sub_of(token: str, token_type: str) -> str | None:
    """Return the ``sub`` claim (user id) of a decodable token, else None."""
    try:
        claims = decode_token(token, token_type)
        return claims.get("sub")
    except Exception:
        return None


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
@limiter.limit(LIMIT_PASSWORD_RESET)
async def forgot_password(
    request: Request,
    response: Response,
    payload: ForgotPasswordIn,
    db: AsyncSession = Depends(get_db),
) -> ForgotPasswordResponse:
    return await auth_service.forgot_password(db, payload.email)


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit(LIMIT_PASSWORD_RESET)
async def reset_password(
    request: Request,
    response: Response,
    payload: ResetPasswordIn,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    result = await auth_service.reset_password(db, payload.token, payload.new_password)
    user_id = _sub_of(payload.token, "password_reset")
    await record_audit(
        db,
        actor_id=None if user_id is None else uuid.UUID(user_id),
        action=ACTION_PASSWORD_RESET,
        entity_type="user",
        entity_id=user_id or "via-token",
        ip_address=_client_ip(request),
    )
    await db.commit()
    return result


@router.get("/me", response_model=MeResponse)
async def me(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> MeResponse:
    return await auth_service.get_me(db, user.id)


@router.patch("/me/profile", response_model=UserProfileOut)
async def update_profile(
    payload: UpdateProfileIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfileOut:
    return await auth_service.update_my_profile(db, user.id, payload)
