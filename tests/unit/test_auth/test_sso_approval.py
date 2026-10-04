"""Tests for admin approval of JIT-provisioned SSO users (SSO_NEW_USERS_ACTIVE)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions import AccountInactiveError


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    role_result = MagicMock()
    role_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=role_result)
    return session


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.headers = {"user-agent": "pytest"}
    request.client.host = "127.0.0.1"
    return request


def _settings(*, sso_new_users_active: bool) -> MagicMock:
    settings = MagicMock()
    settings.sso_new_users_active = sso_new_users_active
    return settings


class TestNewSsoUserActiveFlag:
    """create_user_from_keycloak sets is_active from SSO_NEW_USERS_ACTIVE."""

    @pytest.mark.parametrize("active", [True, False])
    async def test_new_sso_user_follows_setting(self, mock_session, active):
        from auth_service.crud.users import create_user_from_keycloak

        with patch(
            "auth_service.crud.users.get_settings",
            return_value=_settings(sso_new_users_active=active),
        ):
            user = await create_user_from_keycloak(
                mock_session,
                keycloak_sub="kc-sub-1",
                email="new@example.com",
                full_name="New User",
                org_id="org-1",
            )

        assert user.is_active is active

    def test_setting_defaults_to_active(self):
        from core.config import Settings

        assert Settings.model_fields["sso_new_users_active"].default is True


class TestRejectIfInactive:
    """_reject_if_inactive blocks inactive accounts at SSO sign-in."""

    async def test_active_user_passes(self, mock_session, mock_request):
        from auth_service.routes.auth import _reject_if_inactive

        user = MagicMock(is_active=True)
        with patch("auth_service.routes.auth.write_audit_log", new=AsyncMock()) as audit:
            await _reject_if_inactive(mock_session, user, mock_request, "keycloak")

        audit.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    async def test_inactive_user_is_audited_committed_and_rejected(
        self, mock_session, mock_request
    ):
        from auth_service.routes.auth import _reject_if_inactive

        user = MagicMock(is_active=False, id="user-1", email="pending@example.com")
        with (
            patch("auth_service.routes.auth.write_audit_log", new=AsyncMock()) as audit,
            pytest.raises(AccountInactiveError),
        ):
            await _reject_if_inactive(mock_session, user, mock_request, "keycloak")

        audit.assert_awaited_once()
        assert audit.await_args.kwargs["action"] == "user_login_failed"
        assert audit.await_args.kwargs["details"]["reason"] == "inactive_account"
        # Committed before raising so the pending account and audit entry survive
        # the request session's rollback.
        mock_session.commit.assert_awaited_once()


class TestAccountInactiveResponse:
    """The auth service maps AccountInactiveError to 403 with a clear message."""

    async def test_handler_returns_403(self):
        from auth_service.main import account_inactive_handler

        resp = await account_inactive_handler(MagicMock(), AccountInactiveError())

        assert resp.status_code == 403
        assert b"awaiting administrator approval" in resp.body
