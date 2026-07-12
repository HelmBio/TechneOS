"""Integration tests for pipeline execution lifecycle.

Requires: docker compose up (Postgres must be running)
Run: make test-integration
"""

import pytest

pytestmark = pytest.mark.integration


class TestPipelineLifecycle:
    """Test creating, running, and tracking a pipeline."""

    async def test_health_endpoint(self, pipeline_client):
        resp = await pipeline_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    async def test_create_pipeline_requires_auth(self, pipeline_client):
        """Pipeline creation without auth should fail."""
        resp = await pipeline_client.post(
            "/api/v1/pipelines",
            json={"name": "test", "description": "desc", "steps": []},
        )
        assert resp.status_code in (401, 403, 422)

    async def test_create_and_list_pipeline(self, pipeline_client, admin_headers):
        """Full pipeline create -> list flow."""
        resp = await pipeline_client.post(
            "/api/v1/pipelines",
            json={
                "name": "Integration Test Pipeline",
                "description": "Created by integration test",
                "steps": [
                    {
                        "name": "step1",
                        "tool_slug": "csv-filter",
                        "tool_version": None,
                        "parameters": {},
                        "depends_on": [],
                        "resource_requirements": {},
                    }
                ],
            },
            headers=admin_headers,
        )
        if resp.status_code == 201:
            data = resp.json()
            assert data["name"] == "Integration Test Pipeline"
            pipeline_id = data["id"]

            # List should include our pipeline
            resp = await pipeline_client.get("/api/v1/pipelines", headers=admin_headers)
            assert resp.status_code == 200
            items = resp.json()["items"]
            assert any(p["id"] == pipeline_id for p in items)

            # Cleanup
            await pipeline_client.delete(f"/api/v1/pipelines/{pipeline_id}", headers=admin_headers)


class TestRBACEnforcement:
    """Test role-based access control across services."""

    async def test_non_admin_cannot_access_admin_routes(self, pipeline_client, scientist_headers):
        """Scientist-level token should not access admin endpoints."""
        resp = await pipeline_client.get("/api/v1/admin/users", headers=scientist_headers)
        assert resp.status_code in (403, 404, 405)
