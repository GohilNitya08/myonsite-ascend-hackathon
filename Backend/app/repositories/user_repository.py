"""Database access for user profiles against the existing ``users`` table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class User:
    """A typed representation of the user profile columns used by this module."""

    user_id: int
    username: str
    full_name: str
    email: str
    account_type: str
    enrollment_id: str | None
    employee_id: str | None
    profile_picture: str | None
    bio: str | None
    storage_used: int
    storage_limit: int
    email_verified: bool
    two_factor_enabled: bool
    account_status: str
    created_at: datetime | None
    updated_at: datetime | None
    last_login: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "User":
        """Create a typed user value from a SQLAlchemy mapping result."""
        return cls(
            user_id=int(row["user_id"]),
            username=str(row["username"]),
            full_name=str(row["full_name"]),
            email=str(row["email"]),
            account_type=str(row["account_type"]),
            enrollment_id=_optional_string(row["enrollment_id"]),
            employee_id=_optional_string(row["employee_id"]),
            profile_picture=_optional_string(row["profile_picture"]),
            bio=_optional_string(row["bio"]),
            storage_used=int(row["storage_used"] or 0),
            storage_limit=int(row["storage_limit"] or 0),
            email_verified=bool(row["email_verified"]),
            two_factor_enabled=bool(row["two_factor_enabled"]),
            account_status=str(row["account_status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login=row["last_login"],
        )


class UserRepository:
    """Encapsulate profile reads, updates, searches, and soft deletion."""

    _USER_COLUMNS = """
        user_id, username, full_name, email, account_type, enrollment_id,
        employee_id, profile_picture, bio, storage_used, storage_limit,
        email_verified, two_factor_enabled, account_status, created_at,
        updated_at, last_login
    """
    _PROFILE_COLUMNS = {
        "username": "username",
        "full_name": "full_name",
        "email": "email",
        "profile_picture": "profile_picture",
        "bio": "bio",
    }

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, user_id: int) -> User | None:
        """Return a user by primary key regardless of account status."""
        return self._get_one_by_id(user_id=user_id, active_only=False)

    def get_active_by_id(self, user_id: int) -> User | None:
        """Return an active user by primary key, if one exists."""
        return self._get_one_by_id(user_id=user_id, active_only=True)

    def get_by_email(self, email: str) -> User | None:
        """Return a user matching an email address, if one exists."""
        return self._get_one_by("email", email)

    def get_by_username(self, username: str) -> User | None:
        """Return a user matching a username, if one exists."""
        return self._get_one_by("username", username)

    def search_active(self, query: str, *, limit: int) -> list[User]:
        """Search active users by username or full name."""
        rows = (
            self._db.execute(
                text(
                    f"""
                    SELECT {self._USER_COLUMNS}
                    FROM users
                    WHERE account_status = 'ACTIVE'
                      AND (username LIKE :pattern OR full_name LIKE :pattern)
                    ORDER BY username ASC, user_id ASC
                    LIMIT :limit
                    """
                ),
                {"pattern": f"%{query}%", "limit": limit},
            )
            .mappings()
            .all()
        )
        return [User.from_row(row) for row in rows]

    def update_profile(self, user_id: int, changes: Mapping[str, Any]) -> bool:
        """Apply validated profile changes to an active user."""
        unsupported_fields = set(changes).difference(self._PROFILE_COLUMNS)
        if unsupported_fields:
            raise ValueError("Unsupported profile field")
        if not changes:
            return False

        assignments = [
            f"{self._PROFILE_COLUMNS[field_name]} = :{field_name}"
            for field_name in changes
        ]
        if "email" in changes:
            assignments.append("email_verified = FALSE")
        assignments.append("updated_at = UTC_TIMESTAMP()")

        result = self._db.execute(
            text(
                "UPDATE users SET "
                + ", ".join(assignments)
                + " WHERE user_id = :user_id AND account_status = 'ACTIVE'"
            ),
            {**changes, "user_id": user_id},
        )
        return result.rowcount == 1

    def soft_delete(self, user_id: int) -> bool:
        """Mark an active account as deleted without removing related records."""
        result = self._db.execute(
            text(
                """
                UPDATE users
                SET account_status = 'DELETED', updated_at = UTC_TIMESTAMP()
                WHERE user_id = :user_id AND account_status = 'ACTIVE'
                """
            ),
            {"user_id": user_id},
        )
        return result.rowcount == 1

    def commit(self) -> None:
        """Commit the current request transaction."""
        self._db.commit()

    def rollback(self) -> None:
        """Roll back the current request transaction."""
        self._db.rollback()

    def _get_one_by_id(self, *, user_id: int, active_only: bool) -> User | None:
        active_clause = " AND account_status = 'ACTIVE'" if active_only else ""
        row = (
            self._db.execute(
                text(
                    f"SELECT {self._USER_COLUMNS} FROM users "
                    f"WHERE user_id = :user_id{active_clause} LIMIT 1"
                ),
                {"user_id": user_id},
            )
            .mappings()
            .first()
        )
        return User.from_row(row) if row else None

    def _get_one_by(self, column: str, value: str) -> User | None:
        if column not in {"email", "username"}:
            raise ValueError("Unsupported user lookup column")

        row = (
            self._db.execute(
                text(
                    f"SELECT {self._USER_COLUMNS} FROM users "
                    f"WHERE {column} = :value LIMIT 1"
                ),
                {"value": value},
            )
            .mappings()
            .first()
        )
        return User.from_row(row) if row else None


def _optional_string(value: Any) -> str | None:
    """Return optional database text as a string."""
    return str(value) if value is not None else None
