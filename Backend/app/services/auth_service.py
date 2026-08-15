"""Authentication business logic and JWT handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.repositories.auth_repository import AuthRepository, AuthUser

PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthError(Exception):
    """Base class for expected authentication failures."""


class DuplicateEmailError(AuthError):
    """Raised when an email address is already in use."""


class DuplicateUsernameError(AuthError):
    """Raised when a username is already in use."""


class InvalidCredentialsError(AuthError):
    """Raised when login credentials do not authenticate a user."""


class InvalidTokenError(AuthError):
    """Raised when a JWT is malformed, expired, or has the wrong purpose."""


class InactiveAccountError(AuthError):
    """Raised when an operation targets a non-active account."""


class UserNotFoundError(AuthError):
    """Raised when a token references a user that no longer exists."""


@dataclass(frozen=True, slots=True)
class AuthTokens:
    """A JWT access and refresh token pair."""

    access_token: str
    refresh_token: str
    access_token_expires_in: int


@dataclass(frozen=True, slots=True)
class AccessToken:
    """A newly issued access token."""

    access_token: str
    access_token_expires_in: int


class AuthService:
    """Coordinate password authentication, repository access, and token creation."""

    def __init__(self, repository: AuthRepository) -> None:
        self._repository = repository

    def register(
        self,
        *,
        username: str,
        full_name: str,
        email: str,
        password: str,
    ) -> AuthUser:
        """Create a new account with a bcrypt password hash."""
        normalized_email = email.lower()
        if self._repository.get_by_email(normalized_email):
            raise DuplicateEmailError
        if self._repository.get_by_username(username):
            raise DuplicateUsernameError

        try:
            user_id = self._repository.create_user(
                username=username,
                full_name=full_name,
                email=normalized_email,
                password_hash=self._hash_password(password),
            )
            self._repository.commit()
        except IntegrityError:
            self._repository.rollback()
            self._raise_duplicate_after_conflict(email=normalized_email, username=username)
            raise

        user = self._repository.get_by_id(user_id)
        if user is None:
            raise RuntimeError("Created user could not be loaded")
        return user

    def login(self, *, email: str, password: str) -> AuthTokens:
        """Verify credentials, update login metadata, and issue both JWTs."""
        user = self._repository.get_by_email(email.lower())
        if user is None or not user.password_hash:
            raise InvalidCredentialsError
        if not self._verify_password(password, user.password_hash):
            raise InvalidCredentialsError
        self._ensure_active(user)

        self._repository.update_last_login(user.user_id)
        self._repository.commit()
        return self._issue_token_pair(user)

    def refresh_access_token(self, refresh_token: str) -> AccessToken:
        """Validate a refresh token and issue a new access token."""
        user = self._get_active_token_user(refresh_token, expected_type="refresh")
        access_token = self._create_token(
            user,
            token_type="access",
            expires_in_minutes=settings.jwt_access_token_expire_minutes,
        )
        return AccessToken(
            access_token=access_token,
            access_token_expires_in=settings.jwt_access_token_expire_minutes * 60,
        )

    def request_password_reset(self, email: str) -> None:
        """Accept a reset request without revealing whether the account exists.

        Email delivery is intentionally deferred. A future mail workflow will create a
        password-reset JWT and deliver it only for active accounts.
        """
        user = self._repository.get_by_email(email.lower())
        if user is not None and user.account_status == "ACTIVE":
            # Reserved for future email delivery; keep the response identical either way.
            return

    def reset_password(self, *, reset_token: str, new_password: str) -> None:
        """Validate a future-issued reset token and store a new bcrypt hash."""
        user = self._get_active_token_user(reset_token, expected_type="password_reset")
        if not self._repository.update_password_hash(
            user.user_id, self._hash_password(new_password)
        ):
            self._repository.rollback()
            raise UserNotFoundError
        self._repository.commit()

    @staticmethod
    def logout() -> None:
        """Provide a no-op logout hook until token blacklisting is implemented."""
        return None

    def _issue_token_pair(self, user: AuthUser) -> AuthTokens:
        return AuthTokens(
            access_token=self._create_token(
                user,
                token_type="access",
                expires_in_minutes=settings.jwt_access_token_expire_minutes,
            ),
            refresh_token=self._create_token(
                user,
                token_type="refresh",
                expires_in_minutes=settings.jwt_refresh_token_expire_minutes,
            ),
            access_token_expires_in=settings.jwt_access_token_expire_minutes * 60,
        )

    def _get_active_token_user(self, token: str, *, expected_type: str) -> AuthUser:
        claims = self._decode_token(token, expected_type=expected_type)
        subject = claims.get("sub")
        try:
            user_id = int(subject)
        except (TypeError, ValueError) as error:
            raise InvalidTokenError from error
        if user_id < 1:
            raise InvalidTokenError

        user = self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError
        self._ensure_active(user)
        return user

    @staticmethod
    def _hash_password(password: str) -> str:
        return PASSWORD_CONTEXT.hash(password)

    @staticmethod
    def _verify_password(password: str, password_hash: str) -> bool:
        try:
            return PASSWORD_CONTEXT.verify(password, password_hash)
        except ValueError:
            return False

    @staticmethod
    def _ensure_active(user: AuthUser) -> None:
        if user.account_status != "ACTIVE":
            raise InactiveAccountError

    @staticmethod
    def _create_token(
        user: AuthUser,
        *,
        token_type: str,
        expires_in_minutes: int,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user.user_id),
            "email": user.email,
            "token_type": token_type,
            "iat": now,
            "exp": now + timedelta(minutes=expires_in_minutes),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    @staticmethod
    def _decode_token(token: str, *, expected_type: str) -> dict[str, object]:
        try:
            claims = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
        except JWTError as error:
            raise InvalidTokenError from error
        if claims.get("token_type") != expected_type:
            raise InvalidTokenError
        return claims

    def _raise_duplicate_after_conflict(self, *, email: str, username: str) -> None:
        """Translate a race-condition unique-constraint conflict to an API error."""
        if self._repository.get_by_email(email):
            raise DuplicateEmailError
        if self._repository.get_by_username(username):
            raise DuplicateUsernameError
