"""JWT-protected HTTP endpoints for workspace folders."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.api.routes.users import get_current_auth_user
from app.api.routes.workspaces import get_workspace_service
from app.database.session import get_db
from app.repositories.auth_repository import AuthUser
from app.repositories.folder_repository import Folder, FolderRepository
from app.schemas.folder import (
    FolderCreateRequest,
    FolderMoveRequest,
    FolderResponse,
    FolderTreeResponse,
    FolderUpdateRequest,
)
from app.services.folder_service import (
    FolderConflictError,
    FolderNotFoundError,
    FolderPermissionError,
    FolderService,
)
from app.services.workspace_service import WorkspaceService

router = APIRouter(tags=["folders"])
FolderId = Annotated[int, Path(gt=0)]
WorkspaceId = Annotated[int, Path(gt=0)]


def get_folder_service(
    db: Annotated[Session, Depends(get_db)],
    workspace_service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> FolderService:
    """Build the request-scoped folder service using existing workspace DI."""
    return FolderService(FolderRepository(db), workspace_service)


@router.post(
    "/folders",
    response_model=FolderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a folder",
)
def create_folder(
    payload: FolderCreateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderResponse:
    """Create a root folder or a child folder in an accessible workspace."""
    try:
        folder = service.create_folder(current_user.user_id, payload)
    except (FolderNotFoundError, FolderPermissionError, FolderConflictError) as error:
        raise _folder_http_exception(error) from error
    return _folder_response(folder)


@router.get(
    "/workspaces/{workspace_id}/folders",
    response_model=list[FolderResponse],
    summary="List workspace folders",
)
def list_folders(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FolderService, Depends(get_folder_service)],
    include_archived: Annotated[bool, Query()] = False,
) -> list[FolderResponse]:
    """List folders in an accessible workspace."""
    try:
        folders = service.list_folders(
            workspace_id, current_user.user_id, include_archived=include_archived
        )
    except (FolderNotFoundError, FolderPermissionError) as error:
        raise _folder_http_exception(error) from error
    return [_folder_response(folder) for folder in folders]


@router.get(
    "/workspaces/{workspace_id}/tree",
    response_model=list[FolderTreeResponse],
    summary="Get workspace folder tree",
)
def get_tree(
    workspace_id: WorkspaceId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FolderService, Depends(get_folder_service)],
) -> list[FolderTreeResponse]:
    """Return active folders as a nested parent-child hierarchy."""
    try:
        return service.get_tree(workspace_id, current_user.user_id)
    except (FolderNotFoundError, FolderPermissionError) as error:
        raise _folder_http_exception(error) from error


@router.get("/folders/{folder_id}", response_model=FolderResponse, summary="Get a folder")
def get_folder(
    folder_id: FolderId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderResponse:
    """Return an active folder accessible to the current workspace member."""
    try:
        folder = service.get_folder(folder_id, current_user.user_id)
    except (FolderNotFoundError, FolderPermissionError) as error:
        raise _folder_http_exception(error) from error
    return _folder_response(folder)


@router.put("/folders/{folder_id}", response_model=FolderResponse, summary="Update a folder")
def update_folder(
    folder_id: FolderId,
    payload: FolderUpdateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderResponse:
    """Update editable properties of a folder the caller can manage."""
    try:
        folder = service.update_folder(folder_id, current_user.user_id, payload)
    except (FolderNotFoundError, FolderPermissionError, FolderConflictError) as error:
        raise _folder_http_exception(error) from error
    return _folder_response(folder)


@router.post(
    "/folders/{folder_id}/move",
    response_model=FolderResponse,
    summary="Move a folder",
)
def move_folder(
    folder_id: FolderId,
    payload: FolderMoveRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderResponse:
    """Move a folder to a new active parent or the workspace root."""
    try:
        folder = service.move_folder(folder_id, current_user.user_id, payload)
    except (FolderNotFoundError, FolderPermissionError, FolderConflictError) as error:
        raise _folder_http_exception(error) from error
    return _folder_response(folder)


@router.delete(
    "/folders/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Soft-delete a folder",
)
def delete_folder(
    folder_id: FolderId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FolderService, Depends(get_folder_service)],
) -> Response:
    """Archive a managed folder subtree using the existing archive flag."""
    try:
        service.delete_folder(folder_id, current_user.user_id)
    except (FolderNotFoundError, FolderPermissionError, FolderConflictError) as error:
        raise _folder_http_exception(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/folders/{folder_id}/restore",
    response_model=FolderResponse,
    summary="Restore a folder",
)
def restore_folder(
    folder_id: FolderId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderResponse:
    """Restore an archived folder subtree when its parent is active."""
    try:
        folder = service.restore_folder(folder_id, current_user.user_id)
    except (FolderNotFoundError, FolderPermissionError, FolderConflictError) as error:
        raise _folder_http_exception(error) from error
    return _folder_response(folder)


def _folder_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, FolderNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error) or "Folder not found")
    if isinstance(error, FolderPermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Folder permission denied")
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error) or "Folder state conflict")


def _folder_response(folder: Folder) -> FolderResponse:
    return FolderResponse(
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
