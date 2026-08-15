"""Pydantic models for user profile requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints, model_validator

from app.schemas.auth import FullName, Username

ProfilePicture = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048)]
Bio = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class UserUpdateRequest(BaseModel):
    """Mutable fields of the authenticated user's profile.

    ``null`` clears a profile picture or bio. Identity fields cannot be set to
    ``null`` because their database columns are required.
    """

    model_config = ConfigDict(extra="forbid")

    username: Username | None = None
    full_name: FullName | None = None
    email: EmailStr | None = None
    profile_picture: ProfilePicture | None = None
    bio: Bio | None = None

    @model_validator(mode="after")
    def require_change(self) -> "UserUpdateRequest":
        """Reject empty update payloads and null required identity fields."""
        if not self.model_fields_set:
            raise ValueError("At least one profile field must be provided")

        for field_name in ("username", "full_name", "email"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class PublicUserResponse(BaseModel):
    """Non-sensitive profile data available through user lookup and search."""

    user_id: int
    username: str
    full_name: str
    account_type: str
    profile_picture: str | None
    bio: str | None
    created_at: datetime | None


class CurrentUserResponse(PublicUserResponse):
    """Full profile data returned only to the authenticated account owner."""

    email: EmailStr
    enrollment_id: str | None
    employee_id: str | None
    storage_used: int
    storage_limit: int
    email_verified: bool
    two_factor_enabled: bool
    account_status: str
    updated_at: datetime | None
    last_login: datetime | None
