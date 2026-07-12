"""Tests for the auth provider (JWT creation and validation)."""

import pytest

from core.auth.providers import (
    LocalAuthProvider,
    hash_password,
    verify_password,
)
from core.exceptions import InvalidTokenError


class TestPasswordHashing:
    """Test password hashing utilities."""

    def test_hash_and_verify(self):
        password = "my-secure-password"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_different_hashes(self):
        """Same password should produce different hashes (bcrypt salt)."""
        h1 = hash_password("password")
        h2 = hash_password("password")
        assert h1 != h2


class TestLocalAuthProvider:
    """Test JWT token creation and validation."""

    @pytest.fixture
    def provider(self):
        return LocalAuthProvider()

    @pytest.mark.asyncio
    async def test_create_and_validate_token(self, provider):
        tokens = await provider.create_tokens(
            user_id="user-123",
            claims={
                "email": "test@example.com",
                "role": "scientist",
                "org_id": "org-1",
                "team_id": "team-1",
            },
        )
        assert tokens.access_token
        assert tokens.refresh_token
        assert tokens.token_type == "bearer"

        # Validate access token
        payload = await provider.validate_token(tokens.access_token)
        assert payload.sub == "user-123"
        assert payload.email == "test@example.com"
        assert payload.role == "scientist"
        assert payload.org_id == "org-1"
        assert payload.type == "access"

    @pytest.mark.asyncio
    async def test_refresh_token_flow(self, provider):
        tokens = await provider.create_tokens(
            user_id="user-456",
            claims={"email": "refresh@example.com", "role": "viewer"},
        )

        # Refresh
        new_tokens = await provider.refresh_tokens(tokens.refresh_token)
        assert new_tokens.access_token != tokens.access_token
        assert new_tokens.refresh_token != tokens.refresh_token

        # Validate new access token
        payload = await provider.validate_token(new_tokens.access_token)
        assert payload.sub == "user-456"

    @pytest.mark.asyncio
    async def test_invalid_token(self, provider):
        with pytest.raises(InvalidTokenError):
            await provider.validate_token("not-a-valid-token")

    @pytest.mark.asyncio
    async def test_access_token_cannot_refresh(self, provider):
        tokens = await provider.create_tokens(
            user_id="user-789",
            claims={"email": "test@example.com"},
        )
        with pytest.raises(InvalidTokenError, match="Not a refresh token"):
            await provider.refresh_tokens(tokens.access_token)
