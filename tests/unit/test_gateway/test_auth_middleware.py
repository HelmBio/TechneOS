"""Tests for the gateway authentication middleware."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gateway.middleware.auth import AUTH_PATHS, PUBLIC_PATHS, AuthMiddleware


@pytest.fixture
def app():
    """Create a minimal FastAPI app with auth middleware for testing."""
    _app = FastAPI()
    _app.add_middleware(AuthMiddleware)

    @_app.get("/health")
    async def health():
        return {"status": "ok"}

    @_app.get("/api/v1/auth/login")
    async def login():
        return {"status": "login"}

    @_app.get("/api/v1/protected")
    async def protected(request: Request):
        return {"user": request.state.user.sub}

    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestPublicPaths:
    """Public paths should bypass auth entirely."""

    def test_health_no_auth_required(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_all_public_paths_defined(self):
        expected = {"/health", "/ready", "/docs", "/redoc", "/openapi.json"}
        assert expected == PUBLIC_PATHS

    def test_all_auth_paths_defined(self):
        assert "/api/v1/auth/login" in AUTH_PATHS
        assert "/api/v1/auth/register" in AUTH_PATHS
        assert "/api/v1/auth/refresh" in AUTH_PATHS


class TestOptionsRequests:
    """OPTIONS requests (CORS preflight) should always pass through."""

    def test_options_no_auth(self, client):
        resp = client.options("/api/v1/protected")
        # FastAPI returns 405 for OPTIONS on GET-only route, but middleware passes it through
        assert resp.status_code != 401


class TestBearerTokenAuth:
    """Bearer token validation via Authorization header."""

    @patch("gateway.middleware.auth.validate_any_token")
    def test_valid_bearer_sets_user(self, mock_validate, client):
        mock_payload = MagicMock()
        mock_payload.sub = "user-123"
        mock_validate.return_value = mock_payload

        resp = client.get(
            "/api/v1/protected",
            headers={"Authorization": "Bearer valid-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["user"] == "user-123"
        mock_validate.assert_called_once_with("valid-token")

    @patch("gateway.middleware.auth.validate_any_token")
    def test_invalid_bearer_returns_401(self, mock_validate, client):
        from core.exceptions import AuthError

        mock_validate.side_effect = AuthError("expired")

        resp = client.get(
            "/api/v1/protected",
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401
        assert "Invalid or expired token" in resp.json()["detail"]

    def test_no_credentials_returns_401(self, client):
        resp = client.get("/api/v1/protected")
        assert resp.status_code == 401
        assert "Not authenticated" in resp.json()["detail"]


class TestApiKeyAuth:
    """API key validation via X-API-Key header."""

    @patch("gateway.middleware.auth.validate_any_token")
    def test_malformed_key_no_techneos_prefix(self, mock_validate, client):
        resp = client.get(
            "/api/v1/protected",
            headers={"X-API-Key": "bad_prefix_secret"},
        )
        assert resp.status_code == 401
        assert "Invalid API key" in resp.json()["detail"]

    @patch("gateway.middleware.auth.validate_any_token")
    def test_malformed_key_wrong_parts(self, mock_validate, client):
        resp = client.get(
            "/api/v1/protected",
            headers={"X-API-Key": "techneos_onlytwoparts"},
        )
        assert resp.status_code == 401


class TestInternalServiceToken:
    """Internal service token auth via X-Internal-Token header."""

    @patch("core.config.get_settings")
    def test_valid_internal_token(self, mock_settings, client):
        settings = MagicMock()
        settings.internal_service_token = "secret-internal-token"
        mock_settings.return_value = settings

        resp = client.get(
            "/api/v1/protected",
            headers={"X-Internal-Token": "secret-internal-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["user"] == "internal-service"

    @patch("core.config.get_settings")
    def test_invalid_internal_token(self, mock_settings, client):
        settings = MagicMock()
        settings.internal_service_token = "correct-token"
        mock_settings.return_value = settings

        resp = client.get(
            "/api/v1/protected",
            headers={"X-Internal-Token": "wrong-token"},
        )
        assert resp.status_code == 401
        assert "Invalid internal token" in resp.json()["detail"]
