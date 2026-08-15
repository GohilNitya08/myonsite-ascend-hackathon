"""SQLAlchemy data access for workspaces and their existing related tables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class Workspace:
    """A typed workspace record sourced from the existing ``workspaces`` table."""

    workspace_id: int
    user_id: int
    workspace_name: str
    description: str | None
    workspace_type: str
    visibility: str
    storage_used: int
    storage_limit: int
    color: str
    is_archived: bool
    created_at: datetime | None
    updated_at: datetime | None
    member_role: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Workspace":
        return cls(
            workspace_id=int(row["workspace_id"]),
            user_id=int(row["user_id"]),
            workspace_name=str(row["workspace_name"]),
            description=_optional_string(row["description"]),
            workspace_type=str(row["workspace_type"]),
            visibility=str(row["visibility"]),
            storage_used=int(row["storage_used"] or 0),
            storage_limit=int(row["storage_limit"] or 0),
            color=str(row["color"]),
            is_archived=bool(row["is_archived"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            member_role=_optional_string(row.get("member_role")),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceMember:
    """A typed membership record from ``workspace_members``."""

    member_id: int
    workspace_id: int
    user_id: int
    role: str
    invited_by: int | None
    joined_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "WorkspaceMember":
        return cls(
            member_id=int(row["member_id"]),
            workspace_id=int(row["workspace_id"]),
            user_id=int(row["user_id"]),
            role=str(row["role"]),
            invited_by=int(row["invited_by"]) if row["invited_by"] is not None else None,
            joined_at=row["joined_at"],
        )


@dataclass(frozen=True, slots=True)
class WorkspaceActivity:
    """An activity row associated with a workspace through a stable description prefix."""

    activity_id: int
    user_id: int
    activity_type: str
    activity_description: str | None
    created_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "WorkspaceActivity":
        return cls(
            activity_id=int(row["activity_id"]),
            user_id=int(row["user_id"]),
            activity_type=str(row["activity_type"]),
            activity_description=_optional_string(row["activity_description"]),
            created_at=row["created_at"],
        )


class WorkspaceRepository:
    """Encapsulate database reads and writes for workspace domain operations."""

    _WORKSPACE_COLUMNS = """
        workspace_id, user_id, workspace_name, description, workspace_type,
        visibility, storage_used, storage_limit, color, is_archived,
        created_at, updated_at
    """
    _SETTINGS_COLUMNS = {
        "workspace_name": "workspace_name",
        "description": "description",
        "visibility": "visibility",
        "color": "color",
    }

    def __init__(self, db: Session) -> None:
        self._db = db

    def create_workspace(self, values: Mapping[str, Any]) -> int:
        """Insert a workspace and return its database-generated BIGINT identifier."""
        result = self._db.execute(
            text(
                """
                INSERT INTO workspaces (
                    user_id, workspace_name, description, workspace_type,
                    visibility, storage_limit, color
                ) VALUES (
                    :user_id, :workspace_name, :description, :workspace_type,
                    :visibility, :storage_limit, :color
                )
                """
            ),
            values,
        )
        return int(result.lastrowid)

    def get_by_id(self, workspace_id: int) -> Workspace | None:
        """Return a workspace by its existing primary key."""
        row = (
            self._db.execute(
                text(
                    f"SELECT {self._WORKSPACE_COLUMNS} FROM workspaces "
                    "WHERE workspace_id = :workspace_id LIMIT 1"
                ),
                {"workspace_id": workspace_id},
            )
            .mappings()
            .first()
        )
        return Workspace.from_row(row) if row else None

    def list_for_user(self, user_id: int, *, include_archived: bool) -> list[Workspace]:
        """Return workspaces owned by or shared with a user."""
        archived_clause = "" if include_archived else " AND w.is_archived = FALSE"
        rows = (
            self._db.execute(
                text(
                    f"""
                    SELECT w.workspace_id, w.user_id, w.workspace_name, w.description,
                           w.workspace_type, w.visibility, w.storage_used,
                           w.storage_limit, w.color, w.is_archived, w.created_at,
                           w.updated_at,
                           COALESCE(wm.role, CASE WHEN w.user_id = :user_id THEN 'OWNER' END)
                               AS member_role
                    FROM workspaces AS w
                    LEFT JOIN workspace_members AS wm
                      ON wm.workspace_id = w.workspace_id AND wm.user_id = :user_id
                    WHERE (w.user_id = :user_id OR wm.user_id IS NOT NULL){archived_clause}
                    ORDER BY w.updated_at DESC, w.workspace_id DESC
                    """
                ),
                {"user_id": user_id},
            )
            .mappings()
            .all()
        )
        return [Workspace.from_row(row) for row in rows]

    def get_membership(self, workspace_id: int, user_id: int) -> WorkspaceMember | None:
        """Return one user's membership for a workspace."""
        row = (
            self._db.execute(
                text(
                    """
                    SELECT member_id, workspace_id, user_id, role, invited_by, joined_at
                    FROM workspace_members
                    WHERE workspace_id = :workspace_id AND user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"workspace_id": workspace_id, "user_id": user_id},
            )
            .mappings()
            .first()
        )
        return WorkspaceMember.from_row(row) if row else None

    def list_members(self, workspace_id: int) -> list[WorkspaceMember]:
        """Return all membership records for a workspace."""
        rows = (
            self._db.execute(
                text(
                    """
                    SELECT member_id, workspace_id, user_id, role, invited_by, joined_at
                    FROM workspace_members
                    WHERE workspace_id = :workspace_id
                    ORDER BY CASE role
                        WHEN 'OWNER' THEN 1
                        WHEN 'ADMIN' THEN 2
                        WHEN 'EDITOR' THEN 3
                        ELSE 4
                    END, member_id ASC
                    """
                ),
                {"workspace_id": workspace_id},
            )
            .mappings()
            .all()
        )
        return [WorkspaceMember.from_row(row) for row in rows]

    def add_member(
        self, *, workspace_id: int, user_id: int, role: str, invited_by: int | None
    ) -> int:
        """Create a membership and return its database-generated BIGINT identifier."""
        result = self._db.execute(
            text(
                """
                INSERT INTO workspace_members (workspace_id, user_id, role, invited_by)
                VALUES (:workspace_id, :user_id, :role, :invited_by)
                """
            ),
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "role": role,
                "invited_by": invited_by,
            },
        )
        return int(result.lastrowid)

    def update_settings(self, workspace_id: int, changes: Mapping[str, Any]) -> bool:
        """Apply validated workspace-setting changes."""
        unsupported_fields = set(changes).difference(self._SETTINGS_COLUMNS)
        if unsupported_fields or not changes:
            raise ValueError("Unsupported or empty workspace settings update")
        assignments = [
            f"{self._SETTINGS_COLUMNS[field_name]} = :{field_name}"
            for field_name in changes
        ]
        assignments.append("updated_at = UTC_TIMESTAMP()")
        result = self._db.execute(
            text(
                "UPDATE workspaces SET "
                + ", ".join(assignments)
                + " WHERE workspace_id = :workspace_id"
            ),
            {**changes, "workspace_id": workspace_id},
        )
        return result.rowcount == 1

    def update_storage_limit(self, workspace_id: int, storage_limit: int) -> bool:
        """Set the configured storage limit without changing recorded usage."""
        result = self._db.execute(
            text(
                """
                UPDATE workspaces
                SET storage_limit = :storage_limit, updated_at = UTC_TIMESTAMP()
                WHERE workspace_id = :workspace_id
                """
            ),
            {"workspace_id": workspace_id, "storage_limit": storage_limit},
        )
        return result.rowcount == 1

    def set_archived(self, workspace_id: int, *, is_archived: bool) -> bool:
        """Set the existing archive flag on a workspace."""
        result = self._db.execute(
            text(
                """
                UPDATE workspaces
                SET is_archived = :is_archived, updated_at = UTC_TIMESTAMP()
                WHERE workspace_id = :workspace_id
                """
            ),
            {"workspace_id": workspace_id, "is_archived": is_archived},
        )
        return result.rowcount == 1

    def update_member_role(self, workspace_id: int, user_id: int, role: str) -> bool:
        """Update a member role while retaining its existing membership record."""
        result = self._db.execute(
            text(
                """
                UPDATE workspace_members
                SET role = :role
                WHERE workspace_id = :workspace_id AND user_id = :user_id
                """
            ),
            {"workspace_id": workspace_id, "user_id": user_id, "role": role},
        )
        return result.rowcount == 1

    def remove_member(self, workspace_id: int, user_id: int) -> bool:
        """Remove one membership record."""
        result = self._db.execute(
            text(
                "DELETE FROM workspace_members "
                "WHERE workspace_id = :workspace_id AND user_id = :user_id"
            ),
            {"workspace_id": workspace_id, "user_id": user_id},
        )
        return result.rowcount == 1

    def transfer_ownership(
        self, *, workspace_id: int, previous_owner_id: int, new_owner_id: int
    ) -> bool:
        """Transfer table ownership and synchronise the two membership roles."""
        result = self._db.execute(
            text(
                "UPDATE workspaces SET user_id = :new_owner_id, updated_at = UTC_TIMESTAMP() "
                "WHERE workspace_id = :workspace_id AND user_id = :previous_owner_id"
            ),
            {
                "workspace_id": workspace_id,
                "previous_owner_id": previous_owner_id,
                "new_owner_id": new_owner_id,
            },
        )
        if result.rowcount != 1:
            return False
        self.update_member_role(workspace_id, previous_owner_id, "ADMIN")
        return self.update_member_role(workspace_id, new_owner_id, "OWNER")

    def delete_workspace(self, workspace_id: int) -> bool:
        """Delete a workspace; database foreign keys handle dependent records."""
        result = self._db.execute(
            text("DELETE FROM workspaces WHERE workspace_id = :workspace_id"),
            {"workspace_id": workspace_id},
        )
        return result.rowcount == 1

    def record_activity(
        self, *, workspace_id: int, user_id: int, activity_type: str, detail: str
    ) -> None:
        """Store a workspace action using the available activity-log schema."""
        self._db.execute(
            text(
                """
                INSERT INTO activity_logs (user_id, activity_type, activity_description)
                VALUES (:user_id, :activity_type, :activity_description)
                """
            ),
            {
                "user_id": user_id,
                "activity_type": activity_type,
                "activity_description": f"Workspace {workspace_id}: {detail}",
            },
        )

    def list_activity(self, workspace_id: int, *, limit: int) -> list[WorkspaceActivity]:
        """Return activity rows produced by this workspace module."""
        rows = (
            self._db.execute(
                text(
                    """
                    SELECT activity_id, user_id, activity_type, activity_description, created_at
                    FROM activity_logs
                    WHERE activity_description LIKE :workspace_prefix
                    ORDER BY created_at DESC, activity_id DESC
                    LIMIT :limit
                    """
                ),
                {"workspace_prefix": f"Workspace {workspace_id}:%", "limit": limit},
            )
            .mappings()
            .all()
        )
        return [WorkspaceActivity.from_row(row) for row in rows]

    def commit(self) -> None:
        """Commit the current request transaction."""
        self._db.commit()

    def rollback(self) -> None:
        """Roll back the current request transaction."""
        self._db.rollback()


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
