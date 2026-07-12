"""Tests for the exceptions module."""

from core.exceptions import (
    AlreadyExistsError,
    InsufficientPermissionsError,
    InvalidCredentialsError,
    NotFoundError,
    PlatformError,
    TokenExpiredError,
)


def test_platform_error():
    e = PlatformError("something broke", detail={"code": 42})
    assert str(e) == "something broke"
    assert e.message == "something broke"
    assert e.detail == {"code": 42}


def test_not_found_error():
    e = NotFoundError("User", "abc-123")
    assert "User" in e.message
    assert "abc-123" in e.message


def test_not_found_error_no_id():
    e = NotFoundError("Dataset")
    assert e.message == "Dataset not found"


def test_already_exists_error():
    e = AlreadyExistsError("Organization", "acme")
    assert "Organization" in e.message
    assert "acme" in e.message


def test_insufficient_permissions():
    e = InsufficientPermissionsError("delete", "pipeline")
    assert "delete" in e.message
    assert "pipeline" in e.message


def test_insufficient_permissions_generic():
    e = InsufficientPermissionsError()
    assert e.message == "Insufficient permissions"


def test_invalid_credentials():
    e = InvalidCredentialsError()
    assert e.message == "Invalid credentials"


def test_token_expired():
    e = TokenExpiredError()
    assert e.message == "Token has expired"
