"""Tests for the gateway authentication middleware."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gateway.middleware.auth import (
    AUTH_PATHS,
    PUBLIC_PATHS,
    PUBLIC_PREFIXES,
    AuthMiddleware,
)


@pytest.fixture(autouse=True)
def account_active():
    """Treat every token's account as active unless a test says otherwise.

    The real check reads the database; these tests run without one.
    """
    with patch.object(
        AuthMiddleware, "_is_account_active", new=AsyncMock(return_value=True)
    ) as mock:
        yield mock


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

    @_app.get("/simple/")
    async def simple_root():
        return {"index": "root"}

    @_app.get("/simple/{package}/")
    async def simple_package(package: str):
        return {"index": package}

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

    def test_simple_index_prefix_is_public(self):
        # The PyPI Simple proxy must be reachable unauthenticated so uv/pip can
        # resolve packages — the gateway authenticates to the index downstream.
        assert "/simple/" in PUBLIC_PREFIXES

    def test_simple_index_root_no_auth_required(self, client):
        resp = client.get("/simple/")
        assert resp.status_code == 200

    def test_simple_package_page_no_auth_required(self, client):
        resp = client.get("/simple/techneos-tools/")
        assert resp.status_code == 200
        assert resp.json()["index"] == "techneos-tools"


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


class TestInactiveAccount:
    """A valid token for an inactive account (e.g. awaiting approval) is refused."""

    @patch("gateway.middleware.auth.validate_any_token")
    def test_inactive_bearer_returns_403(self, mock_validate, client, account_active):
        mock_validate.return_value = MagicMock(sub="user-123")
        account_active.return_value = False

        resp = client.get(
            "/api/v1/protected",
            headers={"Authorization": "Bearer valid-token"},
        )
        assert resp.status_code == 403
        assert "awaiting administrator approval" in resp.json()["detail"]

    @patch("gateway.middleware.auth.validate_any_token")
    def test_inactive_cookie_returns_403(self, mock_validate, client, account_active):
        mock_validate.return_value = MagicMock(sub="user-123")
        account_active.return_value = False

        client.cookies.set("techneos_access_token", "valid-token")
        resp = client.get("/api/v1/protected")
        assert resp.status_code == 403

    @patch("gateway.middleware.auth.validate_any_token")
    def test_status_lookup_failure_returns_503(self, mock_validate, client, account_active):
        mock_validate.return_value = MagicMock(sub="user-123")
        account_active.side_effect = RuntimeError("db down")

        resp = client.get(
            "/api/v1/protected",
            headers={"Authorization": "Bearer valid-token"},
        )
        assert resp.status_code == 503


class TestAccountStatusCache:
    """_is_account_active caches the database lookup per token subject."""

    @pytest.fixture(autouse=True)
    def account_active(self):
        # Override the module-level fixture: exercise the real method here.
        yield None

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from gateway.middleware import auth as auth_module

        auth_module._account_status_cache.clear()
        yield
        auth_module._account_status_cache.clear()

    async def test_lookup_is_cached(self):
        from core.models.common import TokenPayload

        middleware = AuthMiddleware(app=MagicMock())
        claims = TokenPayload(sub="user-1", email="u@example.com")
        with patch.object(
            AuthMiddleware, "_lookup_account_active", new=AsyncMock(return_value=False)
        ) as lookup:
            assert await middleware._is_account_active(claims) is False
            assert await middleware._is_account_active(claims) is False

        lookup.assert_awaited_once()

    async def test_cache_expires(self):
        from core.models.common import TokenPayload
        from gateway.middleware import auth as auth_module

        middleware = AuthMiddleware(app=MagicMock())
        claims = TokenPayload(sub="user-1", email="u@example.com")
        with (
            patch.object(
                AuthMiddleware, "_lookup_account_active", new=AsyncMock(return_value=True)
            ) as lookup,
            patch.object(auth_module.time, "monotonic", side_effect=[0.0, 1000.0]),
        ):
            await middleware._is_account_active(claims)
            await middleware._is_account_active(claims)

        assert lookup.await_count == 2

    @pytest.mark.parametrize("new_users_active", [True, False])
    async def test_unknown_account_follows_setting(self, new_users_active):
        from core.models.common import TokenPayload

        result = MagicMock()
        result.scalars.return_value = iter([])
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        settings = MagicMock(sso_new_users_active=new_users_active)

        middleware = AuthMiddleware(app=MagicMock())
        claims = TokenPayload(sub="kc-sub", email="new@example.com")
        with (
            patch("core.database.postgres.get_session_factory", return_value=factory),
            patch("gateway.middleware.auth.get_settings", return_value=settings),
        ):
            assert await middleware._lookup_account_active(claims) is new_users_active
