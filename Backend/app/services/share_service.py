"""Business rules for secure file sharing using the existing schema."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.repositories.file_repository import FileRecord
from app.repositories.folder_repository import Folder
from app.repositories.share_repository import FileShare, ShareRepository
from app.schemas.share import ShareCreateRequest, ShareUpdateRequest
from app.services.auth_service import PASSWORD_CONTEXT, UserNotFoundError
from app.services.file_service import FileNotFoundError, FilePermissionError, FileService
from app.services.folder_service import FolderNotFoundError, FolderPermissionError, FolderService
from app.services.user_service import UserService
from app.services.workspace_service import (
    WorkspaceNotFoundError,
    WorkspacePermissionError,
    WorkspaceService,
)


class ShareError(Exception):
    """Base class for expected sharing-domain failures."""


class ShareNotFoundError(ShareError):
    """Raised when a share or required share resource does not exist."""


class SharePermissionError(ShareError):
    """Raised when a caller is not the workspace owner or an administrator."""


class ShareConflictError(ShareError):
    """Raised when a duplicate active share or unique-link conflict occurs."""


class ShareValidationError(ShareError):
    """Raised when share fields cannot be represented by the current schema."""


class ShareService:
    """Coordinate file access, workspace roles, and share-table transactions."""

    def __init__(
        self,
        repository: ShareRepository,
        file_service: FileService,
        folder_service: FolderService,
        workspace_service: WorkspaceService,
        user_service: UserService,
    ) -> None:
        self._repository = repository
        self._file_service = file_service
        self._folder_service = folder_service
        self._workspace_service = workspace_service
        self._user_service = user_service

    def create_share(self, actor_id: int, payload: ShareCreateRequest) -> FileShare:
        """Create a schema-compatible file share for an owner or administrator."""
        self._require_owner_or_admin(payload.file_id, actor_id)
        self._validate_create_payload(actor_id, payload)
        if self._repository.get_active_duplicate(
            file_id=payload.file_id,
            share_type=payload.share_type,
            shared_with=payload.shared_with,
        ):
            raise ShareConflictError("An active share with the same recipient scope already exists")

        values: dict[str, Any] = {
            "file_id": payload.file_id,
            "shared_by": actor_id,
            "shared_with": payload.shared_with,
            "share_type": payload.share_type,
            "permission": payload.permission,
            "share_link": self._new_share_link() if payload.share_type == "LINK" else None,
            "password_hash": (
                PASSWORD_CONTEXT.hash(payload.link_password)
                if payload.link_password is not None
                else None
            ),
            "expires_at": payload.expires_at,
        }
        try:
            share_id = self._repository.create(values)
            self._repository.commit()
        except IntegrityError as error:
            self._repository.rollback()
            raise ShareConflictError("An equivalent active share or share link already exists") from error
        except Exception:
            self._repository.rollback()
            raise
        share = self._repository.get_by_id(share_id)
        if share is None:
            raise RuntimeError("Created share could not be loaded")
        return share

    def list_shares(self, actor_id: int) -> list[FileShare]:
        """List shares created by the caller that they can still administer."""
        shares: list[FileShare] = []
        for share in self._repository.list_by_sharer(actor_id):
            try:
                self._require_owner_or_admin(share.file_id, actor_id)
            except (ShareNotFoundError, SharePermissionError):
                continue
            shares.append(share)
        return shares

    def get_share(self, share_id: int, actor_id: int) -> FileShare:
        """Return a share if the caller can administer its underlying file."""
        share = self._require_share(share_id)
        self._require_owner_or_admin(share.file_id, actor_id)
        return share

    def update_share(
        self, share_id: int, actor_id: int, payload: ShareUpdateRequest
    ) -> FileShare:
        """Update permission, expiry, or link-password controls for a share."""
        share = self.get_share(share_id, actor_id)
        changes = self._update_changes(share, payload)
        if not changes:
            return share
        try:
            if not self._repository.update(share_id, changes):
                raise ShareNotFoundError
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        updated_share = self._repository.get_by_id(share_id)
        if updated_share is None:
            raise RuntimeError("Updated share could not be loaded")
        return updated_share

    def delete_share(self, share_id: int, actor_id: int) -> None:
        """Permanently remove a share record at an authorized user's request."""
        share = self.get_share(share_id, actor_id)
        try:
            if not self._repository.delete(share.share_id):
                raise ShareNotFoundError
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise

    def revoke_share(self, share_id: int, actor_id: int) -> None:
        """Idempotently revoke a share; an already-revoked record is a success."""
        share = self._repository.get_by_id(share_id)
        if share is None:
            return
        self._require_owner_or_admin(share.file_id, actor_id)
        try:
            self._repository.delete(share_id)
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise

    def _require_share(self, share_id: int) -> FileShare:
        share = self._repository.get_by_id(share_id)
        if share is None:
            raise ShareNotFoundError
        return share

    def _require_owner_or_admin(self, file_id: int, actor_id: int) -> FileRecord:
        try:
            file = self._file_service.get_file(file_id, actor_id)
            folder = self._folder_service.get_folder(file.folder_id, actor_id)
        except FileNotFoundError as error:
            raise ShareNotFoundError("File not found") from error
        except (FilePermissionError, FolderPermissionError) as error:
            raise SharePermissionError from error
        except FolderNotFoundError as error:
            raise ShareNotFoundError("Folder not found") from error
        try:
            workspace = self._workspace_service.get_workspace(folder.workspace_id, actor_id)
        except WorkspaceNotFoundError as error:
            raise ShareNotFoundError("Workspace not found") from error
        except WorkspacePermissionError as error:
            raise SharePermissionError from error
        if workspace.member_role not in {"OWNER", "ADMIN"}:
            raise SharePermissionError
        return file

    def _validate_create_payload(self, actor_id: int, payload: ShareCreateRequest) -> None:
        if payload.share_type == "PRIVATE":
            if payload.shared_with is None:
                raise ShareValidationError("PRIVATE shares require shared_with")
            if payload.shared_with == actor_id:
                raise ShareValidationError("A file cannot be privately shared with its owner")
            if payload.link_password is not None:
                raise ShareValidationError("Only LINK shares can have a link password")
            self._ensure_active_user(payload.shared_with)
            return
        if payload.shared_with is not None:
            raise ShareValidationError("PUBLIC and LINK shares cannot specify shared_with")
        if payload.share_type == "PUBLIC" and payload.link_password is not None:
            raise ShareValidationError("Only LINK shares can have a link password")

    def _update_changes(
        self, share: FileShare, payload: ShareUpdateRequest
    ) -> dict[str, Any]:
        changes = payload.model_dump(exclude_unset=True)
        if "link_password" in changes:
            if share.share_type != "LINK":
                raise ShareValidationError("Only LINK shares can have a link password")
            password = changes.pop("link_password")
            changes["password_hash"] = (
                PASSWORD_CONTEXT.hash(password) if password is not None else None
            )
        return {
            field_name: value
            for field_name, value in changes.items()
            if value != getattr(share, field_name)
        }

    def _ensure_active_user(self, user_id: int) -> None:
        try:
            self._user_service.get_user(user_id)
        except UserNotFoundError as error:
            raise ShareNotFoundError("Share recipient not found") from error

    def _new_share_link(self) -> str:
        for _ in range(5):
            share_link = secrets.token_urlsafe(32)
            if self._repository.get_by_link(share_link) is None:
                return share_link
        raise ShareConflictError("Unable to allocate a unique share link")
