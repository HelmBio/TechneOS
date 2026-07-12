"""Route-layer integration tests for the dataset service.

Covers the dataset CRUD routes and the dataset-version list/get/auth surface
(the version routes are the platform's largest under-tested route module). The
heavy upload/download/transfer paths — which need multipart bodies and live
object storage — are intentionally out of scope here.

Requires: docker compose up (Postgres must be running)
Run: make test-integration
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.integration

DATASETS = "/api/v1/datasets"
_SCHEMA = {"type": "object", "properties": {"smiles": {"type": "string"}}}


@pytest.fixture
def perm_headers() -> dict[str, str]:
    """A token whose ``permissions`` claim grants everything at platform scope.

    The route layer checks the token's ``permissions`` claim (not just the
    role), so the shared conftest admin token — which omits it — gets 403 on
    permission-gated writes. sub/org match the row _admin_db_user creates.
    """
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta

    from jose import jwt as jose_jwt

    from core.config import get_settings

    settings = get_settings()
    payload = {
        "sub": "test-admin-integration",
        "email": "admin-integ@test.com",
        "role": "platform_admin",
        "org_id": "org-1",
        "permissions": ["*:*:platform"],
        "type": "access",
        "jti": str(_uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    token = jose_jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def _admin_db_user():
    """Ensure the org + user referenced by the admin token exist (FK targets)."""
    from core.database.postgres import get_session_factory
    from core.models.user import Org, User

    factory = get_session_factory()
    async with factory() as session:
        if (await session.execute(select(Org).where(Org.id == "org-1"))).scalar_one_or_none() is None:
            session.add(Org(id="org-1", name="Integ Org", slug="integ-org"))
            await session.flush()
        if (
            await session.execute(select(User).where(User.id == "test-admin-integration"))
        ).scalar_one_or_none() is None:
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


@pytest.fixture
async def dataset_client():
    from dataset_service.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def a_dataset(dataset_client, perm_headers, _admin_db_user):
    """Create a dataset, yield its id, then delete it."""
    slug = f"ds-{uuid.uuid4().hex[:8]}"
    resp = await dataset_client.post(
        DATASETS,
        headers=perm_headers,
        json={"name": "Integ DS", "slug": slug, "data_type": "molecular", "data_schema": _SCHEMA},
    )
    assert resp.status_code == 201, resp.text
    dataset_id = resp.json()["id"]
    yield dataset_id
    from sqlalchemy import delete

    from core.database.postgres import get_session_factory
    from core.models.dataset import Dataset

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
        await session.commit()


# ── dataset routes ────────────────────────────────────────────────────────────


async def test_list_datasets_requires_auth(dataset_client):
    assert (await dataset_client.get(DATASETS)).status_code == 401


async def test_create_and_get_dataset(dataset_client, perm_headers, a_dataset):
    # a_dataset fixture already created one; fetch it back.
    resp = await dataset_client.get(f"{DATASETS}/{a_dataset}", headers=perm_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == a_dataset
    assert "versions" in body  # DatasetWithVersions shape


async def test_list_datasets(dataset_client, perm_headers, a_dataset):
    resp = await dataset_client.get(DATASETS, headers=perm_headers)
    assert resp.status_code == 200
    assert any(d["id"] == a_dataset for d in resp.json()["items"])


async def test_get_dataset_not_found(dataset_client, perm_headers):
    resp = await dataset_client.get(f"{DATASETS}/{uuid.uuid4()}", headers=perm_headers)
    assert resp.status_code == 404


async def test_create_dataset_rejects_bad_slug(dataset_client, perm_headers, _admin_db_user):
    resp = await dataset_client.post(
        DATASETS,
        headers=perm_headers,
        json={"name": "X", "slug": "Bad Slug!", "data_schema": _SCHEMA},
    )
    assert resp.status_code == 422  # slug pattern violation


# ── dataset-version routes ──────────────────────────────────────────────────


async def test_list_versions_empty(dataset_client, perm_headers, a_dataset):
    resp = await dataset_client.get(f"{DATASETS}/{a_dataset}/versions", headers=perm_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []  # freshly-created dataset has no versions yet


async def test_list_versions_requires_auth(dataset_client, a_dataset):
    assert (await dataset_client.get(f"{DATASETS}/{a_dataset}/versions")).status_code == 401


async def test_get_version_not_found(dataset_client, perm_headers, a_dataset):
    resp = await dataset_client.get(
        f"{DATASETS}/{a_dataset}/versions/{uuid.uuid4()}", headers=perm_headers
    )
    assert resp.status_code == 404
