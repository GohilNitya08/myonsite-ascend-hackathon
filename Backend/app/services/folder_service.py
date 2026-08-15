"""Business rules for folder hierarchy, permissions, and soft deletion."""

from __future__ import annotations

from typing import Any

from app.repositories.folder_repository import Folder, FolderRepository
from app.schemas.folder import (
    FolderCreateRequest,
    FolderMoveRequest,
    FolderTreeResponse,
    FolderUpdateRequest,
)
from app.services.workspace_service import (
    WorkspaceNotFoundError,
    WorkspacePermissionError,
    WorkspaceService,
)


class FolderError(Exception):
    """Base class for expected folder-domain failures."""


class FolderNotFoundError(FolderError):
    """Raised when a requested active folder does not exist."""


class FolderPermissionError(FolderError):
    """Raised when the current workspace role cannot perform an action."""


class FolderConflictError(FolderError):
    """Raised when a hierarchy operation would create invalid folder state."""


class FolderService:
    """Coordinate folder persistence with existing workspace authorization."""

    def __init__(
        self, repository: FolderRepository, workspace_service: WorkspaceService
    ) -> None:
        self._repository = repository
        self._workspace_service = workspace_service

    def create_folder(self, actor_id: int, payload: FolderCreateRequest) -> Folder:
        """Create a root or child folder after validating its workspace and parent."""
        self._require_workspace_writer(payload.workspace_id, actor_id)
        self._validate_parent(
            workspace_id=payload.workspace_id,
            parent_folder_id=payload.parent_folder_id,
        )
        values = payload.model_dump()
        values["created_by"] = actor_id
        try:
            folder_id = self._repository.create(values)
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        folder = self._repository.get_by_id(folder_id, include_archived=False)
        if folder is None:
            raise RuntimeError("Created folder could not be loaded")
        return folder

    def list_folders(
        self, workspace_id: int, actor_id: int, *, include_archived: bool
    ) -> list[Folder]:
        """List folders in a workspace available to the current member."""
        self._require_workspace_access(workspace_id, actor_id)
        return self._repository.list_by_workspace(
            workspace_id, include_archived=include_archived
        )

    def get_folder(self, folder_id: int, actor_id: int) -> Folder:
        """Return an active folder if the caller can access its workspace."""
        folder = self._require_folder(folder_id, include_archived=False)
        self._require_workspace_access(folder.workspace_id, actor_id)
        return folder

    def update_folder(
        self, folder_id: int, actor_id: int, payload: FolderUpdateRequest
    ) -> Folder:
        """Update editable properties of an active folder."""
        folder = self._require_folder(folder_id, include_archived=False)
        self._require_folder_manager(folder, actor_id)
        changes = {
            field_name: value
            for field_name, value in payload.model_dump(exclude_unset=True).items()
            if value != getattr(folder, field_name)
        }
        if not changes:
            return folder
        try:
            if not self._repository.update(folder_id, changes):
                raise FolderNotFoundError
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_folder(folder_id, actor_id)

    def move_folder(
        self, folder_id: int, actor_id: int, payload: FolderMoveRequest
    ) -> Folder:
        """Move a folder to a new parent or the workspace root without cycles."""
        folder = self._require_folder(folder_id, include_archived=False)
        self._require_folder_manager(folder, actor_id)
        if payload.parent_folder_id == folder.parent_folder_id:
            return folder
        if payload.parent_folder_id is not None:
            self._validate_parent(
                workspace_id=folder.workspace_id,
                parent_folder_id=payload.parent_folder_id,
            )
            if payload.parent_folder_id == folder_id:
                raise FolderConflictError("A folder cannot be its own parent")
            if payload.parent_folder_id in self._subtree_ids(folder_id):
                raise FolderConflictError("A folder cannot be moved into one of its descendants")
        try:
            if not self._repository.move(folder_id, payload.parent_folder_id):
                raise FolderNotFoundError
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_folder(folder_id, actor_id)

    def delete_folder(self, folder_id: int, actor_id: int) -> None:
        """Soft-delete an active folder and all of its descendants."""
        folder = self._require_folder(folder_id, include_archived=False)
        self._require_folder_manager(folder, actor_id)
        subtree_ids = self._subtree_ids(folder_id)
        try:
            if self._repository.set_archived(subtree_ids, is_archived=True) < 1:
                raise FolderNotFoundError
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise

    def restore_folder(self, folder_id: int, actor_id: int) -> Folder:
        """Restore an archived folder subtree when its parent is active or absent."""
        folder = self._require_folder(folder_id, include_archived=True)
        if not folder.is_archived:
            return self.get_folder(folder_id, actor_id)
        self._require_folder_manager(folder, actor_id)
        if folder.parent_folder_id is not None:
            parent = self._repository.get_by_id(
                folder.parent_folder_id, include_archived=False
            )
            if parent is None:
                raise FolderConflictError("Restore the parent folder before restoring this folder")
        subtree_ids = self._subtree_ids(folder_id)
        try:
            if self._repository.set_archived(subtree_ids, is_archived=False) < 1:
                raise FolderNotFoundError
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_folder(folder_id, actor_id)

    def get_tree(self, workspace_id: int, actor_id: int) -> list[FolderTreeResponse]:
        """Build the active parent-child hierarchy for an accessible workspace."""
        self._require_workspace_access(workspace_id, actor_id)
        folders = self._repository.list_by_workspace(workspace_id, include_archived=False)
        nodes = {
            folder.folder_id: FolderTreeResponse(
                folder_id=folder.folder_id,
                workspace_id=folder.workspace_id,
                parent_folder_id=folder.parent_folder_id,
                folder_name=folder.folder_name,
                description=folder.description,
                color=folder.color,
                is_favorite=folder.is_favorite,
                is_archived=folder.is_archived,
                created_by=folder.created_by,
                created_at=folder.created_at,
                updated_at=folder.updated_at,
            )
            for folder in folders
        }
        roots: list[FolderTreeResponse] = []
        for folder in folders:
            node = nodes[folder.folder_id]
            if folder.parent_folder_id is None or folder.parent_folder_id not in nodes:
                roots.append(node)
            else:
                nodes[folder.parent_folder_id].children.append(node)
        return roots

    def _require_folder(self, folder_id: int, *, include_archived: bool) -> Folder:
        folder = self._repository.get_by_id(folder_id, include_archived=include_archived)
        if folder is None:
            raise FolderNotFoundError
        return folder

    def _require_workspace_access(self, workspace_id: int, actor_id: int) -> str:
        try:
            workspace = self._workspace_service.get_workspace(workspace_id, actor_id)
        except WorkspaceNotFoundError as error:
            raise FolderNotFoundError("Workspace not found") from error
        except WorkspacePermissionError as error:
            raise FolderPermissionError from error
        if workspace.member_role is None:
            raise FolderPermissionError
        return workspace.member_role

    def _require_workspace_writer(self, workspace_id: int, actor_id: int) -> str:
        role = self._require_workspace_access(workspace_id, actor_id)
        if role not in {"OWNER", "ADMIN", "EDITOR"}:
            raise FolderPermissionError
        return role

    def _require_folder_manager(self, folder: Folder, actor_id: int) -> None:
        role = self._require_workspace_writer(folder.workspace_id, actor_id)
        if role == "EDITOR" and folder.created_by != actor_id:
            raise FolderPermissionError

    def _validate_parent(self, *, workspace_id: int, parent_folder_id: int | None) -> None:
        if parent_folder_id is None:
            return
        parent = self._repository.get_by_id(parent_folder_id, include_archived=False)
        if parent is None:
            raise FolderNotFoundError("Parent folder not found")
        if parent.workspace_id != workspace_id:
            raise FolderConflictError("Parent folder must belong to the same workspace")

    def _subtree_ids(self, folder_id: int) -> list[int]:
        """Collect a folder and all descendants without relying on database recursion."""
        subtree_ids: list[int] = []
        frontier = [folder_id]
        seen: set[int] = set()
        while frontier:
            current_id = frontier.pop()
            if current_id in seen:
                continue
            seen.add(current_id)
            subtree_ids.append(current_id)
            frontier.extend(self._repository.list_child_ids([current_id]))
        return subtree_ids
