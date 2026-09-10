"""Request/response schemas for the authentication endpoints."""

import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import is_strong_password


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    # Every citizen must pick one of the active reference wards at signup
    # (Part 31). The service layer re-validates that the ward exists + is active.
    ward_id: uuid.UUID

    @field_validator("password")
    @classmethod
    def _check_strength(cls, v: str) -> str:
        ok, reason = is_strong_password(v)
        if not ok:
            raise ValueError(reason or "Weak password.")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthResponse(BaseModel):
    user: "UserOut"
    tokens: TokenPair


class RefreshIn(BaseModel):
    refresh_token: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_strength(cls, v: str) -> str:
        ok, reason = is_strong_password(v)
        if not ok:
            raise ValueError(reason or "Weak password.")
        return v


class MessageResponse(BaseModel):
    message: str


class ForgotPasswordResponse(BaseModel):
    message: str
    # Dev/demo only: normally the reset link is emailed. Never return in production.
    reset_token: str | None = None


from app.schemas.user import UserOut  # noqa: E402  (for model rebuild/forward ref)

AuthResponse.model_rebuild()
