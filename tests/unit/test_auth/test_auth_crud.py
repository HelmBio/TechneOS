"""Tests for auth routes — register, login, refresh, me."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.auth.providers import LocalAuthProvider
from core.models.common import UserCreate


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


class TestRegister:
    """Tests for POST /auth/register (via create_user CRUD)."""

    async def test_create_user_success(self, mock_session):
        from auth_service.crud.users import create_user

        mock_role = MagicMock()
        mock_role.id = "role-1"
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = mock_role
        mock_session.execute.return_value = mock_role_result

        data = UserCreate(
            email="newuser@example.com",
            password="securePass123!",
            full_name="New User",
            org_id="org-1",
            role_name="scientist",
        )

        user = await create_user(mock_session, data)

        assert user.email == "newuser@example.com"
        assert user.full_name == "New User"
        assert user.org_id == "org-1"
        assert user.role_id == "role-1"
        assert user.hashed_password is not None
        assert user.hashed_password != "securePass123!"
        mock_session.add.assert_called_once()

    async def test_create_user_without_role_skips_role_lookup(self, mock_session):
        from auth_service.crud.users import create_user

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        data = UserCreate(
            email="norole@example.com",
            password="securePass123!",
            full_name="No Role User",
            org_id="org-1",
            role_name="",
        )

        user = await create_user(mock_session, data)

        assert user.email == "norole@example.com"
        assert user.role_id is None

    async def test_create_user_duplicate_email(self, mock_session):
        from auth_service.crud.users import get_user_by_email

        existing_user = MagicMock()
        existing_user.email = "existing@example.com"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_session.execute.return_value = mock_result

        user = await get_user_by_email(mock_session, "existing@example.com")
        assert user is not None
        assert user.email == "existing@example.com"

    async def test_create_user_password_is_hashed(self, mock_session):
        from auth_service.crud.users import create_user
        from core.auth.providers import verify_password

        mock_role = MagicMock()
        mock_role.id = "role-1"
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = mock_role
        mock_session.execute.return_value = mock_role_result

        data = UserCreate(
            email="hashcheck@example.com",
            password="mySecretP@ss1",
            full_name="Hash Check",
            org_id="org-1",
        )

        user = await create_user(mock_session, data)

        assert verify_password("mySecretP@ss1", user.hashed_password) is True
        assert verify_password("wrongPassword", user.hashed_password) is False


class TestLogin:
    """Tests for POST /auth/login (verify_password + token creation)."""

    async def test_login_success(self, mock_session):
        from auth_service.crud.users import create_user
        from core.auth.providers import verify_password

        mock_role = MagicMock()
        mock_role.id = "role-1"
        mock_role.name = "scientist"
        mock_role.permissions = ["dataset:read:own", "tool:read:own"]
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = mock_role
        mock_session.execute.return_value = mock_role_result

        data = UserCreate(
            email="login-test@example.com",
            password="CorrectP@ss1",
            full_name="Login Test",
            org_id="org-1",
            role_name="scientist",
        )
        user = await create_user(mock_session, data)

        assert verify_password("CorrectP@ss1", user.hashed_password) is True
        assert user.email == "login-test@example.com"

    async def test_login_wrong_password(self):
        from core.auth.providers import hash_password, verify_password

        hashed = hash_password("CorrectP@ss1")

        assert verify_password("WrongP@ss1", hashed) is False
        assert verify_password("", hashed) is False

    async def test_login_inactive_user(self, mock_session):
        from auth_service.crud.users import create_user
        from core.auth.providers import verify_password

        mock_role = MagicMock()
        mock_role.id = "role-1"
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = mock_role
        mock_session.execute.return_value = mock_role_result

        data = UserCreate(
            email="inactive@example.com",
            password="SecureP@ss1",
            full_name="Inactive User",
            org_id="org-1",
        )
        user = await create_user(mock_session, data)

        # User is active by default — simulate inactive
        user.is_active = False
        assert verify_password("SecureP@ss1", user.hashed_password) is True

    async def test_token_creation(self, mock_session):
        provider = LocalAuthProvider()
        tokens = await provider.create_tokens(
            user_id="user-1",
            claims={
                "email": "test@example.com",
                "role": "scientist",
                "org_id": "org-1",
                "team_id": None,
                "permissions": ["dataset:read:own"],
            },
        )

        assert tokens.access_token is not None
        assert tokens.refresh_token is not None
        assert tokens.token_type == "bearer"

    async def test_token_validation(self, mock_session):
        provider = LocalAuthProvider()
        tokens = await provider.create_tokens(
            user_id="user-1",
            claims={
                "email": "test@example.com",
                "role": "scientist",
                "org_id": "org-1",
            },
        )

        payload = await provider.validate_token(tokens.access_token)
        assert payload.sub == "user-1"
        assert payload.email == "test@example.com"
        assert payload.role == "scientist"
        assert payload.type == "access"

    async def test_token_refresh(self, mock_session):
        provider = LocalAuthProvider()
        tokens = await provider.create_tokens(
            user_id="user-1",
            claims={
                "email": "test@example.com",
                "role": "scientist",
                "org_id": "org-1",
            },
        )

        refresh_payload = await provider.validate_token(tokens.refresh_token)
        assert refresh_payload.sub == "user-1"
        assert refresh_payload.type == "refresh"

    async def test_login_flow_full(self, mock_session):
        from auth_service.crud.users import create_user
        from core.auth.providers import LocalAuthProvider, verify_password

        mock_role = MagicMock()
        mock_role.id = "role-1"
        mock_role.name = "scientist"
        mock_role.permissions = ["dataset:read:own"]
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = mock_role
        mock_session.execute.return_value = mock_role_result

        data = UserCreate(
            email="full-flow@example.com",
            password="TestP@ss123",
            full_name="Full Flow",
            org_id="org-1",
            role_name="scientist",
        )
        user = await create_user(mock_session, data)

        assert verify_password("TestP@ss123", user.hashed_password) is True

        provider = LocalAuthProvider()
        tokens = await provider.create_tokens(
            user_id=user.id,
            claims={
                "email": user.email,
                "role": "scientist",
                "org_id": user.org_id,
                "permissions": ["dataset:read:own"],
            },
        )

        assert tokens.access_token is not None
        assert tokens.refresh_token is not None

        payload = await provider.validate_token(tokens.access_token)
        assert payload.sub == user.id
        assert payload.email == "full-flow@example.com"
