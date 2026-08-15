"""SQLAlchemy data access for the existing ``file_shares`` table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class FileShare:
    """A typed file-share record without exposing ownership implementation details."""

    share_id: int
    file_id: int
    shared_by: int
    shared_with: int | None
    share_type: str
    permission: str
    share_link: str | None
    password_hash: str | None
    expires_at: datetime | None
    created_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "FileShare":
        return cls(
            share_id=int(row["share_id"]),
            file_id=int(row["file_id"]),
            shared_by=int(row["shared_by"]),
            shared_with=int(row["shared_with"]) if row["shared_with"] is not None else None,
            share_type=str(row["share_type"]),
            permission=str(row["permission"]),
            share_link=_optional_string(row["share_link"]),
            password_hash=_optional_string(row["password_hash"]),
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )


class ShareRepository:
    """Encapsulate creation, lookup, update, and revocation of file shares."""

    _SHARE_COLUMNS = """
        share_id, file_id, shared_by, shared_with, share_type, permission,
        share_link, password_hash, expires_at, created_at
    """
    _UPDATE_COLUMNS = {
        "permission": "permission",
        "password_hash": "password_hash",
        "expires_at": "expires_at",
    }

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, values: Mapping[str, Any]) -> int:
        """Insert a share and return its database-generated BIGINT identifier."""
        result = self._db.execute(
            text(
                """
                INSERT INTO file_shares (
                    file_id, shared_by, shared_with, share_type, permission,
                    share_link, password_hash, expires_at
                ) VALUES (
                    :file_id, :shared_by, :shared_with, :share_type, :permission,
                    :share_link, :password_hash, :expires_at
                )
                """
            ),
            values,
        )
        return int(result.lastrowid)

    def get_by_id(self, share_id: int) -> FileShare | None:
        """Return a share record by primary key."""
        row = (
            self._db.execute(
                text(
                    f"SELECT {self._SHARE_COLUMNS} FROM file_shares "
                    "WHERE share_id = :share_id LIMIT 1"
                ),
                {"share_id": share_id},
            )
            .mappings()
            .first()
        )
        return FileShare.from_row(row) if row else None

    def list_by_sharer(self, shared_by: int) -> list[FileShare]:
        """List shares created by a user, newest first."""
        rows = (
            self._db.execute(
                text(
                    f"""
                    SELECT {self._SHARE_COLUMNS}
                    FROM file_shares
                    WHERE shared_by = :shared_by
                    ORDER BY created_at DESC, share_id DESC
                    """
                ),
                {"shared_by": shared_by},
            )
            .mappings()
            .all()
        )
        return [FileShare.from_row(row) for row in rows]

    def get_by_link(self, share_link: str) -> FileShare | None:
        """Return a share with an existing generated link token, if any."""
        row = (
            self._db.execute(
                text(
                    f"SELECT {self._SHARE_COLUMNS} FROM file_shares "
                    "WHERE share_link = :share_link LIMIT 1"
                ),
                {"share_link": share_link},
            )
            .mappings()
            .first()
        )
        return FileShare.from_row(row) if row else None

    def get_active_duplicate(
        self, *, file_id: int, share_type: str, shared_with: int | None
    ) -> FileShare | None:
        """Find an unexpired share with the same file, type, and recipient scope."""
        recipient_clause = (
            "shared_with = :shared_with" if shared_with is not None else "shared_with IS NULL"
        )
        row = (
            self._db.execute(
                text(
                    f"""
                    SELECT {self._SHARE_COLUMNS}
                    FROM file_shares
                    WHERE file_id = :file_id
                      AND share_type = :share_type
                      AND {recipient_clause}
                      AND (expires_at IS NULL OR expires_at > UTC_TIMESTAMP())
                    LIMIT 1
                    """
                ),
                {
                    "file_id": file_id,
                    "share_type": share_type,
                    "shared_with": shared_with,
                },
            )
            .mappings()
            .first()
        )
        return FileShare.from_row(row) if row else None

    def update(self, share_id: int, changes: Mapping[str, Any]) -> bool:
        """Apply validated mutable share controls."""
        unsupported_fields = set(changes).difference(self._UPDATE_COLUMNS)
        if unsupported_fields or not changes:
            raise ValueError("Unsupported or empty share update")
        assignments = [
            f"{self._UPDATE_COLUMNS[field_name]} = :{field_name}"
            for field_name in changes
        ]
        result = self._db.execute(
            text(
                "UPDATE file_shares SET "
                + ", ".join(assignments)
                + " WHERE share_id = :share_id"
            ),
            {**changes, "share_id": share_id},
        )
        return result.rowcount == 1

    def delete(self, share_id: int) -> bool:
        """Remove a share record to revoke access using the existing schema."""
        result = self._db.execute(
            text("DELETE FROM file_shares WHERE share_id = :share_id"),
            {"share_id": share_id},
        )
        return result.rowcount == 1

    def commit(self) -> None:
        """Commit the current request transaction."""
        self._db.commit()

    def rollback(self) -> None:
        """Roll back the current request transaction."""
        self._db.rollback()


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
