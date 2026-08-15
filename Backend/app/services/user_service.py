"""Business logic for retrieving and managing user profiles."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from app.repositories.user_repository import User, UserRepository
from app.schemas.user import UserUpdateRequest
from app.services.auth_service import (
    DuplicateEmailError,
    DuplicateUsernameError,
    UserNotFoundError,
)


class UserService:
    """Coordinate user profile validation, repository access, and transactions."""

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def get_current_user(self, user_id: int) -> User:
        """Return the authenticated user's active profile."""
        return self.get_user(user_id)

    def get_user(self, user_id: int) -> User:
        """Return an active user's public profile source data."""
        user = self._repository.get_active_by_id(user_id)
        if user is None:
            raise UserNotFoundError
        return user

    def search_users(self, query: str, *, limit: int) -> list[User]:
        """Return active users matching a normalized non-empty search term."""
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("Search query must contain at least one non-whitespace character")
        return self._repository.search_active(normalized_query, limit=limit)

    def update_current_user(self, user_id: int, payload: UserUpdateRequest) -> User:
        """Apply allowed profile changes while preserving unique identity fields."""
        current_user = self.get_current_user(user_id)
        changes = self._changed_fields(current_user, payload)
        if not changes:
            return current_user

        self._ensure_identity_is_available(user_id=user_id, changes=changes)
        try:
            if not self._repository.update_profile(user_id, changes):
                self._repository.rollback()
                raise UserNotFoundError
            self._repository.commit()
        except IntegrityError:
            self._repository.rollback()
            self._raise_duplicate_after_conflict(user_id=user_id, changes=changes)
            raise

        updated_user = self._repository.get_active_by_id(user_id)
        if updated_user is None:
            raise RuntimeError("Updated user could not be loaded")
        return updated_user

    def delete_current_user(self, user_id: int) -> None:
        """Soft-delete the authenticated account and commit the change."""
        try:
            if not self._repository.soft_delete(user_id):
                self._repository.rollback()
                raise UserNotFoundError
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise

    def _ensure_identity_is_available(self, *, user_id: int, changes: dict[str, Any]) -> None:
        if "username" in changes:
            existing_username = self._repository.get_by_username(str(changes["username"]))
            if existing_username is not None and existing_username.user_id != user_id:
                raise DuplicateUsernameError
        if "email" in changes:
            existing_email = self._repository.get_by_email(str(changes["email"]))
            if existing_email is not None and existing_email.user_id != user_id:
                raise DuplicateEmailError

    def _raise_duplicate_after_conflict(self, *, user_id: int, changes: dict[str, Any]) -> None:
        """Translate a unique-constraint race into the existing auth-domain errors."""
        self._ensure_identity_is_available(user_id=user_id, changes=changes)

    @staticmethod
    def _changed_fields(user: User, payload: UserUpdateRequest) -> dict[str, Any]:
        changes = payload.model_dump(exclude_unset=True)
        if "email" in changes:
            changes["email"] = str(changes["email"]).lower()

        return {
            field_name: value
            for field_name, value in changes.items()
            if value != getattr(user, field_name)
        }
