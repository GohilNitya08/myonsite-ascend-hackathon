"""Business logic for file metadata, versions, favorites, and permissions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from app.repositories.file_repository import FileRecord, FileRepository, FileVersion
from app.repositories.folder_repository import Folder
from app.schemas.file import FileCreateRequest, FileUpdateRequest, FileVersionCreateRequest
from app.services.folder_service import (
    FolderNotFoundError,
    FolderPermissionError,
    FolderService,
)
from app.services.workspace_service import (
    WorkspaceNotFoundError,
    WorkspacePermissionError,
    WorkspaceService,
)


class FileError(Exception):
    """Base class for expected file-domain failures."""


class FileNotFoundError(FileError):
    """Raised when a requested file is absent or soft-deleted."""


class FilePermissionError(FileError):
    """Raised when the current workspace role cannot perform a file operation."""


class FileConflictError(FileError):
    """Raised when a valid request conflicts with file state."""


class FileService:
    """Coordinate file persistence with existing folder and workspace access rules."""

    def __init__(
        self,
        repository: FileRepository,
        folder_service: FolderService,
        workspace_service: WorkspaceService,
    ) -> None:
        self._repository = repository
        self._folder_service = folder_service
        self._workspace_service = workspace_service

    def create_file(self, actor_id: int, payload: FileCreateRequest) -> FileRecord:
        """Create file metadata in an active folder the caller can write to."""
        folder = self._get_active_folder(payload.folder_id, actor_id)
        self._require_writer(folder, actor_id)
        values = payload.model_dump()
        values["uploaded_by"] = actor_id
        try:
            file_id = self._repository.create_file(values)
            self._repository.record_activity(
                user_id=actor_id,
                file_id=file_id,
                activity_type="FILE_UPLOADED",
                detail=f"File '{payload.file_name}' uploaded",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        file = self._repository.get_by_id(file_id, user_id=actor_id, include_deleted=False)
        if file is None:
            raise RuntimeError("Created file could not be loaded")
        return file

    def list_files(
        self, folder_id: int, actor_id: int, *, include_deleted: bool
    ) -> list[FileRecord]:
        """List a readable folder's files with caller-specific favorite status."""
        self._get_active_folder(folder_id, actor_id)
        return self._repository.list_by_folder(
            folder_id, user_id=actor_id, include_deleted=include_deleted
        )

    def get_file(self, file_id: int, actor_id: int) -> FileRecord:
        """Return a non-deleted file after validating workspace membership."""
        file, _ = self._get_file_and_folder(file_id, actor_id, include_deleted=False)
        return file

    def update_file(
        self, file_id: int, actor_id: int, payload: FileUpdateRequest
    ) -> FileRecord:
        """Update mutable metadata of a file the caller can manage."""
        file, folder = self._get_file_and_folder(file_id, actor_id, include_deleted=False)
        self._require_file_manager(file, folder, actor_id)
        changes = {
            field_name: value
            for field_name, value in payload.model_dump(exclude_unset=True).items()
            if value != getattr(file, field_name)
        }
        if not changes:
            return file
        try:
            if not self._repository.update_metadata(file_id, changes):
                raise FileNotFoundError
            self._repository.record_activity(
                user_id=actor_id,
                file_id=file_id,
                activity_type="FILE_METADATA_UPDATED",
                detail="File metadata updated",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_file(file_id, actor_id)

    def delete_file(self, file_id: int, actor_id: int) -> None:
        """Soft-delete a managed file through the existing ``is_deleted`` field."""
        file, folder = self._get_file_and_folder(file_id, actor_id, include_deleted=False)
        self._require_file_manager(file, folder, actor_id)
        try:
            if not self._repository.set_deleted(file_id, is_deleted=True):
                raise FileNotFoundError
            self._repository.record_activity(
                user_id=actor_id,
                file_id=file_id,
                activity_type="FILE_DELETED",
                detail="File soft-deleted",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise

    def restore_file(self, file_id: int, actor_id: int) -> FileRecord:
        """Restore a soft-deleted file when its containing folder is active."""
        file, folder = self._get_file_and_folder(file_id, actor_id, include_deleted=True)
        if not file.is_deleted:
            return file
        self._require_file_manager(file, folder, actor_id)
        try:
            if not self._repository.set_deleted(file_id, is_deleted=False):
                raise FileNotFoundError
            self._repository.record_activity(
                user_id=actor_id,
                file_id=file_id,
                activity_type="FILE_RESTORED",
                detail="File restored",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_file(file_id, actor_id)

    def list_versions(self, file_id: int, actor_id: int) -> list[FileVersion]:
        """List versions of a readable non-deleted file."""
        self._get_file_and_folder(file_id, actor_id, include_deleted=False)
        return self._repository.list_versions(file_id)

    def create_version(
        self, file_id: int, actor_id: int, payload: FileVersionCreateRequest
    ) -> FileVersion:
        """Create the next sequential version metadata for a managed file."""
        file, folder = self._get_file_and_folder(file_id, actor_id, include_deleted=False)
        self._require_file_manager(file, folder, actor_id)
        version_number = self._repository.next_version_number(file_id)
        values = payload.model_dump()
        values.update(
            file_id=file_id,
            version_number=version_number,
            uploaded_by=actor_id,
        )
        try:
            version_id = self._repository.create_version(values)
            self._repository.record_activity(
                user_id=actor_id,
                file_id=file_id,
                activity_type="FILE_VERSION_CREATED",
                detail=f"Version {version_number} metadata created",
            )
            self._repository.commit()
        except IntegrityError as error:
            self._repository.rollback()
            raise FileConflictError("A file version was created concurrently; retry the request") from error
        except Exception:
            self._repository.rollback()
            raise
        version = self._repository.get_version(version_id)
        if version is None:
            raise RuntimeError("Created file version could not be loaded")
        return version

    def favorite_file(self, file_id: int, actor_id: int) -> FileRecord:
        """Mark a readable file as favorite for the current user only."""
        self._get_file_and_folder(file_id, actor_id, include_deleted=False)
        try:
            self._repository.add_favorite(file_id, actor_id)
            self._repository.record_activity(
                user_id=actor_id,
                file_id=file_id,
                activity_type="FILE_FAVORITED",
                detail="File added to favorites",
            )
            self._repository.commit()
        except IntegrityError as error:
            self._repository.rollback()
            raise FileConflictError("File is already favorited") from error
        except Exception:
            self._repository.rollback()
            raise
        return self.get_file(file_id, actor_id)

    def unfavorite_file(self, file_id: int, actor_id: int) -> FileRecord:
        """Remove the current user's favorite entry from a readable file."""
        self._get_file_and_folder(file_id, actor_id, include_deleted=False)
        try:
            if not self._repository.remove_favorite(file_id, actor_id):
                raise FileConflictError("File is not favorited")
            self._repository.record_activity(
                user_id=actor_id,
                file_id=file_id,
                activity_type="FILE_UNFAVORITED",
                detail="File removed from favorites",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_file(file_id, actor_id)

    def _get_file_and_folder(
        self, file_id: int, actor_id: int, *, include_deleted: bool
    ) -> tuple[FileRecord, Folder]:
        file = self._repository.get_by_id(
            file_id, user_id=actor_id, include_deleted=include_deleted
        )
        if file is None:
            raise FileNotFoundError
        folder = self._get_active_folder(file.folder_id, actor_id)
        return file, folder

    def _get_active_folder(self, folder_id: int, actor_id: int) -> Folder:
        try:
            return self._folder_service.get_folder(folder_id, actor_id)
        except FolderNotFoundError as error:
            raise FileNotFoundError("Folder not found") from error
        except FolderPermissionError as error:
            raise FilePermissionError from error

    def _require_writer(self, folder: Folder, actor_id: int) -> str:
        role = self._workspace_role(folder, actor_id)
        if role not in {"OWNER", "ADMIN", "EDITOR"}:
            raise FilePermissionError
        return role

    def _require_file_manager(self, file: FileRecord, folder: Folder, actor_id: int) -> None:
        role = self._require_writer(folder, actor_id)
        if role == "EDITOR" and file.uploaded_by != actor_id:
            raise FilePermissionError

    def _workspace_role(self, folder: Folder, actor_id: int) -> str:
        try:
            workspace = self._workspace_service.get_workspace(folder.workspace_id, actor_id)
        except WorkspaceNotFoundError as error:
            raise FileNotFoundError("Workspace not found") from error
        except WorkspacePermissionError as error:
            raise FilePermissionError from error
        if workspace.member_role is None:
            raise FilePermissionError
        return workspace.member_role
