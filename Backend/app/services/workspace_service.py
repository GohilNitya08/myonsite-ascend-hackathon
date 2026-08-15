"""Business rules for workspace lifecycle, membership, and operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import (
    Workspace,
    WorkspaceActivity,
    WorkspaceMember,
    WorkspaceRepository,
)
from app.schemas.workspace import (
    WorkspaceCreateRequest,
    WorkspaceInvitationRequest,
    WorkspaceMemberUpdateRequest,
    WorkspaceStorageUpdateRequest,
    WorkspaceUpdateRequest,
)


class WorkspaceError(Exception):
    """Base class for expected workspace-domain failures."""


class WorkspaceNotFoundError(WorkspaceError):
    """Raised when a requested workspace does not exist."""


class WorkspacePermissionError(WorkspaceError):
    """Raised when a member lacks the required workspace role."""


class WorkspaceConflictError(WorkspaceError):
    """Raised when a valid request conflicts with workspace state."""


class WorkspaceService:
    """Coordinate workspace repositories, authorization, and transactions."""

    def __init__(
        self, repository: WorkspaceRepository, user_repository: UserRepository
    ) -> None:
        self._repository = repository
        self._user_repository = user_repository

    def create_workspace(self, owner_id: int, payload: WorkspaceCreateRequest) -> Workspace:
        """Create a workspace and its required OWNER membership atomically."""
        values = payload.model_dump()
        values["user_id"] = owner_id
        try:
            workspace_id = self._repository.create_workspace(values)
            self._repository.add_member(
                workspace_id=workspace_id,
                user_id=owner_id,
                role="OWNER",
                invited_by=None,
            )
            self._repository.record_activity(
                workspace_id=workspace_id,
                user_id=owner_id,
                activity_type="WORKSPACE_CREATED",
                detail="Workspace created",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        workspace = self._repository.get_by_id(workspace_id)
        if workspace is None:
            raise RuntimeError("Created workspace could not be loaded")
        return self._with_role(workspace, "OWNER")

    def list_workspaces(self, user_id: int, *, include_archived: bool) -> list[Workspace]:
        """List workspaces in which the caller is an owner or member."""
        return self._repository.list_for_user(user_id, include_archived=include_archived)

    def get_workspace(self, workspace_id: int, user_id: int) -> Workspace:
        """Return a workspace only when the caller is a current member."""
        workspace, role = self._require_access(workspace_id, user_id)
        return self._with_role(workspace, role)

    def update_workspace(
        self, workspace_id: int, actor_id: int, payload: WorkspaceUpdateRequest
    ) -> Workspace:
        """Update workspace settings for an owner or administrator."""
        workspace, role = self._require_manager(workspace_id, actor_id)
        changes = {
            field_name: value
            for field_name, value in payload.model_dump(exclude_unset=True).items()
            if value != getattr(workspace, field_name)
        }
        if not changes:
            return self._with_role(workspace, role)
        try:
            if not self._repository.update_settings(workspace_id, changes):
                raise WorkspaceNotFoundError
            self._repository.record_activity(
                workspace_id=workspace_id,
                user_id=actor_id,
                activity_type="WORKSPACE_UPDATED",
                detail="Workspace settings updated",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_workspace(workspace_id, actor_id)

    def delete_workspace(self, workspace_id: int, actor_id: int) -> None:
        """Permanently delete a workspace when requested by its owner."""
        self._require_owner(workspace_id, actor_id)
        try:
            self._repository.record_activity(
                workspace_id=workspace_id,
                user_id=actor_id,
                activity_type="WORKSPACE_DELETED",
                detail="Workspace deleted",
            )
            if not self._repository.delete_workspace(workspace_id):
                raise WorkspaceNotFoundError
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise

    def get_members(self, workspace_id: int, actor_id: int) -> list[WorkspaceMember]:
        """List members of a workspace available to the caller."""
        self._require_access(workspace_id, actor_id)
        return self._repository.list_members(workspace_id)

    def invite_member(
        self, workspace_id: int, actor_id: int, payload: WorkspaceInvitationRequest
    ) -> WorkspaceMember:
        """Add an active user as an immediate workspace member."""
        _, actor_role = self._require_manager(workspace_id, actor_id)
        if payload.role == "OWNER":
            raise WorkspaceConflictError("Use ownership transfer to assign the OWNER role")
        if actor_role != "OWNER" and payload.role == "ADMIN":
            raise WorkspacePermissionError
        if self._user_repository.get_active_by_id(payload.user_id) is None:
            raise WorkspaceNotFoundError("Invited user was not found")
        if self._repository.get_membership(workspace_id, payload.user_id) is not None:
            raise WorkspaceConflictError("User is already a workspace member")
        try:
            member_id = self._repository.add_member(
                workspace_id=workspace_id,
                user_id=payload.user_id,
                role=payload.role,
                invited_by=actor_id,
            )
            self._repository.record_activity(
                workspace_id=workspace_id,
                user_id=actor_id,
                activity_type="WORKSPACE_MEMBER_INVITED",
                detail=f"User {payload.user_id} added as {payload.role}",
            )
            self._repository.commit()
        except IntegrityError as error:
            self._repository.rollback()
            raise WorkspaceConflictError("User is already a workspace member") from error
        except Exception:
            self._repository.rollback()
            raise

        member = self._repository.get_membership(workspace_id, payload.user_id)
        if member is None or member.member_id != member_id:
            raise RuntimeError("Created workspace membership could not be loaded")
        return member

    def update_member(
        self,
        workspace_id: int,
        actor_id: int,
        member_user_id: int,
        payload: WorkspaceMemberUpdateRequest,
    ) -> WorkspaceMember:
        """Change a non-owner member's role according to role-management rules."""
        _, actor_role = self._require_manager(workspace_id, actor_id)
        member = self._repository.get_membership(workspace_id, member_user_id)
        if member is None:
            raise WorkspaceNotFoundError("Workspace member was not found")
        if member.role == "OWNER" or payload.role == "OWNER":
            raise WorkspaceConflictError("Use ownership transfer to change the OWNER role")
        if member_user_id == actor_id:
            raise WorkspaceConflictError("Members cannot change their own role")
        if actor_role != "OWNER" and (member.role == "ADMIN" or payload.role == "ADMIN"):
            raise WorkspacePermissionError
        if member.role == payload.role:
            return member
        try:
            if not self._repository.update_member_role(workspace_id, member_user_id, payload.role):
                raise WorkspaceNotFoundError("Workspace member was not found")
            self._repository.record_activity(
                workspace_id=workspace_id,
                user_id=actor_id,
                activity_type="WORKSPACE_MEMBER_ROLE_UPDATED",
                detail=f"User {member_user_id} role changed to {payload.role}",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        updated_member = self._repository.get_membership(workspace_id, member_user_id)
        if updated_member is None:
            raise RuntimeError("Updated workspace membership could not be loaded")
        return updated_member

    def remove_member(self, workspace_id: int, actor_id: int, member_user_id: int) -> None:
        """Remove a member, or allow a non-owner to leave a workspace."""
        _, actor_role = self._require_access(workspace_id, actor_id)
        member = self._repository.get_membership(workspace_id, member_user_id)
        if member is None:
            raise WorkspaceNotFoundError("Workspace member was not found")
        if member.role == "OWNER":
            raise WorkspaceConflictError("Transfer ownership before removing the owner")
        if member_user_id != actor_id:
            if actor_role not in {"OWNER", "ADMIN"}:
                raise WorkspacePermissionError
            if actor_role != "OWNER" and member.role == "ADMIN":
                raise WorkspacePermissionError
        try:
            if not self._repository.remove_member(workspace_id, member_user_id):
                raise WorkspaceNotFoundError("Workspace member was not found")
            self._repository.record_activity(
                workspace_id=workspace_id,
                user_id=actor_id,
                activity_type="WORKSPACE_MEMBER_REMOVED",
                detail=f"User {member_user_id} removed from workspace",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise

    def get_settings(self, workspace_id: int, actor_id: int) -> Workspace:
        """Return workspace settings to an authorized member."""
        return self.get_workspace(workspace_id, actor_id)

    def update_storage(
        self, workspace_id: int, actor_id: int, payload: WorkspaceStorageUpdateRequest
    ) -> Workspace:
        """Set a valid workspace storage limit without altering usage."""
        workspace, _ = self._require_manager(workspace_id, actor_id)
        if payload.storage_limit < workspace.storage_used:
            raise WorkspaceConflictError("Storage limit cannot be lower than storage used")
        if payload.storage_limit == workspace.storage_limit:
            return self._with_role(workspace, self._membership_role(workspace, actor_id))
        try:
            if not self._repository.update_storage_limit(workspace_id, payload.storage_limit):
                raise WorkspaceNotFoundError
            self._repository.record_activity(
                workspace_id=workspace_id,
                user_id=actor_id,
                activity_type="WORKSPACE_STORAGE_LIMIT_UPDATED",
                detail=f"Storage limit set to {payload.storage_limit}",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_workspace(workspace_id, actor_id)

    def get_activity(
        self, workspace_id: int, actor_id: int, *, limit: int
    ) -> list[WorkspaceActivity]:
        """Return module-recorded activity to an authorized workspace member."""
        self._require_access(workspace_id, actor_id)
        return self._repository.list_activity(workspace_id, limit=limit)

    def set_archived(self, workspace_id: int, actor_id: int, *, is_archived: bool) -> Workspace:
        """Archive or restore a workspace for an owner or administrator."""
        workspace, role = self._require_manager(workspace_id, actor_id)
        if workspace.is_archived == is_archived:
            return self._with_role(workspace, role)
        action = "WORKSPACE_ARCHIVED" if is_archived else "WORKSPACE_RESTORED"
        detail = "Workspace archived" if is_archived else "Workspace restored"
        try:
            if not self._repository.set_archived(workspace_id, is_archived=is_archived):
                raise WorkspaceNotFoundError
            self._repository.record_activity(
                workspace_id=workspace_id,
                user_id=actor_id,
                activity_type=action,
                detail=detail,
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_workspace(workspace_id, actor_id)

    def transfer_ownership(self, workspace_id: int, actor_id: int, new_owner_id: int) -> Workspace:
        """Transfer workspace ownership to an existing active member."""
        self._require_owner(workspace_id, actor_id)
        if new_owner_id == actor_id:
            raise WorkspaceConflictError("The current owner is already the workspace owner")
        new_owner_membership = self._repository.get_membership(workspace_id, new_owner_id)
        if new_owner_membership is None:
            raise WorkspaceConflictError("New owner must already be a workspace member")
        if self._user_repository.get_active_by_id(new_owner_id) is None:
            raise WorkspaceNotFoundError("New owner was not found")
        try:
            if not self._repository.transfer_ownership(
                workspace_id=workspace_id,
                previous_owner_id=actor_id,
                new_owner_id=new_owner_id,
            ):
                raise WorkspaceNotFoundError
            self._repository.record_activity(
                workspace_id=workspace_id,
                user_id=actor_id,
                activity_type="WORKSPACE_OWNERSHIP_TRANSFERRED",
                detail=f"Ownership transferred to user {new_owner_id}",
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return self.get_workspace(workspace_id, new_owner_id)

    def _require_access(self, workspace_id: int, user_id: int) -> tuple[Workspace, str]:
        workspace = self._repository.get_by_id(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError
        return workspace, self._membership_role(workspace, user_id)

    def _require_manager(self, workspace_id: int, user_id: int) -> tuple[Workspace, str]:
        workspace, role = self._require_access(workspace_id, user_id)
        if role not in {"OWNER", "ADMIN"}:
            raise WorkspacePermissionError
        return workspace, role

    def _require_owner(self, workspace_id: int, user_id: int) -> Workspace:
        workspace, role = self._require_access(workspace_id, user_id)
        if role != "OWNER":
            raise WorkspacePermissionError
        return workspace

    def _membership_role(self, workspace: Workspace, user_id: int) -> str:
        membership = self._repository.get_membership(workspace.workspace_id, user_id)
        if membership is not None:
            return membership.role
        if workspace.user_id == user_id:
            return "OWNER"
        raise WorkspacePermissionError

    @staticmethod
    def _with_role(workspace: Workspace, role: str) -> Workspace:
        return Workspace(
            workspace_id=workspace.workspace_id,
            user_id=workspace.user_id,
            workspace_name=workspace.workspace_name,
            description=workspace.description,
            workspace_type=workspace.workspace_type,
            visibility=workspace.visibility,
            storage_used=workspace.storage_used,
            storage_limit=workspace.storage_limit,
            color=workspace.color,
            is_archived=workspace.is_archived,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
            member_role=role,
        )
