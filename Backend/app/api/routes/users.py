"""User profile HTTP endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.repositories.auth_repository import AuthRepository, AuthUser
from app.repositories.user_repository import User, UserRepository
from app.schemas.user import CurrentUserResponse, PublicUserResponse, UserUpdateRequest
from app.services.auth_service import (
    AuthService,
    DuplicateEmailError,
    DuplicateUsernameError,
    InactiveAccountError,
    InvalidTokenError,
    UserNotFoundError,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


def get_user_service(db: Annotated[Session, Depends(get_db)]) -> UserService:
    """Build the request-scoped user service."""
    return UserService(UserRepository(db))


def get_current_auth_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> AuthUser:
    """Resolve an active user from the existing access-token implementation."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    auth_service = AuthService(AuthRepository(db))
    try:
        return auth_service._get_active_token_user(
            credentials.credentials, expected_type="access"
        )
    except (InvalidTokenError, UserNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except InactiveAccountError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active",
        ) from error


@router.get("/me", response_model=CurrentUserResponse, summary="Get the current user's profile")
def read_current_user(
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> CurrentUserResponse:
    """Return the profile for the account represented by the access token."""
    return _current_user_response(_get_current_profile(service, current_user.user_id))


@router.put("/me", response_model=CurrentUserResponse, summary="Update the current user's profile")
def update_current_user(
    payload: UserUpdateRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> CurrentUserResponse:
    """Update the authenticated user's editable profile fields."""
    try:
        user = service.update_current_user(current_user.user_id, payload)
    except DuplicateUsernameError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This username is already in use",
        ) from error
    except DuplicateEmailError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from error
    except UserNotFoundError as error:
        raise _user_not_found_exception() from error
    return _current_user_response(user)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete the current user's account",
)
def delete_current_user(
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> Response:
    """Soft-delete the authenticated account while retaining related records."""
    try:
        service.delete_current_user(current_user.user_id)
    except UserNotFoundError as error:
        raise _user_not_found_exception() from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/search",
    response_model=list[PublicUserResponse],
    summary="Search active users",
)
def search_users(
    q: Annotated[str, Query(min_length=1, max_length=100, description="Search term")],
    service: Annotated[UserService, Depends(get_user_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[PublicUserResponse]:
    """Find active accounts by username or full name."""
    try:
        users = service.search_users(q, limit=limit)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    return [_public_user_response(user) for user in users]


@router.get(
    "/{user_id}",
    response_model=PublicUserResponse,
    summary="Get an active user's public profile",
)
def read_user(
    user_id: int,
    service: Annotated[UserService, Depends(get_user_service)],
) -> PublicUserResponse:
    """Return a non-sensitive profile for an active user."""
    if user_id < 1:
        raise _user_not_found_exception()
    try:
        user = service.get_user(user_id)
    except UserNotFoundError as error:
        raise _user_not_found_exception() from error
    return _public_user_response(user)


def _get_current_profile(service: UserService, user_id: int) -> User:
    try:
        return service.get_current_user(user_id)
    except UserNotFoundError as error:
        raise _user_not_found_exception() from error


def _user_not_found_exception() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


def _public_user_response(user: User) -> PublicUserResponse:
    return PublicUserResponse(
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        account_type=user.account_type,
        profile_picture=user.profile_picture,
        bio=user.bio,
        created_at=user.created_at,
    )


def _current_user_response(user: User) -> CurrentUserResponse:
    return CurrentUserResponse(
        **_public_user_response(user).model_dump(),
        email=user.email,
        enrollment_id=user.enrollment_id,
        employee_id=user.employee_id,
        storage_used=user.storage_used,
        storage_limit=user.storage_limit,
        email_verified=user.email_verified,
        two_factor_enabled=user.two_factor_enabled,
        account_status=user.account_status,
        updated_at=user.updated_at,
        last_login=user.last_login,
    )
