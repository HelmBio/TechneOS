"""Integration tests for the auth service HTTP route layer.

Focus: happy paths + the key auth/authorization error branches (401 no token,
403 non-admin) for the admin surface. Exercises the routes end-to-end against
the ``techneos_test`` database via the ASGI test client.

Requires: docker compose up (Postgres must be running)
Run: make test-integration
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

pytestmark = pytest.mark.integration


@pytest.fixture
async def _admin_db_user():
    """Materialize the org + user the shared ``admin_token`` refers to.

    The token's ``sub``/``org_id`` (``test-admin-integration`` / ``org-1``) don't
    exist in the seeded DB, so write paths that write audit logs (FK to users)
    or JIT-provision (FK to orgs) fail without these rows. Create them once so
    the admin route write-paths can be exercised.
    """
    from core.database.postgres import get_session_factory
    from core.models.user import Org, User

    factory = get_session_factory()
    async with factory() as session:
        org = (await session.execute(select(Org).where(Org.id == "org-1"))).scalar_one_or_none()
        if org is None:
            session.add(Org(id="org-1", name="Integ Org", slug="integ-org"))
            await session.flush()
        user = (
            await session.execute(select(User).where(User.id == "test-admin-integration"))
        ).scalar_one_or_none()
        if user is None:
            session.add(
                User(
                    id="test-admin-integration",
                    email="admin-integ@test.com",
                    full_name="Integ Admin",
                    hashed_password="x",
                    org_id="org-1",
                )
            )
        await session.commit()


# ── public / self endpoints ─────────────────────────────────────────────────


async def test_oidc_config_is_public(auth_client):
    resp = await auth_client.get("/api/v1/auth/oidc/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["local"] is True  # email/password always available


async def test_me_requires_auth(auth_client):
    resp = await auth_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_returns_profile(auth_client, admin_headers, _admin_db_user):
    resp = await auth_client.get("/api/v1/auth/me", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "admin-integ@test.com"


# ── admin surface: authorization guards ──────────────────────────────────────


async def test_admin_stats_requires_auth(auth_client):
    assert (await auth_client.get("/api/v1/admin/stats")).status_code == 401


async def test_admin_stats_forbidden_for_scientist(auth_client, scientist_headers):
    resp = await auth_client.get("/api/v1/admin/stats", headers=scientist_headers)
    assert resp.status_code == 403


async def test_admin_stats_ok_for_admin(auth_client, admin_headers):
    resp = await auth_client.get("/api/v1/admin/stats", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    # The stats payload reports platform-wide counts.
    assert "total_users" in resp.json()


# ── admin: list endpoints (happy path) ───────────────────────────────────────


async def test_admin_list_users(auth_client, admin_headers):
    resp = await auth_client.get("/api/v1/admin/users", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body and "total" in body


async def test_admin_list_roles(auth_client, admin_headers):
    resp = await auth_client.get("/api/v1/admin/roles", headers=admin_headers)
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()}
    # Seeded roles are present.
    assert "platform_admin" in names


async def test_admin_list_orgs(auth_client, admin_headers):
    resp = await auth_client.get("/api/v1/admin/orgs", headers=admin_headers)
    assert resp.status_code == 200
    assert "items" in resp.json()


async def test_admin_list_llm_providers(auth_client, admin_headers):
    resp = await auth_client.get("/api/v1/admin/llm-providers", headers=admin_headers)
    assert resp.status_code == 200
    assert "items" in resp.json()


# ── admin: create role + org (happy path, with cleanup) ───────────────────────


async def test_admin_create_and_update_role(auth_client, admin_headers, _admin_db_user):
    slug = f"test_role_{uuid.uuid4().hex[:8]}"
    create = await auth_client.post(
        "/api/v1/admin/roles",
        headers=admin_headers,
        json={"name": slug, "description": "temp", "permissions": ["dataset:read:own"]},
    )
    assert create.status_code == 201, create.text
    role_id = create.json()["id"]
    try:
        update = await auth_client.put(
            f"/api/v1/admin/roles/{role_id}",
            headers=admin_headers,
            json={"description": "updated"},
        )
        assert update.status_code == 200
        assert update.json()["description"] == "updated"
    finally:
        from core.database.postgres import get_session_factory
        from core.models.user import Role

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(delete(Role).where(Role.id == role_id))
            await session.commit()


async def test_admin_create_org(auth_client, admin_headers, _admin_db_user):
    slug = f"test-org-{uuid.uuid4().hex[:8]}"
    resp = await auth_client.post(
        "/api/v1/admin/orgs",
        headers=admin_headers,
        json={"name": "Temp Org", "slug": slug},
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]
    from core.database.postgres import get_session_factory
    from core.models.user import Org

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(Org).where(Org.id == org_id))
        await session.commit()


async def test_admin_get_user_not_found(auth_client, admin_headers):
    resp = await auth_client.get(
        f"/api/v1/admin/users/{uuid.uuid4()}", headers=admin_headers
    )
    assert resp.status_code == 404
