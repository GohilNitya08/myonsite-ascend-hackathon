"""Protected HTTP endpoints for workspace lifecycle and collaboration."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.api.routes.users import get_current_auth_user
from app.database.session import get_db
from app.repositories.auth_repository import AuthUser
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import Workspace, WorkspaceActivity, WorkspaceMember, WorkspaceRepository
from app.schemas.workspace import (
    WorkspaceActivityResponse,
    WorkspaceCreateRequest,
    WorkspaceInvitationRequest,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdateRequest,
    WorkspaceOwnershipTransferRequest,
    WorkspaceResponse,
    WorkspaceStorageResponse,
    WorkspaceStorageUpdateRequest,
    WorkspaceUpdateRequest,
)
from app.services.workspace_service import (
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    WorkspacePermissionError,
    WorkspaceService,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
WorkspaceId = Annotated[int, Path(gt=0)]


def get_workspace_service(db: Annotated[Session, Depends(get_db)]) -> WorkspaceService:
    """Build the request-scoped workspace service and its related repositories."""
    return WorkspaceService(WorkspaceRepository(db), UserRepository(db))


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a workspace",
)
def create_workspace(
    payload: WorkspaceCreateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    """Create a workspace and assign the authenticated user as OWNER."""
    return _workspace_response(service.create_workspace(current_user.user_id, payload))


@router.get("", response_model=list[WorkspaceResponse], summary="List my workspaces")
def list_workspaces(
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
    include_archived: Annotated[bool, Query()] = False,
) -> list[WorkspaceResponse]:
    """List workspaces owned by or shared with the authenticated user."""
    return [
        _workspace_response(workspace)
        for workspace in service.list_workspaces(
            current_user.user_id, include_archived=include_archived
        )
    ]


@router.get(
    "/{workspace_id}/members",
    response_model=list[WorkspaceMemberResponse],
    summary="List workspace members",
)
def list_members(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> list[WorkspaceMemberResponse]:
    """List members for a workspace the caller can access."""
    try:
        members = service.get_members(workspace_id, current_user.user_id)
    except (WorkspaceNotFoundError, WorkspacePermissionError) as error:
        raise _workspace_http_exception(error) from error
    return [_member_response(member) for member in members]


@router.post(
    "/{workspace_id}/invitations",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user to a workspace",
)
def invite_member(
    workspace_id: WorkspaceId,
    payload: WorkspaceInvitationRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceMemberResponse:
    """Create an immediate membership using the available schema fields."""
    try:
        member = service.invite_member(workspace_id, current_user.user_id, payload)
    except (WorkspaceNotFoundError, WorkspacePermissionError, WorkspaceConflictError) as error:
        raise _workspace_http_exception(error) from error
    return _member_response(member)


@router.put(
    "/{workspace_id}/members/{member_user_id}",
    response_model=WorkspaceMemberResponse,
    summary="Update a workspace member role",
)
def update_member(
    workspace_id: WorkspaceId,
    member_user_id: Annotated[int, Path(gt=0)],
    payload: WorkspaceMemberUpdateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceMemberResponse:
    """Update a member role without changing workspace ownership."""
    try:
        member = service.update_member(
            workspace_id, current_user.user_id, member_user_id, payload
        )
    except (WorkspaceNotFoundError, WorkspacePermissionError, WorkspaceConflictError) as error:
        raise _workspace_http_exception(error) from error
    return _member_response(member)


@router.delete(
    "/{workspace_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove a workspace member or leave a workspace",
)
def remove_member(
    workspace_id: WorkspaceId,
    member_user_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> Response:
    """Remove a member or permit a non-owner to remove their own membership."""
    try:
        service.remove_member(workspace_id, current_user.user_id, member_user_id)
    except (WorkspaceNotFoundError, WorkspacePermissionError, WorkspaceConflictError) as error:
        raise _workspace_http_exception(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{workspace_id}/settings",
    response_model=WorkspaceResponse,
    summary="Get workspace settings",
)
def get_settings(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    """Return settings for an accessible workspace."""
    try:
        workspace = service.get_settings(workspace_id, current_user.user_id)
    except (WorkspaceNotFoundError, WorkspacePermissionError) as error:
        raise _workspace_http_exception(error) from error
    return _workspace_response(workspace)


@router.put(
    "/{workspace_id}/settings",
    response_model=WorkspaceResponse,
    summary="Update workspace settings",
)
def update_settings(
    workspace_id: WorkspaceId,
    payload: WorkspaceUpdateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    """Update editable settings for an owner or administrator."""
    try:
        workspace = service.update_workspace(workspace_id, current_user.user_id, payload)
    except (WorkspaceNotFoundError, WorkspacePermissionError, WorkspaceConflictError) as error:
        raise _workspace_http_exception(error) from error
    return _workspace_response(workspace)


@router.get(
    "/{workspace_id}/storage",
    response_model=WorkspaceStorageResponse,
    summary="Get workspace storage",
)
def get_storage(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceStorageResponse:
    """Return storage usage and configured limit for an accessible workspace."""
    try:
        workspace = service.get_workspace(workspace_id, current_user.user_id)
    except (WorkspaceNotFoundError, WorkspacePermissionError) as error:
        raise _workspace_http_exception(error) from error
    return _storage_response(workspace)


@router.put(
    "/{workspace_id}/storage",
    response_model=WorkspaceStorageResponse,
    summary="Update workspace storage limit",
)
def update_storage(
    workspace_id: WorkspaceId,
    payload: WorkspaceStorageUpdateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceStorageResponse:
    """Set a storage limit that is not below current usage."""
    try:
        workspace = service.update_storage(workspace_id, current_user.user_id, payload)
    except (WorkspaceNotFoundError, WorkspacePermissionError, WorkspaceConflictError) as error:
        raise _workspace_http_exception(error) from error
    return _storage_response(workspace)


@router.get(
    "/{workspace_id}/activity",
    response_model=list[WorkspaceActivityResponse],
    summary="List workspace activity",
)
def get_activity(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[WorkspaceActivityResponse]:
    """List activity produced by this module for an accessible workspace."""
    try:
        activity = service.get_activity(workspace_id, current_user.user_id, limit=limit)
    except (WorkspaceNotFoundError, WorkspacePermissionError) as error:
        raise _workspace_http_exception(error) from error
    return [_activity_response(item) for item in activity]


@router.post(
    "/{workspace_id}/archive",
    response_model=WorkspaceResponse,
    summary="Archive a workspace",
)
def archive_workspace(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    """Set the schema's archive flag to true."""
    try:
        workspace = service.set_archived(workspace_id, current_user.user_id, is_archived=True)
    except (WorkspaceNotFoundError, WorkspacePermissionError) as error:
        raise _workspace_http_exception(error) from error
    return _workspace_response(workspace)


@router.post(
    "/{workspace_id}/restore",
    response_model=WorkspaceResponse,
    summary="Restore an archived workspace",
)
def restore_workspace(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    """Set the schema's archive flag to false."""
    try:
        workspace = service.set_archived(workspace_id, current_user.user_id, is_archived=False)
    except (WorkspaceNotFoundError, WorkspacePermissionError) as error:
        raise _workspace_http_exception(error) from error
    return _workspace_response(workspace)


@router.post(
    "/{workspace_id}/transfer-ownership",
    response_model=WorkspaceResponse,
    summary="Transfer workspace ownership",
)
def transfer_ownership(
    workspace_id: WorkspaceId,
    payload: WorkspaceOwnershipTransferRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    """Transfer ownership to an existing active member."""
    try:
        workspace = service.transfer_ownership(
            workspace_id, current_user.user_id, payload.user_id
        )
    except (WorkspaceNotFoundError, WorkspacePermissionError, WorkspaceConflictError) as error:
        raise _workspace_http_exception(error) from error
    return _workspace_response(workspace)


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Get a workspace",
)
def get_workspace(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    """Return an accessible workspace."""
    try:
        workspace = service.get_workspace(workspace_id, current_user.user_id)
    except (WorkspaceNotFoundError, WorkspacePermissionError) as error:
        raise _workspace_http_exception(error) from error
    return _workspace_response(workspace)


@router.put(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Update a workspace",
)
def update_workspace(
    workspace_id: WorkspaceId,
    payload: WorkspaceUpdateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    """Update editable workspace settings for an owner or administrator."""
    try:
        workspace = service.update_workspace(workspace_id, current_user.user_id, payload)
    except (WorkspaceNotFoundError, WorkspacePermissionError, WorkspaceConflictError) as error:
        raise _workspace_http_exception(error) from error
    return _workspace_response(workspace)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a workspace",
)
def delete_workspace(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> Response:
    """Permanently delete a workspace when requested by its owner."""
    try:
        service.delete_workspace(workspace_id, current_user.user_id)
    except (WorkspaceNotFoundError, WorkspacePermissionError) as error:
        raise _workspace_http_exception(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _workspace_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, WorkspaceNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error) or "Workspace not found")
    if isinstance(error, WorkspacePermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace permission denied")
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error) or "Workspace state conflict")


def _workspace_response(workspace: Workspace) -> WorkspaceResponse:
    return WorkspaceResponse(
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
        member_role=workspace.member_role,
    )


def _member_response(member: WorkspaceMember) -> WorkspaceMemberResponse:
    return WorkspaceMemberResponse(
        member_id=member.member_id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        role=member.role,
        invited_by=member.invited_by,
        joined_at=member.joined_at,
    )


def _storage_response(workspace: Workspace) -> WorkspaceStorageResponse:
    return WorkspaceStorageResponse(
        workspace_id=workspace.workspace_id,
        storage_used=workspace.storage_used,
        storage_limit=workspace.storage_limit,
    )


def _activity_response(activity: WorkspaceActivity) -> WorkspaceActivityResponse:
    return WorkspaceActivityResponse(
        activity_id=activity.activity_id,
        user_id=activity.user_id,
        activity_type=activity.activity_type,
        activity_description=activity.activity_description,
        created_at=activity.created_at,
    )
