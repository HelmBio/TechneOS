"""Integration tests for dataset + tool + pipeline CRUD flows.

Requires: docker compose up (Postgres must be running)
Run: make test-integration
"""

import pytest
from sqlalchemy import delete
from sqlalchemy import select as sa_select

pytestmark = pytest.mark.integration


@pytest.fixture
async def live_auth_token():
    """Register a real user and get a token via the auth service."""
    import uuid

    from httpx import ASGITransport, AsyncClient

    from core.database.postgres import get_session_factory
    from core.models.user import ApiKey, AuditLog, Org, User

    test_email = "crud-flow-test@example.com"

    # Look up default org — the seeded org's slug is whatever this
    # deployment's seed config says (local .techneos.<env>.json, gitignored), so
    # fall back to creating "default" rather than assuming it's been seeded.
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(sa_select(Org).where(Org.slug == "default"))
        default_org = result.scalar_one_or_none()
        if default_org is None:
            default_org = Org(id=str(uuid.uuid4()), name="Default", slug="default")
            session.add(default_org)
            await session.commit()
        default_org_id = default_org.id

    # Clean up stale test user
    async with factory() as session:
        await session.execute(
            delete(AuditLog).where(
                AuditLog.user_id.in_(sa_select(User.id).where(User.email == test_email))
            )
        )
        await session.execute(
            delete(ApiKey).where(
                ApiKey.user_id.in_(sa_select(User.id).where(User.email == test_email))
            )
        )
        await session.execute(delete(User).where(User.email == test_email))
        await session.commit()

    # Register + login
    from auth_service.main import app as auth_app

    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": test_email,
                "full_name": "CRUD Flow Tester",
                "password": "test-password-123",
                "role_name": "platform_admin",
                "org_id": default_org_id,
            },
        )
        assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.text}"

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "test-password-123"},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

    yield token

    # Cleanup
    from core.models.artifact import ComputeArtifact
    from core.models.dataset import Dataset, DatasetVersion
    from core.models.pipeline import Pipeline, PipelineRun, PipelineRunArtifact, PipelineStepRun
    from core.models.tool import Tool, ToolVersion

    async with factory() as session:
        await session.execute(delete(PipelineRunArtifact))
        await session.execute(delete(PipelineStepRun))
        await session.execute(delete(PipelineRun))
        await session.execute(delete(Pipeline))
        await session.execute(delete(DatasetVersion))
        await session.execute(delete(Dataset))
        await session.execute(delete(ToolVersion))
        await session.execute(delete(Tool))
        # published_by FKs to the test user; must clear before deleting it.
        await session.execute(delete(ComputeArtifact))
        await session.execute(
            delete(ApiKey).where(
                ApiKey.user_id.in_(sa_select(User.id).where(User.email == test_email))
            )
        )
        await session.execute(
            delete(AuditLog).where(
                AuditLog.user_id.in_(sa_select(User.id).where(User.email == test_email))
            )
        )
        await session.execute(delete(User).where(User.email == test_email))
        await session.commit()


@pytest.mark.asyncio
async def test_dataset_crud_flow(dataset_client, live_auth_token):
    """Test create -> list -> get -> update -> delete dataset."""
    headers = {"Authorization": f"Bearer {live_auth_token}"}

    # 1. Create dataset
    create_resp = await dataset_client.post(
        "/api/v1/datasets",
        json={
            "name": "ChEMBL Subset",
            "slug": "chembl-subset",
            "description": "A subset of ChEMBL for testing",
            "data_type": "molecular",
            "tags": ["chembl", "test"],
            "data_schema": {
                "type": "object",
                "required": ["smiles"],
                "properties": {"smiles": {"type": "string"}},
            },
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    ds = create_resp.json()
    assert ds["name"] == "ChEMBL Subset"
    assert ds["data_type"] == "molecular"
    dataset_id = ds["id"]

    # 2. List datasets
    list_resp = await dataset_client.get("/api/v1/datasets", headers=headers)
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] >= 1

    # 3. Get dataset with versions
    get_resp = await dataset_client.get(f"/api/v1/datasets/{dataset_id}", headers=headers)
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["slug"] == "chembl-subset"
    assert detail["versions"] == []

    # 4. Update dataset
    update_resp = await dataset_client.patch(
        f"/api/v1/datasets/{dataset_id}",
        json={"description": "Updated description", "is_public": True},
        headers=headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["is_public"] is True

    # 5. Delete dataset
    delete_resp = await dataset_client.delete(f"/api/v1/datasets/{dataset_id}", headers=headers)
    assert delete_resp.status_code == 204


@pytest.mark.asyncio
async def test_tool_crud_flow(tool_client, live_auth_token):
    """Test create -> get -> add version -> list versions flow."""
    headers = {"Authorization": f"Bearer {live_auth_token}"}

    # 1. Register tool
    create_resp = await tool_client.post(
        "/api/v1/tools",
        json={
            "name": "AutoDock Vina",
            "slug": "autodock-vina",
            "category": "docking",
            "tags": ["docking", "molecular"],
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    tool = create_resp.json()
    tool_id = tool["id"]

    # 2. Add version — the image must exist in the artifact inventory first.
    art_resp = await tool_client.post(
        "/api/v1/compute-artifacts",
        json={
            "kind": "docker_image",
            "origin": "catalog",
            "name": "ghcr.io/example/autodock-vina",
            "version": "v1.2.5",
        },
        headers=headers,
    )
    assert art_resp.status_code == 201, art_resp.text
    ver_resp = await tool_client.post(
        f"/api/v1/tools/{tool_id}/versions",
        json={
            "docker_image": "ghcr.io/example/autodock-vina",
            "docker_tag": "v1.2.5",
            "input_schema": {"type": "object", "properties": {"ligand": {"type": "string"}}},
            "resource_requirements": {"cpu": "4", "memory": "8Gi"},
        },
        headers=headers,
    )
    assert ver_resp.status_code == 201
    version = ver_resp.json()
    assert version["version"] == 1
    assert version["status"] == "draft"

    # 3. Get tool with versions
    get_resp = await tool_client.get(f"/api/v1/tools/{tool_id}", headers=headers)
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert len(detail["versions"]) == 1

    # 4. Update version status to active — lifecycle requires draft -> testing
    # -> active, no direct draft -> active transition.
    testing_resp = await tool_client.patch(
        f"/api/v1/tools/{tool_id}/versions/{version['id']}",
        json={"status": "testing"},
        headers=headers,
    )
    assert testing_resp.status_code == 200, testing_resp.text
    patch_resp = await tool_client.patch(
        f"/api/v1/tools/{tool_id}/versions/{version['id']}",
        json={"status": "active"},
        headers=headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["status"] == "active"

    # Cleanup
    await tool_client.delete(f"/api/v1/tools/{tool_id}", headers=headers)


@pytest.mark.asyncio
async def test_pipeline_submit_flow(tool_client, pipeline_client, live_auth_token):
    """Test define pipeline -> submit run -> check status -> cancel."""
    headers = {"Authorization": f"Bearer {live_auth_token}"}

    # 0. Create required tools with an active version
    for tool_slug, tool_name, category in [
        ("ligand-prep", "Ligand Prep", "docking"),
        ("autodock-vina", "AutoDock Vina", "docking"),
    ]:
        resp = await tool_client.post(
            "/api/v1/tools",
            json={"name": tool_name, "slug": tool_slug, "category": category},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        tool_id = resp.json()["id"]
        art_resp = await tool_client.post(
            "/api/v1/compute-artifacts",
            json={
                "kind": "docker_image",
                "origin": "catalog",
                "name": f"ghcr.io/example/{tool_slug}",
                "version": "v1",
            },
            headers=headers,
        )
        assert art_resp.status_code == 201, art_resp.text
        ver_resp = await tool_client.post(
            f"/api/v1/tools/{tool_id}/versions",
            json={
                "docker_image": f"ghcr.io/example/{tool_slug}",
                "docker_tag": "v1",
                "input_schema": {"type": "object", "properties": {}},
                "resource_requirements": {"cpu": "1", "memory": "1Gi"},
            },
            headers=headers,
        )
        assert ver_resp.status_code == 201, ver_resp.text
        version = ver_resp.json()
        # Lifecycle requires draft -> testing -> active, no direct jump.
        testing_resp = await tool_client.patch(
            f"/api/v1/tools/{tool_id}/versions/{version['id']}",
            json={"status": "testing"},
            headers=headers,
        )
        assert testing_resp.status_code == 200, testing_resp.text
        patch_resp = await tool_client.patch(
            f"/api/v1/tools/{tool_id}/versions/{version['id']}",
            json={"status": "active"},
            headers=headers,
        )
        assert patch_resp.status_code == 200, patch_resp.text

    # 1. Create pipeline definition
    create_resp = await pipeline_client.post(
        "/api/v1/pipelines",
        json={
            "name": "Virtual Screening",
            "slug": "virtual-screening",
            "steps": [
                {"name": "prep", "tool_slug": "ligand-prep", "parameters": {"format": "sdf"}},
                {
                    "name": "dock",
                    "tool_slug": "autodock-vina",
                    "depends_on": ["prep"],
                    "parameters": {"exhaustiveness": 8},
                },
            ],
            # Default_parameters only folds onto a *declared*
            # parameters_schema property — it can't invent one.
            "parameters_schema": {"properties": {"receptor": {"type": "string"}}},
            "default_parameters": {"receptor": "target.pdbqt"},
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    pipeline = create_resp.json()
    pipeline_id = pipeline["id"]
    assert pipeline["version"] == 1

    # 2. Submit a run
    run_resp = await pipeline_client.post(
        "/api/v1/pipeline-runs",
        json={
            "pipeline_id": pipeline_id,
            "parameters": {"exhaustiveness": 16},
        },
        headers=headers,
    )
    assert run_resp.status_code == 201
    run = run_resp.json()
    run_id = run["id"]
    assert run["status"] in ("pending", "queued")
    assert run["parameters"]["receptor"] == "target.pdbqt"
    assert run["parameters"]["exhaustiveness"] == 16

    # 3. Get run detail (includes steps)
    detail_resp = await pipeline_client.get(f"/api/v1/pipeline-runs/{run_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert len(detail["steps"]) == 2
    assert detail["steps"][0]["status"] == "pending"

    # 4. Cancel the run
    cancel_resp = await pipeline_client.post(
        f"/api/v1/pipeline-runs/{run_id}/cancel", headers=headers
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    # 5. Verify cannot cancel again
    cancel2_resp = await pipeline_client.post(
        f"/api/v1/pipeline-runs/{run_id}/cancel", headers=headers
    )
    assert cancel2_resp.status_code == 422

    # Cleanup
    await pipeline_client.delete(f"/api/v1/pipelines/{pipeline_id}", headers=headers)
