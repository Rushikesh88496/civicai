"""Authentication and identity business logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import RefreshToken, Role, User, UserProfile
from app.models.enums import RoleName
from app.schemas.auth import (
    AuthResponse,
    ForgotPasswordResponse,
    MessageResponse,
    RegisterIn,
    TokenPair,
    UserOut,
)
from app.schemas.user import MeResponse, UpdateProfileIn, UserProfileOut
from app.services import language_service

settings = get_settings()

_STATUS_FORBIDDEN = status.HTTP_403_FORBIDDEN
_STATUS_UNAUTHORIZED = status.HTTP_401_UNAUTHORIZED


def _now() -> datetime:
    return datetime.now(UTC)


def _to_user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


async def _issue_token_pair(db: AsyncSession, user: User) -> TokenPair:
    """Mint an access token and persist a revocable refresh token."""
    access_token = create_access_token(str(user.id), user.role.name)

    refresh_token, jti, expires_at = create_refresh_token(str(user.id))
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=jti,
            token_hash=hash_password(refresh_token),
            expires_at=expires_at,
            revoked=False,
        )
    )
    await db.flush()

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def register_user(db: AsyncSession, payload: RegisterIn) -> AuthResponse:
    """Create a new citizen user and return a token pair."""
    email = payload.email.lower().strip()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")

    role = await db.scalar(select(Role).where(Role.name == RoleName.CITIZEN.value))
    if role is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Default CITIZEN role is missing. Run the development seed script first.",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role_id=role.id,
        is_active=True,
        is_email_verified=False,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id))
    await db.flush()

    tokens = await _issue_token_pair(db, user)
    await db.commit()
    await db.refresh(user)
    return AuthResponse(user=_to_user_out(user), tokens=tokens)


async def login_user(db: AsyncSession, email: str, password: str) -> AuthResponse:
    """Authenticate a user and return tokens."""
    email = email.lower().strip()
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash):
        # Generic message to avoid user enumeration.
        raise HTTPException(
            _STATUS_UNAUTHORIZED,
            "Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(_STATUS_FORBIDDEN, "This account has been disabled.")

    tokens = await _issue_token_pair(db, user)
    await db.commit()
    await db.refresh(user)
    return AuthResponse(user=_to_user_out(user), tokens=tokens)


async def _find_refresh_token(db: AsyncSession, jti: str) -> RefreshToken | None:
    return await db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> TokenPair:
    """Validate a refresh token, revoke it, and mint a new pair (rotation)."""
    try:
        claims = decode_token(refresh_token, "refresh")
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(_STATUS_UNAUTHORIZED, "Refresh token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(_STATUS_UNAUTHORIZED, "Invalid refresh token.") from exc

    record = await _find_refresh_token(db, claims["jti"])
    if record is None:
        raise HTTPException(_STATUS_UNAUTHORIZED, "Invalid refresh token.")

    if record.revoked:
        raise HTTPException(_STATUS_UNAUTHORIZED, "Refresh token has been revoked.")

    if not verify_password(refresh_token, record.token_hash):
        raise HTTPException(_STATUS_UNAUTHORIZED, "Invalid refresh token.")

    user = await db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(_STATUS_UNAUTHORIZED, "Account is no longer available.")

    # Rotate session: revoke the used token, mint a fresh pair.
    record.revoked = True
    record.revoked_at = _now()
    tokens = await _issue_token_pair(db, user)
    await db.commit()
    return tokens


async def logout_user(db: AsyncSession, refresh_token: str) -> MessageResponse:
    """Revoke the supplied refresh token (idempotent)."""
    try:
        claims = decode_token(refresh_token, "refresh")
    except jwt.InvalidTokenError:
        return MessageResponse(message="Logged out.")

    record = await _find_refresh_token(db, claims["jti"])
    if record is not None and not record.revoked:
        record.revoked = True
        record.revoked_at = _now()
        await db.commit()
    return MessageResponse(message="Logged out.")


async def forgot_password(db: AsyncSession, email: str) -> ForgotPasswordResponse:
    """Issue a password-reset token.

    NOTE: no mailer exists yet, so the token is only echoed back in dev/demo mode.
    Production must email the reset link instead of returning the token.
    """
    user = await db.scalar(select(User).where(User.email == email.lower().strip()))
    if user is None:
        # Do not reveal whether the email exists.
        return ForgotPasswordResponse(
            message="If that email is registered, a reset link has been sent."
        )

    reset_token = jwt.encode(
        {
            "sub": str(user.id),
            "type": "password_reset",
            "jti": str(uuid.uuid4()),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

    token_in_response = bool(settings.DEBUG) or (user.email in _DEMO_RESET_EMAILS)
    return ForgotPasswordResponse(
        message="If that email is registered, a reset link has been sent.",
        reset_token=reset_token if token_in_response else None,
    )


# Emails that may receive their reset token back in dev/demo (still only when
# DEBUG is enabled too). Kept empty; seed/demo can populate as needed.
_DEMO_RESET_EMAILS: set[str] = set()


async def reset_password(db: AsyncSession, token: str, new_password: str) -> MessageResponse:
    """Validate a reset token and set a new password, revoking all sessions."""
    try:
        claims = decode_token(token, "password_reset")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(_STATUS_UNAUTHORIZED, "Invalid or expired reset token.") from exc

    try:
        user_id = uuid.UUID(claims["sub"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(_STATUS_UNAUTHORIZED, "Invalid or expired reset token.") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(_STATUS_UNAUTHORIZED, "Invalid or expired reset token.")

    user.password_hash = hash_password(new_password)

    active_sessions = await db.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
    )
    for record in active_sessions:
        record.revoked = True
        record.revoked_at = _now()

    await db.commit()
    return MessageResponse(message="Your password has been reset. Please log in again.")


async def get_me(db: AsyncSession, user_id: uuid.UUID) -> MeResponse:
    """Return the current user with profile and role loaded."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    await db.refresh(user, attribute_names=["profile", "role"])
    return MeResponse(user=_to_user_out(user))


async def update_my_profile(
    db: AsyncSession, user_id: uuid.UUID, payload: UpdateProfileIn
) -> UserProfileOut:
    """Update the current user's profile fields."""
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found.")

    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "language":
            # Part 26: only persist a genuinely supported code; unsupported /
            # malformed values are dropped (None = English behaviour) instead of
            # being coerced to English.
            value = value if language_service.supported(value) == value else None
        setattr(profile, key, value)
    await db.commit()
    await db.refresh(profile)
    return UserProfileOut.model_validate(profile)
