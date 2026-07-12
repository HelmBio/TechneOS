"""Route-layer integration tests for the task-service list/auth surface.

Complements test_task_run_api.py (which drives the create→accept→submit
lifecycle) by covering the list endpoint, authentication wiring, and
not-found handling — the cheap, high-signal route branches.

Requires: docker compose up (Postgres must be running)
Run: make test-integration
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

API = "/api/v1/task-runs"


@pytest.fixture
async def task_client():
    from task_service.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_list_requires_auth(task_client):
    assert (await task_client.get(API)).status_code == 401


async def test_list_ok_for_authenticated_user(task_client, scientist_headers):
    resp = await task_client.get(API, headers=scientist_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and "total" in body


async def test_list_status_filter_accepted(task_client, scientist_headers):
    resp = await task_client.get(f"{API}?status=pending", headers=scientist_headers)
    assert resp.status_code == 200


async def test_get_unknown_task_run_404(task_client, scientist_headers):
    resp = await task_client.get(f"{API}/{uuid.uuid4()}", headers=scientist_headers)
    assert resp.status_code in (403, 404)  # no access to a run you do not hold


async def test_accept_unknown_task_run_404(task_client, scientist_headers):
    resp = await task_client.post(f"{API}/{uuid.uuid4()}/accept", headers=scientist_headers)
    assert resp.status_code in (403, 404)


async def test_cancel_requires_auth(task_client):
    resp = await task_client.post(f"{API}/{uuid.uuid4()}/cancel")
    assert resp.status_code == 401
