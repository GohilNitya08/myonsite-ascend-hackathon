"""Pydantic models for authentication requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=30,
        pattern=r"^[A-Za-z0-9_]+$",
    ),
]
FullName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class PasswordValidationModel(BaseModel):
    """Apply bcrypt-compatible validation to password-bearing requests."""

    @staticmethod
    def _validate_password_length(password: str) -> str:
        if len(password.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 bytes")
        return password


class RegisterRequest(PasswordValidationModel):
    """Required details for creating a password-based account."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    full_name: FullName
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        return cls._validate_password_length(password)


class LoginRequest(PasswordValidationModel):
    """Credentials used to obtain an access and refresh token pair."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        return cls._validate_password_length(password)


class RefreshTokenRequest(BaseModel):
    """Refresh token supplied to obtain a new access token."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class ForgotPasswordRequest(BaseModel):
    """Email address for a password-reset request."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetPasswordRequest(PasswordValidationModel):
    """A password-reset token and the replacement password."""

    model_config = ConfigDict(extra="forbid")

    reset_token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        return cls._validate_password_length(password)


class GoogleAuthRequest(BaseModel):
    """Google identity token accepted once Google OAuth is configured."""

    model_config = ConfigDict(extra="forbid")

    id_token: str = Field(min_length=1)


class UserResponse(BaseModel):
    """Public account information returned after registration."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    full_name: str
    email: EmailStr
    account_type: str
    email_verified: bool
    created_at: datetime | None


class TokenResponse(BaseModel):
    """JWT credentials issued by login or refresh operations."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    access_token_expires_in: int


class MessageResponse(BaseModel):
    """A standard success response for operations without a resource body."""

    message: str
