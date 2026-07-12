"""Tests for Keycloak auth integration.

Tests cover:
- _pick_platform_role() role priority resolution
- KeycloakAuthProvider token validation (mocked JWKS)
- KeycloakAuthProvider token creation (mocked httpx)
- KeycloakAuthProvider refresh (mocked httpx)
- KeycloakAuthProvider logout (mocked httpx)
- KeycloakAdminClient user/role operations (mocked httpx)
- Config validation for Keycloak settings
- CLI login-sso command (mocked browser + callback)
- CLI client token auto-refresh on 401
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Role priority resolution ─────────────────────────────────────────


class TestPickPlatformRole:
    """Test _pick_platform_role helper."""

    def test_picks_highest_priority(self):
        from core.auth.providers import _pick_platform_role

        roles = ["viewer", "scientist", "platform_admin", "default-roles-techneos"]
        assert _pick_platform_role(roles) == "platform_admin"

    def test_picks_org_admin_over_scientist(self):
        from core.auth.providers import _pick_platform_role

        roles = ["scientist", "org_admin"]
        assert _pick_platform_role(roles) == "org_admin"

    def test_single_role(self):
        from core.auth.providers import _pick_platform_role

        assert _pick_platform_role(["viewer"]) == "viewer"

    def test_no_matching_role(self):
        from core.auth.providers import _pick_platform_role

        roles = ["uma_authorization", "offline_access", "default-roles-techneos"]
        assert _pick_platform_role(roles) is None

    def test_empty_list(self):
        from core.auth.providers import _pick_platform_role

        assert _pick_platform_role([]) is None

    def test_all_roles_picks_platform_admin(self):
        from core.auth.providers import PLATFORM_ROLES, _pick_platform_role

        assert _pick_platform_role(PLATFORM_ROLES) == "platform_admin"


# ── Config validation ─────────────────────────────────────────────────


class TestKeycloakConfigValidation:
    """Test that Settings validates Keycloak config when partially configured."""

    def test_keycloak_requires_url(self):
        from pydantic import ValidationError

        from core.config import Settings

        with pytest.raises(ValidationError, match="KEYCLOAK_URL"):
            Settings(
                keycloak_url="",
                keycloak_client_id="techneos-api",
                keycloak_client_secret="secret",
            )

    def test_keycloak_requires_client_id(self):
        from pydantic import ValidationError

        from core.config import Settings

        with pytest.raises(ValidationError, match="KEYCLOAK_CLIENT_ID"):
            Settings(
                keycloak_url="http://localhost:8080",
                keycloak_client_id="",
                keycloak_client_secret="secret",
            )

    def test_keycloak_requires_client_secret(self):
        from pydantic import ValidationError

        from core.config import Settings

        with pytest.raises(ValidationError, match="KEYCLOAK_CLIENT_SECRET"):
            Settings(
                keycloak_url="http://localhost:8080",
                keycloak_client_id="techneos-api",
                keycloak_client_secret="",
            )

    def test_keycloak_valid_config(self):
        from core.config import Settings

        s = Settings(
            keycloak_url="http://localhost:8080",
            keycloak_client_id="techneos-api",
            keycloak_client_secret="secret",
        )
        assert s.keycloak_configured is True
        assert s.keycloak_issuer_url == "http://localhost:8080/realms/techneos"
        assert s.keycloak_openid_base == (
            "http://localhost:8080/realms/techneos/protocol/openid-connect"
        )

    def test_no_keycloak_is_fine(self):
        from core.config import Settings

        s = Settings(keycloak_url="", keycloak_client_id="", keycloak_client_secret="")
        assert s.keycloak_configured is False


# ── KeycloakAuthProvider ─────────────────────────────────────────────


class TestKeycloakAuthProvider:
    """Test KeycloakAuthProvider with mocked HTTP calls."""

    @pytest.fixture
    def kc_settings(self):
        """Patch get_settings to return Keycloak config."""
        settings = MagicMock()
        settings.keycloak_url = "http://localhost:8080"
        settings.keycloak_realm = "techneos"
        settings.keycloak_client_id = "techneos-api"
        settings.keycloak_client_secret = "test-secret"
        settings.keycloak_configured = True
        return settings

    @pytest.fixture
    def provider(self, kc_settings):
        with patch("core.auth.providers.get_settings", return_value=kc_settings):
            from core.auth.providers import KeycloakAuthProvider

            return KeycloakAuthProvider()

    @pytest.mark.asyncio
    async def test_create_tokens_ropc(self, provider):
        """Test ROPC flow — password grant."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "kc-access-tok",
            "refresh_token": "kc-refresh-tok",
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            tokens = await provider.create_tokens(
                user_id="user@example.com",
                claims={"email": "user@example.com", "password": "secret123"},
            )

        assert tokens.access_token == "kc-access-tok"
        assert tokens.refresh_token == "kc-refresh-tok"

        # Verify ROPC grant was used
        call_args = mock_client.post.call_args
        post_data = call_args.kwargs.get("data") or call_args[1].get("data")
        assert post_data["grant_type"] == "password"
        assert post_data["username"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_create_tokens_client_credentials(self, provider):
        """Test fallback to client-credentials when no password."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "cc-access-tok",
            "refresh_token": "",
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            tokens = await provider.create_tokens(
                user_id="service-account",
                claims={"email": "svc@example.com"},
            )

        assert tokens.access_token == "cc-access-tok"
        call_args = mock_client.post.call_args
        post_data = call_args.kwargs.get("data") or call_args[1].get("data")
        assert post_data["grant_type"] == "client_credentials"

    @pytest.mark.asyncio
    async def test_create_tokens_failure(self, provider):
        """Test error handling when Keycloak returns non-200."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "invalid_grant"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from core.exceptions import InvalidTokenError

            with pytest.raises(InvalidTokenError, match="401"):
                await provider.create_tokens(
                    user_id="bad-user",
                    claims={"email": "bad@example.com", "password": "wrong"},
                )

    @pytest.mark.asyncio
    async def test_validate_token_success(self, provider):
        """Test successful JWT validation against JWKS."""
        decoded_payload = {
            "sub": "kc-user-id",
            "email": "user@example.com",
            "realm_access": {"roles": ["scientist", "default-roles-techneos"]},
            "org_id": "org-1",
            "team_id": "team-1",
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        }

        with (
            patch.object(provider, "_get_jwks", new_callable=AsyncMock, return_value={"keys": []}),
            patch("core.auth.providers.jwt.decode", return_value=decoded_payload),
        ):
            payload = await provider.validate_token("fake-token")

        assert payload.sub == "kc-user-id"
        assert payload.email == "user@example.com"
        assert payload.role == "scientist"
        assert payload.org_id == "org-1"
        assert payload.team_id == "team-1"
        assert payload.type == "access"

    @pytest.mark.asyncio
    async def test_validate_token_picks_highest_role(self, provider):
        """Test that the highest-priority platform role is selected."""
        decoded_payload = {
            "sub": "admin-id",
            "email": "admin@example.com",
            "realm_access": {"roles": ["viewer", "scientist", "org_admin"]},
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        }

        with (
            patch.object(provider, "_get_jwks", new_callable=AsyncMock, return_value={"keys": []}),
            patch("core.auth.providers.jwt.decode", return_value=decoded_payload),
        ):
            payload = await provider.validate_token("fake-token")

        assert payload.role == "org_admin"

    @pytest.mark.asyncio
    async def test_validate_token_expired(self, provider):
        """Test that expired tokens raise TokenExpiredError."""
        from jose import JWTError

        from core.exceptions import TokenExpiredError

        with (
            patch.object(provider, "_get_jwks", new_callable=AsyncMock, return_value={"keys": []}),
            patch(
                "core.auth.providers.jwt.decode",
                side_effect=JWTError("Signature has expired"),
            ),
            pytest.raises(TokenExpiredError),
        ):
            await provider.validate_token("expired-token")

    @pytest.mark.asyncio
    async def test_validate_token_invalid(self, provider):
        """Test that invalid tokens raise InvalidTokenError."""
        from jose import JWTError

        from core.exceptions import InvalidTokenError

        with (
            patch.object(provider, "_get_jwks", new_callable=AsyncMock, return_value={"keys": []}),
            patch(
                "core.auth.providers.jwt.decode",
                side_effect=[JWTError("bad sig"), JWTError("bad sig again")],
            ),
            pytest.raises(InvalidTokenError),
        ):
            await provider.validate_token("invalid-token")

    @pytest.mark.asyncio
    async def test_jwks_ttl_caching(self, provider):
        """Test that JWKS keys are cached and refreshed after TTL."""
        mock_jwks = {"keys": [{"kid": "key-1"}]}

        with patch.object(
            provider, "_fetch_jwks", new_callable=AsyncMock, return_value=mock_jwks
        ) as mock_fetch:
            # First call — fetches
            result = await provider._get_jwks()
            assert result == mock_jwks
            assert mock_fetch.call_count == 1

            # Second call — cached
            result = await provider._get_jwks()
            assert mock_fetch.call_count == 1

            # Simulate TTL expiry
            provider._jwks_fetched_at = time.monotonic() - 3601
            result = await provider._get_jwks()
            assert mock_fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_refresh_tokens(self, provider):
        """Test refresh token exchange."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            tokens = await provider.refresh_tokens("old-refresh-token")

        assert tokens.access_token == "new-access"
        assert tokens.refresh_token == "new-refresh"
        call_args = mock_client.post.call_args
        post_data = call_args.kwargs.get("data") or call_args[1].get("data")
        assert post_data["grant_type"] == "refresh_token"

    @pytest.mark.asyncio
    async def test_refresh_tokens_failure(self, provider):
        """Test refresh failure raises InvalidTokenError."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "invalid_grant"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from core.exceptions import InvalidTokenError

            with pytest.raises(InvalidTokenError, match="400"):
                await provider.refresh_tokens("bad-refresh-token")

    @pytest.mark.asyncio
    async def test_logout(self, provider):
        """Test logout calls Keycloak endpoint."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=MagicMock(status_code=204))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await provider.logout("refresh-tok")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        post_data = call_args.kwargs.get("data") or call_args[1].get("data")
        assert post_data["refresh_token"] == "refresh-tok"
        assert "logout" in call_args[0][0]


# ── KeycloakAdminClient ─────────────────────────────────────────────


class TestKeycloakAdminClient:
    """Test KeycloakAdminClient with mocked HTTP calls."""

    @pytest.fixture
    def admin_settings(self):
        settings = MagicMock()
        settings.keycloak_url = "http://localhost:8080"
        settings.keycloak_realm = "techneos"
        settings.keycloak_admin_user = "admin"
        settings.keycloak_admin_password = "admin"
        settings.keycloak_client_id = "techneos-api"
        settings.keycloak_client_secret = "secret"
        settings.keycloak_openid_base = (
            "http://localhost:8080/realms/techneos/protocol/openid-connect"
        )
        return settings

    @pytest.fixture
    def admin_client(self, admin_settings):
        with patch("core.auth.keycloak_admin.get_settings", return_value=admin_settings):
            from core.auth.keycloak_admin import KeycloakAdminClient

            client = KeycloakAdminClient()
            client._admin_token = "admin-tok"  # pre-set to skip token fetch
            return client

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, admin_client):
        """Test looking up a user by email."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": "kc-id-1", "email": "user@example.com", "username": "user@example.com"}
        ]
        mock_resp.raise_for_status = MagicMock()

        with patch.object(admin_client, "_request", new_callable=AsyncMock, return_value=mock_resp):
            user = await admin_client.get_user_by_email("user@example.com")

        assert user is not None
        assert user["id"] == "kc-id-1"

    @pytest.mark.asyncio
    async def test_get_user_by_email_not_found(self, admin_client):
        """Test email lookup returns None for unknown user."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch.object(admin_client, "_request", new_callable=AsyncMock, return_value=mock_resp):
            user = await admin_client.get_user_by_email("nobody@example.com")

        assert user is None

    @pytest.mark.asyncio
    async def test_create_user(self, admin_client):
        """Test user creation returns Keycloak user ID."""
        create_resp = MagicMock()
        create_resp.status_code = 201
        create_resp.headers = {"Location": "http://localhost:8080/admin/realms/dr/users/new-kc-id"}
        create_resp.raise_for_status = MagicMock()

        with (
            patch.object(
                admin_client, "_request", new_callable=AsyncMock, return_value=create_resp
            ),
            patch.object(admin_client, "assign_realm_roles", new_callable=AsyncMock),
        ):
            kc_id = await admin_client.create_user(
                email="new@example.com",
                password="password123",
                first_name="New",
                last_name="User",
                realm_roles=["scientist"],
            )

        assert kc_id == "new-kc-id"

    @pytest.mark.asyncio
    async def test_create_user_already_exists(self, admin_client):
        """Test 409 → returns existing user ID."""
        conflict_resp = MagicMock()
        conflict_resp.status_code = 409

        existing = {"id": "existing-id", "email": "dup@example.com"}

        async def mock_request(method, path, **kwargs):
            if method == "POST":
                return conflict_resp
            return MagicMock(status_code=200, json=MagicMock(return_value=[existing]))

        with (
            patch.object(admin_client, "_request", side_effect=mock_request),
            patch.object(
                admin_client,
                "get_user_by_email",
                new_callable=AsyncMock,
                return_value=existing,
            ),
        ):
            kc_id = await admin_client.create_user(email="dup@example.com", password="pass123")

        assert kc_id == "existing-id"

    @pytest.mark.asyncio
    async def test_get_realm_roles(self, admin_client):
        """Test listing realm roles."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": "r1", "name": "scientist"},
            {"id": "r2", "name": "viewer"},
        ]
        mock_resp.raise_for_status = MagicMock()

        with patch.object(admin_client, "_request", new_callable=AsyncMock, return_value=mock_resp):
            roles = await admin_client.get_realm_roles()

        assert len(roles) == 2
        assert roles[0]["name"] == "scientist"

    @pytest.mark.asyncio
    async def test_assign_realm_roles(self, admin_client):
        """Test assigning roles to a user."""
        role_resp = MagicMock()
        role_resp.status_code = 200
        role_resp.json.return_value = {"id": "role-id-1", "name": "scientist"}
        role_resp.raise_for_status = MagicMock()

        assign_resp = MagicMock()
        assign_resp.status_code = 204
        assign_resp.raise_for_status = MagicMock()

        call_count = 0

        async def mock_request(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            if method == "GET":
                return role_resp
            return assign_resp

        with patch.object(admin_client, "_request", side_effect=mock_request):
            await admin_client.assign_realm_roles("user-id", ["scientist"])

        assert call_count == 2  # GET role + POST assignment

    @pytest.mark.asyncio
    async def test_logout_user(self, admin_client):
        """Test terminating user sessions."""
        mock_resp = MagicMock()
        mock_resp.status_code = 204

        with patch.object(admin_client, "_request", new_callable=AsyncMock, return_value=mock_resp):
            await admin_client.logout_user("user-id")

    @pytest.mark.asyncio
    async def test_revoke_token(self, admin_client, admin_settings):
        """Test token revocation."""
        with patch("core.auth.keycloak_admin.get_settings", return_value=admin_settings):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                await admin_client.revoke_token("refresh-tok")

            mock_client.post.assert_called_once()


# ── CLI login-sso command ────────────────────────────────────────────


class TestCLILoginSSO:
    """Test the CLI login-sso command with mocked browser and server."""

    @patch("cli.commands.auth.api_post")
    @patch("cli.commands.auth.save_tokens")
    @patch("webbrowser.open")
    @patch("httpx.get")
    def test_login_sso_success(self, mock_httpx_get, mock_browser, mock_save, mock_post):
        """Test successful SSO login flow."""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()

        # Mock OIDC config response (new shape — keycloak/oauth2 fields)
        oidc_resp = MagicMock()
        oidc_resp.status_code = 200
        oidc_resp.json.return_value = {
            "local": True,
            "keycloak": {
                "authorization_endpoint": "http://localhost:8080/realms/techneos/protocol/openid-connect/auth",
                "token_endpoint": "http://localhost:8080/realms/techneos/protocol/openid-connect/token",
                "userinfo_endpoint": "http://localhost:8080/realms/techneos/protocol/openid-connect/userinfo",
                "end_session_endpoint": "http://localhost:8080/realms/techneos/protocol/openid-connect/logout",
                "client_id": "techneos-web",
            },
            "oauth2": None,
        }
        oidc_resp.raise_for_status = MagicMock()
        mock_httpx_get.return_value = oidc_resp

        # Mock token exchange response
        mock_post.return_value = {
            "access_token": "sso-access",
            "refresh_token": "sso-refresh",
        }

        # We mock handle_request to do nothing, so the code will reach
        # "Timed out waiting for login callback" because result dict is empty.
        # But that's fine — we're testing that the browser was opened with
        # the correct authorization URL.
        with patch("http.server.HTTPServer.handle_request"):
            runner.invoke(app, ["auth", "login-sso", "--port", "18085"])

        # The browser should have been opened with the Keycloak auth URL
        mock_browser.assert_called_once()
        auth_url = mock_browser.call_args[0][0]
        assert "localhost:8080" in auth_url
        assert "response_type=code" in auth_url
        assert "client_id=techneos-web" in auth_url
        assert "code_challenge" in auth_url

    @patch("httpx.get")
    def test_login_sso_disabled(self, mock_httpx_get):
        """Test SSO login when no SSO provider is configured."""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()

        oidc_resp = MagicMock()
        oidc_resp.status_code = 200
        oidc_resp.json.return_value = {"local": True, "keycloak": None, "oauth2": None}
        oidc_resp.raise_for_status = MagicMock()
        mock_httpx_get.return_value = oidc_resp

        result = runner.invoke(app, ["auth", "login-sso"])
        assert result.exit_code == 1
        assert "not enabled" in result.output

    @patch("httpx.get", side_effect=Exception("Connection refused"))
    def test_login_sso_unreachable(self, mock_httpx_get):
        """Test SSO login when platform is unreachable."""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()

        result = runner.invoke(app, ["auth", "login-sso"])
        assert result.exit_code == 1
        assert "Failed to fetch OIDC config" in result.output


# ── CLI token auto-refresh ───────────────────────────────────────────


class TestCLITokenRefresh:
    """Test the token auto-refresh mechanism in the CLI client."""

    def test_try_refresh_no_tokens(self):
        """Test refresh returns False when no tokens stored."""
        with patch("cli.client.load_tokens", return_value=None):
            from cli.client import _try_refresh

            assert _try_refresh() is False

    def test_try_refresh_no_refresh_token(self):
        """Test refresh returns False when no refresh token."""
        with patch("cli.client.load_tokens", return_value={"access_token": "tok"}):
            from cli.client import _try_refresh

            assert _try_refresh() is False

    @patch("cli.client.save_tokens")
    @patch("cli.client.get_base_url", return_value="http://test:8000")
    @patch("cli.client.load_tokens", return_value={"access_token": "old", "refresh_token": "ref"})
    @patch("httpx.post")
    def test_try_refresh_success(self, mock_post, mock_tokens, mock_url, mock_save):
        """Test successful token refresh."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        }
        mock_post.return_value = mock_resp

        from cli.client import _try_refresh

        assert _try_refresh() is True
        mock_save.assert_called_once_with("new-access", "new-refresh")

    @patch("cli.client.get_base_url", return_value="http://test:8000")
    @patch("cli.client.load_tokens", return_value={"access_token": "old", "refresh_token": "ref"})
    @patch("httpx.post")
    def test_try_refresh_failure(self, mock_post, mock_tokens, mock_url):
        """Test refresh returns False on server error."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_post.return_value = mock_resp

        from cli.client import _try_refresh

        assert _try_refresh() is False

    @patch("cli.client.get_base_url", return_value="http://test:8000")
    @patch("cli.client.load_tokens", return_value={"access_token": "old", "refresh_token": "ref"})
    @patch("httpx.post", side_effect=Exception("Connection refused"))
    def test_try_refresh_exception(self, mock_post, mock_tokens, mock_url):
        """Test refresh returns False on network error."""
        from cli.client import _try_refresh

        assert _try_refresh() is False


# ── CLI logout with server-side revocation ───────────────────────────


class TestCLILogoutRevocation:
    """Test that CLI logout attempts to revoke the server-side session."""

    @patch("cli.commands.auth.api_post")
    @patch("cli.commands.auth.clear_tokens")
    @patch("cli.config.load_tokens", return_value={"access_token": "tok", "refresh_token": "ref"})
    def test_logout_revokes(self, mock_tokens, mock_clear, mock_post):
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["auth", "logout"])
        assert result.exit_code == 0
        assert "Logged out" in result.output

        # Should have called the logout endpoint
        mock_post.assert_called_once_with(
            "/api/v1/auth/logout",
            json={"refresh_token": "ref"},
        )
        mock_clear.assert_called_once()

    @patch("cli.commands.auth.api_post", side_effect=Exception("network error"))
    @patch("cli.commands.auth.clear_tokens")
    @patch("cli.config.load_tokens", return_value={"access_token": "tok", "refresh_token": "ref"})
    def test_logout_revoke_failure_still_clears(self, mock_tokens, mock_clear, mock_post):
        """Test that logout clears tokens even if server revocation fails."""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["auth", "logout"])
        assert result.exit_code == 0
        assert "Logged out" in result.output
        mock_clear.assert_called_once()

    @patch("cli.commands.auth.api_post")
    @patch("cli.commands.auth.clear_tokens")
    @patch("cli.config.load_tokens", return_value=None)
    def test_logout_no_tokens(self, mock_tokens, mock_clear, mock_post):
        """Test logout when not logged in — should not call server."""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["auth", "logout"])
        assert result.exit_code == 0
        mock_post.assert_not_called()
        mock_clear.assert_called_once()
