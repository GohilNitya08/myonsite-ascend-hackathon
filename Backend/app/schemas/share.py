"""Pydantic v2 request and response models for file shares."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.auth import PasswordValidationModel

ShareType = Literal["PRIVATE", "PUBLIC", "LINK"]
SharePermission = Literal["VIEW", "EDIT"]


class ShareCreateRequest(PasswordValidationModel):
    """Details for a private, public, or link-based file share."""

    model_config = ConfigDict(extra="forbid")

    file_id: int = Field(gt=0)
    share_type: ShareType
    permission: SharePermission = "VIEW"
    shared_with: int | None = Field(default=None, gt=0)
    link_password: str | None = Field(default=None, min_length=8, max_length=72)
    expires_at: datetime | None = None

    @field_validator("link_password")
    @classmethod
    def validate_link_password(cls, password: str | None) -> str | None:
        if password is not None:
            cls._validate_password_length(password)
        return password

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, expires_at: datetime | None) -> datetime | None:
        return _validate_future_expiry(expires_at)


class ShareUpdateRequest(PasswordValidationModel):
    """Mutable share controls; an explicit null password removes link protection."""

    model_config = ConfigDict(extra="forbid")

    permission: SharePermission | None = None
    link_password: str | None = Field(default=None, min_length=8, max_length=72)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ShareUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one share field must be provided")
        if "permission" in self.model_fields_set and self.permission is None:
            raise ValueError("permission cannot be null")
        return self

    @field_validator("link_password")
    @classmethod
    def validate_link_password(cls, password: str | None) -> str | None:
        if password is not None:
            cls._validate_password_length(password)
        return password

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, expires_at: datetime | None) -> datetime | None:
        return _validate_future_expiry(expires_at)


class ShareResponse(BaseModel):
    """Share metadata without exposing a stored password hash."""

    share_id: int
    file_id: int
    shared_by: int
    shared_with: int | None
    share_type: ShareType
    permission: SharePermission
    share_link: str | None
    password_protected: bool
    expires_at: datetime | None
    created_at: datetime | None


def _validate_future_expiry(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("expires_at must include a timezone")
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("expires_at must be in the future")
    return expires_at
