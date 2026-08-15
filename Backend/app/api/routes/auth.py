"""Authentication HTTP endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.repositories.auth_repository import AuthRepository, AuthUser
from app.schemas.auth import (
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    MessageResponse,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import (
    AccessToken,
    AuthService,
    AuthTokens,
    DuplicateEmailError,
    DuplicateUsernameError,
    InactiveAccountError,
    InvalidCredentialsError,
    InvalidTokenError,
    UserNotFoundError,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    """Build the request-scoped authentication service."""
    return AuthService(AuthRepository(db))


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
def register(
    payload: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Create an account after validating uniqueness and hashing its password."""
    try:
        user = service.register(
            username=payload.username,
            full_name=payload.full_name,
            email=str(payload.email),
            password=payload.password,
        )
    except DuplicateEmailError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from error
    except DuplicateUsernameError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This username is already in use",
        ) from error
    return _user_response(user)


@router.post("/login", response_model=TokenResponse, summary="Log in with email and password")
def login(
    payload: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Authenticate the user and return a JWT access and refresh token pair."""
    try:
        tokens = service.login(email=str(payload.email), password=payload.password)
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except InactiveAccountError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active",
        ) from error
    return _token_response(tokens)


@router.post("/logout", response_model=MessageResponse, summary="Log out the current client")
def logout() -> MessageResponse:
    """Acknowledge logout until a token blacklist or session store is introduced."""
    AuthService.logout()
    return MessageResponse(message="Logged out successfully")


@router.post("/refresh", response_model=TokenResponse, summary="Refresh an access token")
def refresh_access_token(
    payload: RefreshTokenRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Exchange a valid refresh JWT for a new access JWT."""
    try:
        access_token = service.refresh_access_token(payload.refresh_token)
    except (InvalidTokenError, UserNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except InactiveAccountError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active",
        ) from error
    return _access_token_response(access_token)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset",
)
def forgot_password(
    payload: ForgotPasswordRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Accept a password-reset request without disclosing account existence."""
    service.request_password_reset(str(payload.email))
    return MessageResponse(
        message="If an account exists, password reset instructions will be sent."
    )


@router.post("/reset-password", response_model=MessageResponse, summary="Reset a password")
def reset_password(
    payload: ResetPasswordRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Set a new hashed password from a valid password-reset token."""
    try:
        service.reset_password(
            reset_token=payload.reset_token,
            new_password=payload.new_password,
        )
    except (InvalidTokenError, UserNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired password reset token",
        ) from error
    except InactiveAccountError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active",
        ) from error
    return MessageResponse(message="Password reset successfully")


@router.get("/verify-email", response_model=MessageResponse, summary="Verify an email address")
def verify_email(token: Annotated[str | None, Query()] = None) -> MessageResponse:
    """Reserve the email-verification URL until email delivery is integrated."""
    del token
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Email verification is not configured yet",
    )


@router.post("/google", response_model=TokenResponse, summary="Sign in with Google")
def google_auth(payload: GoogleAuthRequest) -> TokenResponse:
    """Reserve Google sign-in until Google OAuth credentials are configured."""
    del payload
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google OAuth is not configured yet",
    )


def _user_response(user: AuthUser) -> UserResponse:
    """Convert the repository user value into the public API response model."""
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        account_type=user.account_type,
        email_verified=user.email_verified,
        created_at=user.created_at,
    )


def _token_response(tokens: AuthTokens) -> TokenResponse:
    """Convert a login token pair into the API response model."""
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_token_expires_in=tokens.access_token_expires_in,
    )


def _access_token_response(token: AccessToken) -> TokenResponse:
    """Convert a refreshed access token into the API response model."""
    return TokenResponse(
        access_token=token.access_token,
        access_token_expires_in=token.access_token_expires_in,
    )
