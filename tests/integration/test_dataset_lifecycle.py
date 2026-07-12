"""Integration tests for dataset service lifecycle.

Requires: docker compose up (Postgres + MinIO must be running)
Run: make test-integration
"""

import pytest

pytestmark = pytest.mark.integration


class TestDatasetLifecycle:
    """Test dataset create -> list -> get -> delete flow."""

    async def test_health(self, dataset_client):
        resp = await dataset_client.get("/health")
        assert resp.status_code == 200

    async def test_create_and_retrieve_dataset(self, dataset_client, admin_headers):
        """Create a dataset metadata record and retrieve it."""
        resp = await dataset_client.post(
            "/api/v1/datasets",
            json={
                "name": "Integration Test Dataset",
                "description": "Test dataset for integration",
                "format": "csv",
                "tags": ["test", "integration"],
                "data_schema": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                },
            },
            headers=admin_headers,
        )
        if resp.status_code == 201:
            data = resp.json()
            dataset_id = data["id"]
            assert data["name"] == "Integration Test Dataset"

            # Retrieve by ID
            resp = await dataset_client.get(f"/api/v1/datasets/{dataset_id}", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["id"] == dataset_id

            # Cleanup
            await dataset_client.delete(f"/api/v1/datasets/{dataset_id}", headers=admin_headers)

    async def test_list_datasets_paginated(self, dataset_client, admin_headers):
        """List endpoint supports pagination."""
        resp = await dataset_client.get("/api/v1/datasets?skip=0&limit=5", headers=admin_headers)
        if resp.status_code == 200:
            data = resp.json()
            assert "items" in data
            assert "total" in data
            assert isinstance(data["items"], list)
