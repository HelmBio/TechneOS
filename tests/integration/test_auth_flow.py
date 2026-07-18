"""Integration tests for the full auth flow.

Requires: docker compose up (Postgres must be running)
Run: make test-integration
"""

import pytest
from sqlalchemy import delete, select

pytestmark = pytest.mark.integration


@pytest.fixture
async def _cleanup_test_user():
    """Delete the test user after the test (cleanup)."""
    yield

    from core.database.postgres import get_session_factory
    from core.models.user import ApiKey, AuditLog, User

    factory = get_session_factory()
    async with factory() as session:
        test_email = "scientist-authflow@example.com"
        await session.execute(
            delete(AuditLog).where(
                AuditLog.user_id.in_(select(User.id).where(User.email == test_email))
            )
        )
        await session.execute(
            delete(ApiKey).where(
                ApiKey.user_id.in_(select(User.id).where(User.email == test_email))
            )
        )
        await session.execute(delete(User).where(User.email == test_email))
        await session.commit()


@pytest.mark.asyncio
async def test_full_auth_flow(auth_client, _cleanup_test_user):
    """Test register -> login -> get profile -> create API key -> refresh."""
    import uuid

    from core.database.postgres import get_session_factory
    from core.models.user import Org

    factory = get_session_factory()
    async with factory() as session:
        # The seeded org's slug depends on this deployment's config —
        # seed.defaults.json plus any DEFAULT_ORG_SLUG override in .env — so
        # fall back to creating "default" rather than assuming it matches.
        result = await session.execute(select(Org).where(Org.slug == "default"))
        org = result.scalar_one_or_none()
        if org is None:
            org = Org(id=str(uuid.uuid4()), name="Default", slug="default")
            session.add(org)
            await session.commit()
        org_id = org.id

    # 1. Register
    register_resp = await auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "scientist-authflow@example.com",
            "full_name": "Dr. Test Scientist",
            "password": "secure-password-123",
            "role_name": "scientist",
            "org_id": org_id,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    user = register_resp.json()
    assert user["email"] == "scientist-authflow@example.com"
    user_id = user["id"]

    # 2. Login
    login_resp = await auth_client.post(
        "/api/v1/auth/login",
        json={
            "email": "scientist-authflow@example.com",
            "password": "secure-password-123",
        },
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens

    access_token = tokens["access_token"]

    # 3. Get profile
    me_resp = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_resp.status_code == 200
    me = me_resp.json()
    assert me["email"] == "scientist-authflow@example.com"
    assert me["id"] == user_id

    # 4. Create API key
    key_resp = await auth_client.post(
        "/api/v1/api-keys",
        json={"name": "My CLI Key", "scopes": ["read"]},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert key_resp.status_code == 201
    key_data = key_resp.json()
    assert key_data["key"].startswith("techneos_")
    assert key_data["name"] == "My CLI Key"

    # 5. List API keys
    keys_resp = await auth_client.get(
        "/api/v1/api-keys",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert keys_resp.status_code == 200
    keys = keys_resp.json()
    assert len(keys) == 1

    # 6. Refresh token
    refresh_resp = await auth_client.post(
        "/api/v1/auth/refresh",
        params={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    assert new_tokens["access_token"] != access_token
