"""HTTP-level integration tests for the task-service routes.

Drives the FastAPI app (task_service.main.app) over an ASGI client against the
real Postgres test DB + MinIO, exercising the route layer added/changed in the
refactor: the new /actions update endpoint, unified artifact upload/download,
staged-input binding, and the response shape.

Requires: docker compose up (Postgres + MinIO must be running)
Run: make test-integration  (or: uv run pytest -m integration tests/integration/test_task_run_api.py)
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Register the full model set before the session-scoped create_all in conftest.
import core.models.agent
import core.models.app
import core.models.bucket
import core.models.dataset
import core.models.llm_provider
import core.models.notification
import core.models.pipeline
import core.models.platform
import core.models.task_run
import core.models.tool
import core.models.tool_run
import core.models.user  # noqa: F401
from core.config import get_settings
from core.database.postgres import get_session_factory
from core.models.tool import HumanConfig, Tool, ToolVersion
from core.models.user import Org, User

pytestmark = pytest.mark.integration

API = "/api/v1/task-runs"


def _token(sub: str, org_id: str) -> str:
    """A JWT with task_run perms (platform scope → passes every check)."""
    from jose import jwt as jose_jwt

    settings = get_settings()
    payload = {
        "sub": sub,
        "email": f"{sub}@task-api-test.example",
        "role": "scientist",
        "org_id": org_id,
        "permissions": ["task_run:*:platform"],
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jose_jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def _headers(sub: str, org_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(sub, org_id)}"}


class _ApiEnv:
    def __init__(self, org_id, creator, assignee, outsider, tool_slug, version_id):
        self.org_id = org_id
        self.creator = creator
        self.assignee = assignee
        self.outsider = outsider
        self.tool_slug = tool_slug
        self.version_id = version_id


async def _mk_user(session, org_id: str, label: str) -> str:
    uid = str(uuid.uuid4())
    session.add(
        User(
            id=uid,
            email=f"{label}-{uid[:8]}@task-api-test.example",
            full_name=f"{label.title()}",
            hashed_password="x",
            org_id=org_id,
        )
    )
    return uid


def _purge_minio(*prefixes: str) -> None:
    """Delete every object under the given prefixes in the default bucket.

    Integration tests write to the *real* shared MinIO (object storage isn't
    isolated per test-DB), so we clean up after ourselves to avoid leaving
    residue under techneos-data/task-runs/… and techneos-data/scratch-space/….
    """
    from core.storage import get_object_store

    store = get_object_store()
    for prefix in prefixes:
        for obj in store.list_objects("techneos-data", prefix):
            with contextlib.suppress(Exception):
                store.delete("techneos-data", obj.key)


@pytest.fixture
async def api_env():
    factory = get_session_factory()
    async with factory() as session:
        org = (await session.execute(select(Org).where(Org.slug == "default"))).scalar_one_or_none()
        if org is None:
            org = Org(id=str(uuid.uuid4()), name="Default", slug="default")
            session.add(org)
            await session.flush()
        org_id = org.id

        creator = await _mk_user(session, org_id, "creator")
        assignee = await _mk_user(session, org_id, "assignee")
        outsider = await _mk_user(session, org_id, "outsider")

        tool = Tool(
            id=str(uuid.uuid4()),
            name="Hit Triage",
            slug=f"hit-triage-api-{uuid.uuid4().hex[:8]}",
            org_id=org_id,
            created_by=creator,
            tool_type="human",
        )
        session.add(tool)
        await session.flush()
        version = ToolVersion(id=str(uuid.uuid4()), tool_id=tool.id, version=1, created_by=creator)
        session.add(version)
        await session.flush()
        session.add(
            HumanConfig(
                tool_version_id=version.id,
                assignment_type="user",
                require_attachments=False,
                priority="medium",
            )
        )
        await session.commit()
        env = _ApiEnv(org_id, creator, assignee, outsider, tool.slug, version.id)

    yield env

    # Tear down MinIO objects this test created (canonical + scratch).
    _purge_minio(f"task-runs/{env.tool_slug}/", f"scratch-space/task-runs/{env.org_id}/")


async def _create_run(client, env: _ApiEnv) -> dict:
    resp = await client.post(
        f"{API}/from-tool",
        json={
            "tool_slug": env.tool_slug,
            "tool_version_id": env.version_id,
            "assigned_user_id": env.assignee,
            "input_snapshot": {"set": "A"},
        },
        headers=_headers(env.creator, env.org_id),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Full lifecycle over HTTP ────────────────────────────────────────────────


async def test_create_accept_update_finish_over_http(api_env: _ApiEnv):
    env = api_env
    transport = ASGITransport(app=__import__("task_service.main", fromlist=["app"]).app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run = await _create_run(client, env)
        run_id = run["id"]
        assert run["status"] == "pending"
        assert run["assigned_user_id"] == env.assignee
        assert run["input_snapshot"] == {"set": "A"}

        ah = _headers(env.assignee, env.org_id)

        # Accept.
        r = await client.post(f"{API}/{run_id}/accept", headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "accepted"

        # Find the start event to thread under.
        start_id = next(e["id"] for e in r.json()["event_history"] if e["action_type"] == "start")

        # Post a threaded update with a message + file.
        r = await client.post(
            f"{API}/{run_id}/actions",
            data={"message": "first pass", "parent_event_id": start_id},
            files={"file": ("wip.csv", b"a,b\n1,2\n", "text/csv")},
            headers=ah,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        update_ev = next(e for e in body["event_history"] if e["action_type"] == "update")
        assert update_ev["parent_event_id"] == start_id
        assert update_ev["message"] == "first pass"
        assert len(update_ev["artifacts"]) == 1
        assert any(a["action_type"] == "update" for a in body["artifacts"])

        # Finish with output data.
        r = await client.post(
            f"{API}/{run_id}/submit",
            json={"output_data": {"decision": "advance"}},
            headers=ah,
        )
        assert r.status_code == 200, r.text
        fin = r.json()
        assert fin["status"] == "terminal"
        assert fin["display_status"] == "completed"
        assert fin["output_data"]["decision"] == "advance"

        # Final timeline is ordered and complete.
        r = await client.get(f"{API}/{run_id}", headers=ah)
        actions = [e["action_type"] for e in r.json()["event_history"]]
        assert actions == ["start", "accept", "update", "finish"]


# ── Staged input → bind on create ────────────────────────────────────────────


async def test_staged_input_binds_on_create(api_env: _ApiEnv):
    env = api_env
    transport = ASGITransport(app=__import__("task_service.main", fromlist=["app"]).app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ch = _headers(env.creator, env.org_id)
        # Stage an input file. Inputs are validated on bind, so use valid JSON
        # compound data.
        r = await client.post(
            f"{API}/from-tool/upload",
            data={"tool_slug": env.tool_slug, "tool_version_id": env.version_id},
            files={"file": ("hits.json", b'[{"smiles": "CCO", "id": "c1"}]', "application/json")},
            headers=ch,
        )
        assert r.status_code == 201, r.text
        input_id = r.json()["input_id"]
        assert r.json()["storage_path"].startswith("scratch-space/task-runs/")

        # Create a run binding the staged input.
        r = await client.post(
            f"{API}/from-tool",
            json={
                "tool_slug": env.tool_slug,
                "tool_version_id": env.version_id,
                "assigned_user_id": env.assignee,
                "input_snapshot": {"input_file_format": "json"},
                "input_ids": [input_id],
            },
            headers=ch,
        )
        assert r.status_code == 201, r.text
        run = r.json()
        run_id = run["id"]
        assert [i["file_name"] for i in run["inputs"]] == ["hits.json"]
        assert run["inputs"][0]["status"] == "bound"
        # Relocated under the canonical per-run start prefix.
        start_art = next(a for a in run["artifacts"] if a["action_type"] == "start")
        assert f"/v1/{run_id}/start/" in start_art["storage_key"]

        # Download-input yields a presigned URL.
        r = await client.get(f"{API}/{run_id}/download-input", headers=ch)
        assert r.status_code == 200, r.text
        assert r.json()["download_url"]


# ── Output upload + download ──────────────────────────────────────────────────


async def test_output_upload_and_download(api_env: _ApiEnv):
    env = api_env
    transport = ASGITransport(app=__import__("task_service.main", fromlist=["app"]).app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run = await _create_run(client, env)
        run_id = run["id"]
        ah = _headers(env.assignee, env.org_id)
        await client.post(f"{API}/{run_id}/accept", headers=ah)

        # Output upload stages to scratch space (no DB row yet).
        r = await client.post(
            f"{API}/{run_id}/upload-output",
            files={"file": ("result.json", b'{"ok": true}', "application/json")},
            headers=ah,
        )
        assert r.status_code == 201, r.text
        up = r.json()
        assert up["storage_path"].startswith("scratch-space/task-runs/")

        # Submit references the staged file; it's relocated to finish/ + recorded.
        r = await client.post(
            f"{API}/{run_id}/submit",
            json={
                "output_data": {},
                "attachments": [
                    {
                        "storage_path": up["storage_path"],
                        "file_name": up["file_name"],
                        "content_type": "application/json",
                        "file_size": 12,
                    }
                ],
            },
            headers=ah,
        )
        assert r.status_code == 200, r.text
        finish_art = next(a for a in r.json()["artifacts"] if a["action_type"] == "finish")
        assert f"/v1/{run_id}/finish/" in finish_art["storage_key"]

        # The scratch copy is removed after relocation (mirrors input bind).
        from core.storage import get_object_store

        assert get_object_store().list_objects("techneos-data", up["storage_path"]) == []

        r = await client.get(
            f"{API}/{run_id}/download-output",
            params={"file_name": "result.json"},
            headers=ah,
        )
        assert r.status_code == 200, r.text
        assert r.json()["download_url"]


async def test_output_filename_deduped(api_env: _ApiEnv):
    env = api_env
    transport = ASGITransport(app=__import__("task_service.main", fromlist=["app"]).app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run = await _create_run(client, env)
        run_id = run["id"]
        ah = _headers(env.assignee, env.org_id)
        await client.post(f"{API}/{run_id}/accept", headers=ah)

        # Stage the same filename three times (each gets a unique scratch path).
        attachments = []
        for _ in range(3):
            r = await client.post(
                f"{API}/{run_id}/upload-output",
                files={"file": ("result.json", b'{"ok": true}', "application/json")},
                headers=ah,
            )
            assert r.status_code == 201, r.text
            attachments.append(
                {
                    "storage_path": r.json()["storage_path"],
                    "file_name": "result.json",
                    "content_type": "application/json",
                    "file_size": 12,
                }
            )

        # Submit all three — de-duplication happens at finish time.
        r = await client.post(
            f"{API}/{run_id}/submit",
            json={"output_data": {}, "attachments": attachments},
            headers=ah,
        )
        assert r.status_code == 200, r.text
        finish_files = {
            a["file_name"] for a in r.json()["artifacts"] if a["action_type"] == "finish"
        }
        assert finish_files == {"result.json", "result-1.json", "result-2.json"}


# ── Deletion cleans MinIO ─────────────────────────────────────────────────────


async def test_delete_removes_minio_files(api_env: _ApiEnv):
    env = api_env
    transport = ASGITransport(app=__import__("task_service.main", fromlist=["app"]).app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run = await _create_run(client, env)
        run_id = run["id"]
        ah = _headers(env.assignee, env.org_id)
        await client.post(f"{API}/{run_id}/accept", headers=ah)

        up = await client.post(
            f"{API}/{run_id}/upload-output",
            files={"file": ("result.json", b'{"ok": true}', "application/json")},
            headers=ah,
        )
        await client.post(
            f"{API}/{run_id}/submit",
            json={
                "output_data": {},
                "attachments": [
                    {
                        "storage_path": up.json()["storage_path"],
                        "file_name": "result.json",
                        "content_type": "application/json",
                        "file_size": 12,
                    }
                ],
            },
            headers=ah,
        )

        from core.storage import get_object_store

        store = get_object_store()
        run_pref = f"task-runs/{env.tool_slug}/v1/{run_id}/"
        assert store.list_objects("techneos-data", run_pref), "expected a finish file in MinIO"

        # Delete the run → its MinIO files are removed too.
        r = await client.delete(f"{API}/{run_id}", headers=_headers(env.creator, env.org_id))
        assert r.status_code == 204, r.text
        assert store.list_objects("techneos-data", run_pref) == []


# ── Access control ────────────────────────────────────────────────────────────


async def test_outsider_cannot_read(api_env: _ApiEnv):
    env = api_env
    transport = ASGITransport(app=__import__("task_service.main", fromlist=["app"]).app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run = await _create_run(client, env)
        r = await client.get(f"{API}/{run['id']}", headers=_headers(env.outsider, env.org_id))
        assert r.status_code == 403, r.text
