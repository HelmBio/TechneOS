"""Shared exception hierarchy for the platform."""

from typing import Any


class PlatformError(Exception):
    """Base exception for all platform errors."""

    def __init__(self, message: str, detail: Any = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)


# --- Authentication / Authorization ---


class AuthError(PlatformError):
    """Base authentication/authorization error."""


class InvalidCredentialsError(AuthError):
    """Invalid username or password."""

    def __init__(self) -> None:
        super().__init__("Invalid credentials")


class AccountInactiveError(AuthError):
    """The account exists but is inactive (e.g. awaiting administrator approval)."""

    def __init__(self) -> None:
        super().__init__("Your account is awaiting administrator approval")


class TokenExpiredError(AuthError):
    """JWT token has expired."""

    def __init__(self) -> None:
        super().__init__("Token has expired")


class InvalidTokenError(AuthError):
    """JWT token is malformed or invalid."""

    def __init__(self, detail: str = "Invalid token") -> None:
        super().__init__(detail)


class InsufficientPermissionsError(AuthError):
    """User lacks the required permissions."""

    def __init__(self, action: str = "", resource: str = "") -> None:
        msg = "Insufficient permissions"
        if action and resource:
            msg = f"Insufficient permissions: cannot {action} {resource}"
        super().__init__(msg)


# --- Resource errors ---


class NotFoundError(PlatformError):
    """Requested resource not found."""

    def __init__(self, resource: str, identifier: str | None = None) -> None:
        msg = f"{resource} not found"
        if identifier:
            msg = f"{resource} '{identifier}' not found"
        super().__init__(msg)


class AlreadyExistsError(PlatformError):
    """Resource already exists (conflict)."""

    def __init__(self, resource: str, identifier: str | None = None) -> None:
        msg = f"{resource} already exists"
        if identifier:
            msg = f"{resource} '{identifier}' already exists"
        super().__init__(msg)


class ValidationError(PlatformError):
    """Request validation failed."""


class ConflictError(PlatformError):
    """Request conflicts with the current state of the resource (HTTP 409).

    Used for things like illegal version-status transitions and attempts to
    edit a version that is locked (active/deprecated or already has runs).
    """


# --- Infrastructure errors ---


class StorageError(PlatformError):
    """Object storage operation failed."""


class DatabaseError(PlatformError):
    """Database operation failed."""
