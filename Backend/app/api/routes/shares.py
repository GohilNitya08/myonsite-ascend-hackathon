"""JWT-protected HTTP endpoints for file sharing."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from app.api.routes.files import get_file_service
from app.api.routes.folders import get_folder_service
from app.api.routes.users import get_current_auth_user, get_user_service
from app.api.routes.workspaces import get_workspace_service
from app.database.session import get_db
from app.repositories.auth_repository import AuthUser
from app.repositories.share_repository import FileShare, ShareRepository
from app.schemas.share import ShareCreateRequest, ShareResponse, ShareUpdateRequest
from app.services.file_service import FileService
from app.services.folder_service import FolderService
from app.services.share_service import (
    ShareConflictError,
    ShareNotFoundError,
    SharePermissionError,
    ShareService,
    ShareValidationError,
)
from app.services.user_service import UserService
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/shares", tags=["shares"])
ShareId = Annotated[int, Path(gt=0)]


def get_share_service(
    db: Annotated[Session, Depends(get_db)],
    file_service: Annotated[FileService, Depends(get_file_service)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
    workspace_service: Annotated[WorkspaceService, Depends(get_workspace_service)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> ShareService:
    """Build a request-scoped sharing service from existing providers."""
    return ShareService(
        ShareRepository(db),
        file_service,
        folder_service,
        workspace_service,
        user_service,
    )


@router.post("", response_model=ShareResponse, status_code=status.HTTP_201_CREATED, summary="Create a file share")
def create_share(
    payload: ShareCreateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> ShareResponse:
    try:
        share = service.create_share(current_user.user_id, payload)
    except (ShareNotFoundError, SharePermissionError, ShareConflictError, ShareValidationError) as error:
        raise _share_http_exception(error) from error
    return _share_response(share)


@router.get("", response_model=list[ShareResponse], summary="List available file shares")
def list_shares(
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> list[ShareResponse]:
    return [_share_response(share) for share in service.list_shares(current_user.user_id)]


@router.get("/{share_id}", response_model=ShareResponse, summary="Get a file share")
def get_share(
    share_id: ShareId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> ShareResponse:
    try:
        share = service.get_share(share_id, current_user.user_id)
    except (ShareNotFoundError, SharePermissionError) as error:
        raise _share_http_exception(error) from error
    return _share_response(share)


@router.put("/{share_id}", response_model=ShareResponse, summary="Update a file share")
def update_share(
    share_id: ShareId,
    payload: ShareUpdateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> ShareResponse:
    try:
        share = service.update_share(share_id, current_user.user_id, payload)
    except (ShareNotFoundError, SharePermissionError, ShareConflictError, ShareValidationError) as error:
        raise _share_http_exception(error) from error
    return _share_response(share)


@router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, summary="Delete a file share")
def delete_share(
    share_id: ShareId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> Response:
    try:
        service.delete_share(share_id, current_user.user_id)
    except (ShareNotFoundError, SharePermissionError) as error:
        raise _share_http_exception(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{share_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Revoke a file share",
)
def revoke_share(
    share_id: ShareId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> Response:
    """Delete the share idempotently because the schema has no revoke-status column."""
    try:
        service.revoke_share(share_id, current_user.user_id)
    except (ShareNotFoundError, SharePermissionError) as error:
        raise _share_http_exception(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _share_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, ShareNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error) or "Share not found")
    if isinstance(error, SharePermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Share permission denied")
    if isinstance(error, ShareValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error) or "Share state conflict")


def _share_response(share: FileShare) -> ShareResponse:
    return ShareResponse(
        share_id=share.share_id,
        file_id=share.file_id,
        shared_by=share.shared_by,
        shared_with=share.shared_with,
        share_type=share.share_type,
        permission=share.permission,
        share_link=share.share_link,
        password_protected=share.password_hash is not None,
        expires_at=share.expires_at,
        created_at=share.created_at,
    )
