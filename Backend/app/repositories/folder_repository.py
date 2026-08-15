"""SQLAlchemy data access for the existing ``folders`` table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class Folder:
    """A typed folder record from the database schema."""

    folder_id: int
    workspace_id: int
    parent_folder_id: int | None
    folder_name: str
    description: str | None
    color: str
    is_favorite: bool
    is_archived: bool
    created_by: int
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Folder":
        return cls(
            folder_id=int(row["folder_id"]),
            workspace_id=int(row["workspace_id"]),
            parent_folder_id=(
                int(row["parent_folder_id"])
                if row["parent_folder_id"] is not None
                else None
            ),
            folder_name=str(row["folder_name"]),
            description=_optional_string(row["description"]),
            color=str(row["color"]),
            is_favorite=bool(row["is_favorite"]),
            is_archived=bool(row["is_archived"]),
            created_by=int(row["created_by"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class FolderRepository:
    """Encapsulate folder reads, hierarchy queries, and soft-delete updates."""

    _FOLDER_COLUMNS = """
        folder_id, workspace_id, parent_folder_id, folder_name, description,
        color, is_favorite, is_archived, created_by, created_at, updated_at
    """
    _UPDATE_COLUMNS = {
        "folder_name": "folder_name",
        "description": "description",
        "color": "color",
        "is_favorite": "is_favorite",
    }

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, values: Mapping[str, Any]) -> int:
        """Create a folder and return its database-generated BIGINT identifier."""
        result = self._db.execute(
            text(
                """
                INSERT INTO folders (
                    workspace_id, parent_folder_id, folder_name, description, color, created_by
                ) VALUES (
                    :workspace_id, :parent_folder_id, :folder_name, :description, :color,
                    :created_by
                )
                """
            ),
            values,
        )
        return int(result.lastrowid)

    def get_by_id(self, folder_id: int, *, include_archived: bool) -> Folder | None:
        """Return a folder by id, optionally including archived folders."""
        archived_clause = "" if include_archived else " AND is_archived = FALSE"
        row = (
            self._db.execute(
                text(
                    f"SELECT {self._FOLDER_COLUMNS} FROM folders "
                    f"WHERE folder_id = :folder_id{archived_clause} LIMIT 1"
                ),
                {"folder_id": folder_id},
            )
            .mappings()
            .first()
        )
        return Folder.from_row(row) if row else None

    def list_by_workspace(self, workspace_id: int, *, include_archived: bool) -> list[Folder]:
        """Return workspace folders in parent/name order."""
        archived_clause = "" if include_archived else " AND is_archived = FALSE"
        rows = (
            self._db.execute(
                text(
                    f"""
                    SELECT {self._FOLDER_COLUMNS}
                    FROM folders
                    WHERE workspace_id = :workspace_id{archived_clause}
                    ORDER BY parent_folder_id ASC, folder_name ASC, folder_id ASC
                    """
                ),
                {"workspace_id": workspace_id},
            )
            .mappings()
            .all()
        )
        return [Folder.from_row(row) for row in rows]

    def update(self, folder_id: int, changes: Mapping[str, Any]) -> bool:
        """Apply validated non-hierarchy changes to an active folder."""
        unsupported_fields = set(changes).difference(self._UPDATE_COLUMNS)
        if unsupported_fields or not changes:
            raise ValueError("Unsupported or empty folder update")
        assignments = [
            f"{self._UPDATE_COLUMNS[field_name]} = :{field_name}"
            for field_name in changes
        ]
        assignments.append("updated_at = UTC_TIMESTAMP()")
        result = self._db.execute(
            text(
                "UPDATE folders SET "
                + ", ".join(assignments)
                + " WHERE folder_id = :folder_id AND is_archived = FALSE"
            ),
            {**changes, "folder_id": folder_id},
        )
        return result.rowcount == 1

    def move(self, folder_id: int, parent_folder_id: int | None) -> bool:
        """Set a folder's parent relationship while keeping it in its workspace."""
        result = self._db.execute(
            text(
                """
                UPDATE folders
                SET parent_folder_id = :parent_folder_id, updated_at = UTC_TIMESTAMP()
                WHERE folder_id = :folder_id AND is_archived = FALSE
                """
            ),
            {"folder_id": folder_id, "parent_folder_id": parent_folder_id},
        )
        return result.rowcount == 1

    def list_child_ids(self, parent_ids: list[int]) -> list[int]:
        """Return direct child identifiers for the supplied parent identifiers."""
        if not parent_ids:
            return []
        query = text(
            "SELECT folder_id FROM folders WHERE parent_folder_id IN :parent_ids"
        ).bindparams(bindparam("parent_ids", expanding=True))
        rows = self._db.execute(query, {"parent_ids": parent_ids}).mappings().all()
        return [int(row["folder_id"]) for row in rows]

    def set_archived(self, folder_ids: list[int], *, is_archived: bool) -> int:
        """Soft-delete or restore all supplied folder identifiers in one update."""
        if not folder_ids:
            return 0
        query = text(
            """
            UPDATE folders
            SET is_archived = :is_archived, updated_at = UTC_TIMESTAMP()
            WHERE folder_id IN :folder_ids
            """
        ).bindparams(bindparam("folder_ids", expanding=True))
        result = self._db.execute(
            query,
            {"folder_ids": folder_ids, "is_archived": is_archived},
        )
        return int(result.rowcount)

    def commit(self) -> None:
        """Commit the current request transaction."""
        self._db.commit()

    def rollback(self) -> None:
        """Roll back the current request transaction."""
        self._db.rollback()


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
