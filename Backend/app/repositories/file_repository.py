"""SQLAlchemy data access for existing file, version, favorite, and activity tables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class FileRecord:
    """A typed file record with the requesting user's favorite state."""

    file_id: int
    folder_id: int
    uploaded_by: int
    file_name: str
    original_file_name: str
    file_extension: str | None
    mime_type: str | None
    file_size: int
    storage_path: str
    file_hash: str
    ai_enabled: bool
    is_archived: bool
    is_deleted: bool
    is_favorite: bool
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "FileRecord":
        return cls(
            file_id=int(row["file_id"]),
            folder_id=int(row["folder_id"]),
            uploaded_by=int(row["uploaded_by"]),
            file_name=str(row["file_name"]),
            original_file_name=str(row["original_file_name"]),
            file_extension=_optional_string(row["file_extension"]),
            mime_type=_optional_string(row["mime_type"]),
            file_size=int(row["file_size"]),
            storage_path=str(row["storage_path"]),
            file_hash=str(row["file_hash"]),
            ai_enabled=bool(row["ai_enabled"]),
            is_archived=bool(row["is_archived"]),
            is_deleted=bool(row["is_deleted"]),
            is_favorite=bool(row["is_favorite"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class FileVersion:
    """A typed version metadata record."""

    version_id: int
    file_id: int
    version_number: int
    storage_path: str
    file_size: int
    file_hash: str
    uploaded_by: int
    version_note: str | None
    created_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "FileVersion":
        return cls(
            version_id=int(row["version_id"]),
            file_id=int(row["file_id"]),
            version_number=int(row["version_number"]),
            storage_path=str(row["storage_path"]),
            file_size=int(row["file_size"]),
            file_hash=str(row["file_hash"]),
            uploaded_by=int(row["uploaded_by"]),
            version_note=_optional_string(row["version_note"]),
            created_at=row["created_at"],
        )


class FileRepository:
    """Encapsulate file metadata, versions, favorites, and activity persistence."""

    _FILE_COLUMNS = """
        f.file_id, f.folder_id, f.uploaded_by, f.file_name, f.original_file_name,
        f.file_extension, f.mime_type, f.file_size, f.storage_path, f.file_hash,
        f.ai_enabled, f.is_archived, f.is_deleted, f.created_at, f.updated_at
    """
    _UPDATE_COLUMNS = {
        "file_name": "file_name",
        "mime_type": "mime_type",
        "ai_enabled": "ai_enabled",
    }

    def __init__(self, db: Session) -> None:
        self._db = db

    def create_file(self, values: Mapping[str, Any]) -> int:
        """Insert file metadata and return its database-generated BIGINT identifier."""
        result = self._db.execute(
            text(
                """
                INSERT INTO files (
                    folder_id, uploaded_by, file_name, original_file_name, file_extension,
                    mime_type, file_size, storage_path, file_hash, ai_enabled
                ) VALUES (
                    :folder_id, :uploaded_by, :file_name, :original_file_name, :file_extension,
                    :mime_type, :file_size, :storage_path, :file_hash, :ai_enabled
                )
                """
            ),
            values,
        )
        return int(result.lastrowid)

    def get_by_id(
        self, file_id: int, *, user_id: int, include_deleted: bool
    ) -> FileRecord | None:
        """Return file metadata with the requesting user's favorite state."""
        deleted_clause = "" if include_deleted else " AND f.is_deleted = FALSE"
        row = (
            self._db.execute(
                text(
                    f"""
                    SELECT {self._FILE_COLUMNS},
                           EXISTS(
                               SELECT 1 FROM favorites AS fav
                               WHERE fav.file_id = f.file_id AND fav.user_id = :user_id
                           ) AS is_favorite
                    FROM files AS f
                    WHERE f.file_id = :file_id{deleted_clause}
                    LIMIT 1
                    """
                ),
                {"file_id": file_id, "user_id": user_id},
            )
            .mappings()
            .first()
        )
        return FileRecord.from_row(row) if row else None

    def list_by_folder(
        self, folder_id: int, *, user_id: int, include_deleted: bool
    ) -> list[FileRecord]:
        """List folder files with caller-specific favorite state."""
        deleted_clause = "" if include_deleted else " AND f.is_deleted = FALSE"
        rows = (
            self._db.execute(
                text(
                    f"""
                    SELECT {self._FILE_COLUMNS},
                           EXISTS(
                               SELECT 1 FROM favorites AS fav
                               WHERE fav.file_id = f.file_id AND fav.user_id = :user_id
                           ) AS is_favorite
                    FROM files AS f
                    WHERE f.folder_id = :folder_id{deleted_clause}
                    ORDER BY f.updated_at DESC, f.file_id DESC
                    """
                ),
                {"folder_id": folder_id, "user_id": user_id},
            )
            .mappings()
            .all()
        )
        return [FileRecord.from_row(row) for row in rows]

    def update_metadata(self, file_id: int, changes: Mapping[str, Any]) -> bool:
        """Apply validated mutable metadata to a non-deleted file."""
        unsupported_fields = set(changes).difference(self._UPDATE_COLUMNS)
        if unsupported_fields or not changes:
            raise ValueError("Unsupported or empty file update")
        assignments = [
            f"{self._UPDATE_COLUMNS[field_name]} = :{field_name}"
            for field_name in changes
        ]
        assignments.append("updated_at = UTC_TIMESTAMP()")
        result = self._db.execute(
            text(
                "UPDATE files SET "
                + ", ".join(assignments)
                + " WHERE file_id = :file_id AND is_deleted = FALSE"
            ),
            {**changes, "file_id": file_id},
        )
        return result.rowcount == 1

    def set_deleted(self, file_id: int, *, is_deleted: bool) -> bool:
        """Set the existing soft-delete flag on file metadata."""
        result = self._db.execute(
            text(
                """
                UPDATE files
                SET is_deleted = :is_deleted, updated_at = UTC_TIMESTAMP()
                WHERE file_id = :file_id
                """
            ),
            {"file_id": file_id, "is_deleted": is_deleted},
        )
        return result.rowcount >= 1

    def list_versions(self, file_id: int) -> list[FileVersion]:
        """Return all version metadata in ascending version order."""
        rows = (
            self._db.execute(
                text(
                    """
                    SELECT version_id, file_id, version_number, storage_path, file_size,
                           file_hash, uploaded_by, version_note, created_at
                    FROM file_versions
                    WHERE file_id = :file_id
                    ORDER BY version_number ASC, version_id ASC
                    """
                ),
                {"file_id": file_id},
            )
            .mappings()
            .all()
        )
        return [FileVersion.from_row(row) for row in rows]

    def next_version_number(self, file_id: int) -> int:
        """Return the next sequential version number for a file."""
        value = self._db.execute(
            text(
                "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version "
                "FROM file_versions WHERE file_id = :file_id"
            ),
            {"file_id": file_id},
        ).scalar_one()
        return int(value)

    def create_version(self, values: Mapping[str, Any]) -> int:
        """Insert immutable version metadata and return its BIGINT identifier."""
        result = self._db.execute(
            text(
                """
                INSERT INTO file_versions (
                    file_id, version_number, storage_path, file_size, file_hash,
                    uploaded_by, version_note
                ) VALUES (
                    :file_id, :version_number, :storage_path, :file_size, :file_hash,
                    :uploaded_by, :version_note
                )
                """
            ),
            values,
        )
        return int(result.lastrowid)

    def get_version(self, version_id: int) -> FileVersion | None:
        """Return a version record by its database-generated identifier."""
        row = (
            self._db.execute(
                text(
                    """
                    SELECT version_id, file_id, version_number, storage_path, file_size,
                           file_hash, uploaded_by, version_note, created_at
                    FROM file_versions
                    WHERE version_id = :version_id
                    LIMIT 1
                    """
                ),
                {"version_id": version_id},
            )
            .mappings()
            .first()
        )
        return FileVersion.from_row(row) if row else None

    def add_favorite(self, file_id: int, user_id: int) -> int:
        """Create a caller-specific favorite record."""
        result = self._db.execute(
            text("INSERT INTO favorites (user_id, file_id) VALUES (:user_id, :file_id)"),
            {"file_id": file_id, "user_id": user_id},
        )
        return int(result.lastrowid)

    def remove_favorite(self, file_id: int, user_id: int) -> bool:
        """Remove the caller's favorite record for a file."""
        result = self._db.execute(
            text("DELETE FROM favorites WHERE file_id = :file_id AND user_id = :user_id"),
            {"file_id": file_id, "user_id": user_id},
        )
        return result.rowcount == 1

    def record_activity(
        self, *, user_id: int, file_id: int, activity_type: str, detail: str
    ) -> None:
        """Record a file action through the existing activity-log table."""
        self._db.execute(
            text(
                """
                INSERT INTO activity_logs (user_id, file_id, activity_type, activity_description)
                VALUES (:user_id, :file_id, :activity_type, :activity_description)
                """
            ),
            {
                "user_id": user_id,
                "file_id": file_id,
                "activity_type": activity_type,
                "activity_description": detail,
            },
        )

    def commit(self) -> None:
        """Commit the current request transaction."""
        self._db.commit()

    def rollback(self) -> None:
        """Roll back the current request transaction."""
        self._db.rollback()


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
