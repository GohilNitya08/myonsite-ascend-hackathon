"""JWT-protected HTTP endpoints for file metadata and version operations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.api.routes.folders import get_folder_service
from app.api.routes.users import get_current_auth_user
from app.api.routes.workspaces import get_workspace_service
from app.database.session import get_db
from app.repositories.auth_repository import AuthUser
from app.repositories.file_repository import FileRecord, FileRepository, FileVersion
from app.schemas.file import (
    FileCreateRequest,
    FileResponse,
    FileUpdateRequest,
    FileVersionCreateRequest,
    FileVersionResponse,
)
from app.services.file_service import (
    FileConflictError,
    FileNotFoundError,
    FilePermissionError,
    FileService,
)
from app.services.folder_service import FolderService
from app.services.workspace_service import WorkspaceService

router = APIRouter(tags=["files"])
FileId = Annotated[int, Path(gt=0)]
FolderId = Annotated[int, Path(gt=0)]


def get_file_service(
    db: Annotated[Session, Depends(get_db)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
    workspace_service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> FileService:
    """Build the request-scoped file service from existing dependency providers."""
    return FileService(FileRepository(db), folder_service, workspace_service)


@router.post(
    "/files",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create file upload metadata",
)
def create_file(
    payload: FileCreateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileResponse:
    """Store metadata for a file uploaded into a writable folder."""
    try:
        file = service.create_file(current_user.user_id, payload)
    except (FileNotFoundError, FilePermissionError, FileConflictError) as error:
        raise _file_http_exception(error) from error
    return _file_response(file)


@router.get(
    "/folders/{folder_id}/files",
    response_model=list[FileResponse],
    summary="List folder files",
)
def list_files(
    folder_id: FolderId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
    include_deleted: Annotated[bool, Query()] = False,
) -> list[FileResponse]:
    """List files in a readable folder with caller-specific favorite state."""
    try:
        files = service.list_files(
            folder_id, current_user.user_id, include_deleted=include_deleted
        )
    except (FileNotFoundError, FilePermissionError) as error:
        raise _file_http_exception(error) from error
    return [_file_response(file) for file in files]


@router.get("/files/{file_id}", response_model=FileResponse, summary="Get a file")
def get_file(
    file_id: FileId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileResponse:
    """Return non-deleted file metadata to an authorized workspace member."""
    try:
        file = service.get_file(file_id, current_user.user_id)
    except (FileNotFoundError, FilePermissionError) as error:
        raise _file_http_exception(error) from error
    return _file_response(file)


@router.put("/files/{file_id}", response_model=FileResponse, summary="Update file metadata")
def update_file(
    file_id: FileId,
    payload: FileUpdateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileResponse:
    """Rename or update metadata for a file the caller can manage."""
    try:
        file = service.update_file(file_id, current_user.user_id, payload)
    except (FileNotFoundError, FilePermissionError, FileConflictError) as error:
        raise _file_http_exception(error) from error
    return _file_response(file)


@router.delete(
    "/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Soft-delete a file",
)
def delete_file(
    file_id: FileId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> Response:
    """Set the existing file soft-delete flag."""
    try:
        service.delete_file(file_id, current_user.user_id)
    except (FileNotFoundError, FilePermissionError) as error:
        raise _file_http_exception(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/files/{file_id}/restore",
    response_model=FileResponse,
    summary="Restore a file",
)
def restore_file(
    file_id: FileId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileResponse:
    """Restore a soft-deleted file in an active folder."""
    try:
        file = service.restore_file(file_id, current_user.user_id)
    except (FileNotFoundError, FilePermissionError, FileConflictError) as error:
        raise _file_http_exception(error) from error
    return _file_response(file)


@router.get(
    "/files/{file_id}/versions",
    response_model=list[FileVersionResponse],
    summary="List file versions",
)
def list_versions(
    file_id: FileId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> list[FileVersionResponse]:
    """List version metadata for a readable non-deleted file."""
    try:
        versions = service.list_versions(file_id, current_user.user_id)
    except (FileNotFoundError, FilePermissionError) as error:
        raise _file_http_exception(error) from error
    return [_version_response(version) for version in versions]


@router.post(
    "/files/{file_id}/versions",
    response_model=FileVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create file version metadata",
)
def create_version(
    file_id: FileId,
    payload: FileVersionCreateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileVersionResponse:
    """Create the next sequential version record for a managed file."""
    try:
        version = service.create_version(file_id, current_user.user_id, payload)
    except (FileNotFoundError, FilePermissionError, FileConflictError) as error:
        raise _file_http_exception(error) from error
    return _version_response(version)


@router.post(
    "/files/{file_id}/favorite",
    response_model=FileResponse,
    summary="Favorite a file",
)
def favorite_file(
    file_id: FileId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileResponse:
    """Add the current user's favorite record for a readable file."""
    try:
        file = service.favorite_file(file_id, current_user.user_id)
    except (FileNotFoundError, FilePermissionError, FileConflictError) as error:
        raise _file_http_exception(error) from error
    return _file_response(file)


@router.delete(
    "/files/{file_id}/favorite",
    response_model=FileResponse,
    summary="Unfavorite a file",
)
def unfavorite_file(
    file_id: FileId,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileResponse:
    """Remove the current user's favorite record for a readable file."""
    try:
        file = service.unfavorite_file(file_id, current_user.user_id)
    except (FileNotFoundError, FilePermissionError, FileConflictError) as error:
        raise _file_http_exception(error) from error
    return _file_response(file)


def _file_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error) or "File not found")
    if isinstance(error, FilePermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="File permission denied")
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error) or "File state conflict")


def _file_response(file: FileRecord) -> FileResponse:
    return FileResponse(
        file_id=file.file_id,
        folder_id=file.folder_id,
        uploaded_by=file.uploaded_by,
        file_name=file.file_name,
        original_file_name=file.original_file_name,
        file_extension=file.file_extension,
        mime_type=file.mime_type,
        file_size=file.file_size,
        storage_path=file.storage_path,
        file_hash=file.file_hash,
        ai_enabled=file.ai_enabled,
        is_archived=file.is_archived,
        is_deleted=file.is_deleted,
        is_favorite=file.is_favorite,
        created_at=file.created_at,
        updated_at=file.updated_at,
    )


def _version_response(version: FileVersion) -> FileVersionResponse:
    return FileVersionResponse(
        version_id=version.version_id,
        file_id=version.file_id,
        version_number=version.version_number,
        storage_path=version.storage_path,
        file_size=version.file_size,
        file_hash=version.file_hash,
        uploaded_by=version.uploaded_by,
        version_note=version.version_note,
        created_at=version.created_at,
    )
