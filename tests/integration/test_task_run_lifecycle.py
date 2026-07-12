"""Integration tests for the unified task-run CRUD lifecycle.

Exercises task_service.crud.runs against a real Postgres (the test DB created
by the integration conftest), covering the action log, the artifact table, the
denormalised current-holder columns, threading, and response shaping.

Requires: docker compose up (Postgres must be running)
Run: make test-integration
     (or: uv run pytest -m integration tests/integration/test_task_run_lifecycle.py)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import select

# Register the full model set on Base.metadata before the session-scoped
# create_all in conftest runs — otherwise cross-model FK targets (e.g.
# object_store_buckets) can't resolve on a fresh test DB.
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
from core.database.postgres import get_session_factory
from core.models.task_run import TaskRun, TaskRunArtifact, TaskRunEvent
from core.models.tool import HumanConfig, Tool, ToolVersion
from core.models.user import Org, User
from core.schemas.task_run import TaskRunDelegate, TaskRunSubmit
from core.storage import ObjectInfo
from task_service.crud.runs import (
    accept_task_run,
    add_update,
    build_response,
    cancel_task_run,
    create_task_run,
    decline_task_run,
    delegate_task_run,
    escalate_task_run,
    list_task_runs,
    submit_task_run,
    user_can_access,
    user_can_act,
)

pytestmark = pytest.mark.integration


@dataclass
class Env:
    org_id: str
    assignee_id: str
    delegatee_id: str
    lead_id: str
    outsider_id: str
    tool: Tool
    version: ToolVersion
    human_config: HumanConfig


async def _mk_user(session, org_id: str, label: str) -> str:
    uid = str(uuid.uuid4())
    session.add(
        User(
            id=uid,
            email=f"{label}-{uid[:8]}@task-test.example",
            full_name=f"{label.title()} {uid[:4]}",
            hashed_password="x",
            org_id=org_id,
        )
    )
    return uid


@pytest.fixture
async def env() -> Env:
    """Create an org/users/tool/version/human_config and return their handles."""
    factory = get_session_factory()
    async with factory() as session:
        org = (await session.execute(select(Org).where(Org.slug == "default"))).scalar_one_or_none()
        if org is None:
            org = Org(id=str(uuid.uuid4()), name="Default", slug="default")
            session.add(org)
            await session.flush()
        org_id = org.id

        assignee_id = await _mk_user(session, org_id, "assignee")
        delegatee_id = await _mk_user(session, org_id, "delegatee")
        lead_id = await _mk_user(session, org_id, "lead")
        outsider_id = await _mk_user(session, org_id, "outsider")

        tool = Tool(
            id=str(uuid.uuid4()),
            name="Hit Triage",
            slug=f"hit-triage-{uuid.uuid4().hex[:8]}",
            org_id=org_id,
            created_by=assignee_id,
            tool_type="human",
        )
        session.add(tool)
        await session.flush()

        version = ToolVersion(
            id=str(uuid.uuid4()),
            tool_id=tool.id,
            version=2,
            created_by=assignee_id,
        )
        session.add(version)
        await session.flush()

        hc = HumanConfig(
            tool_version_id=version.id,
            assignment_type="user",
            due_in_hours=48,
            require_attachments=True,
            priority="medium",
        )
        session.add(hc)
        await session.commit()

        return Env(
            org_id=org_id,
            assignee_id=assignee_id,
            delegatee_id=delegatee_id,
            lead_id=lead_id,
            outsider_id=outsider_id,
            tool=tool,
            version=version,
            human_config=hc,
        )


async def _create(session, env: Env, **overrides) -> TaskRun:
    kwargs = dict(
        org_id=env.org_id,
        tool=env.tool,
        tool_version=env.version,
        human_config=env.human_config,
        pipeline_run_id=None,
        pipeline_step_run_id=None,
        step_name=None,
        input_snapshot={"compound_set": "set-A"},
        assigned_user_id=env.assignee_id,
        assigned_team_slug=None,
        project_lead_id=env.lead_id,
        started_by=env.assignee_id,
        due_at=None,
    )
    kwargs.update(overrides)
    return await create_task_run(session, **kwargs)


# ── Creation ───────────────────────────────────────────────────────────────


async def test_create_sets_holder_and_logs_start(env: Env):
    factory = get_session_factory()
    async with factory() as session:
        tr = await _create(session, env)
        await session.commit()
        tr_id = tr.id

    async with factory() as session:
        tr = (await session.execute(select(TaskRun).where(TaskRun.id == tr_id))).scalar_one()
        assert tr.status == "pending"
        assert tr.outcome is None
        assert tr.assigned_user_id == env.assignee_id
        assert tr.project_lead_id == env.lead_id
        assert tr.require_attachments is True
        assert tr.cfg_due_in_hours == 48
        assert tr.assignment_type == "user"
        assert tr.priority == "medium"
        assert tr.input_params == {"compound_set": "set-A"}

        events = (
            (await session.execute(select(TaskRunEvent).where(TaskRunEvent.task_run_id == tr_id)))
            .scalars()
            .all()
        )
        assert [e.action_type for e in events] == ["start"]


async def test_create_requires_an_assignee(env: Env):
    factory = get_session_factory()
    async with factory() as session:
        with pytest.raises(ValueError):
            await _create(session, env, assigned_user_id=None, assigned_team_slug=None)


# ── Accept → update (threaded) → finish ─────────────────────────────────────


async def test_accept_update_finish_lifecycle(env: Env):
    factory = get_session_factory()
    async with factory() as session:
        tr = await _create(session, env)
        await accept_task_run(session, tr, env.assignee_id)
        assert tr.status == "accepted"
        assert tr.accepted_at is not None

        start_ev = (
            await session.execute(
                select(TaskRunEvent).where(
                    TaskRunEvent.task_run_id == tr.id,
                    TaskRunEvent.action_type == "start",
                )
            )
        ).scalar_one()
        ev = await add_update(
            session,
            tr,
            env.assignee_id,
            message="WIP — first pass attached",
            parent_event_id=start_ev.id,
            attachments=[{"file_name": "wip.csv", "file_size": 5, "storage_path": "k/wip.csv"}],
        )
        assert ev.parent_event_id == start_ev.id
        assert ev.message == "WIP — first pass attached"

        await submit_task_run(
            session,
            tr,
            TaskRunSubmit(
                output_data={"decision": "advance"},
                attachments=[
                    {"file_name": "final.csv", "file_size": 9, "storage_path": "k/final.csv"}
                ],
            ),
            env.assignee_id,
        )
        await session.commit()
        tr_id = tr.id

    async with factory() as session:
        tr = (await session.execute(select(TaskRun).where(TaskRun.id == tr_id))).scalar_one()
        assert tr.status == "terminal"
        assert tr.outcome == "completed"
        assert tr.finished_by == env.assignee_id
        assert tr.finished_at is not None
        assert tr.output_data == {"decision": "advance"}
        assert tr.tool_version_no == env.version.version

        # Artifacts: one update file + one finish file, each linked to its event.
        arts = (
            (
                await session.execute(
                    select(TaskRunArtifact).where(TaskRunArtifact.task_run_id == tr_id)
                )
            )
            .scalars()
            .all()
        )
        by_action = {a.action_type: a for a in arts}
        assert set(by_action) == {"update", "finish"}
        assert all(a.event_id is not None for a in arts)

        resp = await build_response(session, tr)
        # Event history is threaded and carries per-event artifacts.
        actions = [e["action_type"] for e in resp.event_history]
        assert actions == ["start", "accept", "update", "finish"]
        update_ev = next(e for e in resp.event_history if e["action_type"] == "update")
        assert update_ev["parent_event_id"] is not None
        assert len(update_ev["artifacts"]) == 1
        # Output attachments surface both finish + update files.
        assert resp.output_data["decision"] == "advance"
        # output_data.attachments carries finish files only; the update file
        # lives in the update event's artifacts (asserted above).
        assert len(resp.output_data["attachments"]) == 1
        assert resp.display_status == "completed"


# ── Delegate / escalate ─────────────────────────────────────────────────────


async def test_delegate_moves_holder_and_threads(env: Env):
    factory = get_session_factory()
    async with factory() as session:
        tr = await _create(session, env)
        await accept_task_run(session, tr, env.assignee_id)
        await delegate_task_run(
            session,
            tr,
            TaskRunDelegate(to_user_id=env.delegatee_id, reason="please take over"),
            env.assignee_id,
        )
        assert tr.assigned_user_id == env.delegatee_id
        assert tr.status == "pending"
        assert tr.accepted_at is None  # reset on reassignment

        delegate_ev = (
            await session.execute(
                select(TaskRunEvent).where(
                    TaskRunEvent.task_run_id == tr.id,
                    TaskRunEvent.action_type == "delegate",
                )
            )
        ).scalar_one()
        # Threaded under a prior holder action (the start event).
        assert delegate_ev.parent_event_id is not None
        assert delegate_ev.payload["to_user_id"] == env.delegatee_id

        resp = await build_response(session, tr)
        # Back-compat delegation_history is populated from the event log.
        assert any(d["event_type"] == "delegate" for d in resp.delegation_history)


async def test_escalate_to_project_lead(env: Env):
    factory = get_session_factory()
    async with factory() as session:
        tr = await _create(session, env)
        await escalate_task_run(session, tr)
        assert tr.assigned_user_id == env.lead_id
        assert tr.status == "pending"

        resp = await build_response(session, tr)
        assert resp.display_status == "escalated"
        assert resp.escalated_at is not None

        # Idempotent once already with the lead.
        await escalate_task_run(session, tr)
        escalations = (
            (
                await session.execute(
                    select(TaskRunEvent).where(
                        TaskRunEvent.task_run_id == tr.id,
                        TaskRunEvent.action_type == "escalate",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(escalations) == 1


async def test_escalate_without_lead_raises(env: Env):
    factory = get_session_factory()
    async with factory() as session:
        tr = await _create(session, env, project_lead_id=None)
        with pytest.raises(ValueError):
            await escalate_task_run(session, tr)


# ── Decline / cancel ─────────────────────────────────────────────────────────


async def test_decline(env: Env):
    factory = get_session_factory()
    async with factory() as session:
        tr = await _create(session, env)
        await decline_task_run(session, tr, env.assignee_id, reason="not my area")
        assert tr.status == "terminal"
        assert tr.outcome == "declined"
        # finished_at is the unified terminal timestamp (replaces completed_at).
        assert tr.finished_at is not None
        assert tr.finished_by == env.assignee_id
        resp = await build_response(session, tr)
        assert resp.display_status == "declined"


async def test_cancel(env: Env):
    factory = get_session_factory()
    async with factory() as session:
        tr = await _create(session, env)
        await cancel_task_run(session, tr, env.assignee_id)
        assert tr.status == "terminal"
        assert tr.outcome == "cancelled"
        # Cancelling a terminal run is a no-op.
        await cancel_task_run(session, tr, env.assignee_id)
        cancels = (
            (
                await session.execute(
                    select(TaskRunEvent).where(
                        TaskRunEvent.task_run_id == tr.id,
                        TaskRunEvent.action_type == "cancel",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(cancels) == 1


# ── Staged input binding (copy-on-bind) ──────────────────────────────────────


class _FakeStore:
    """In-memory object store. Staged files live only here (scratch space),
    not in the DB — binding must reconstruct metadata via list_objects and
    read content via get (for input validation)."""

    def __init__(self):
        self.objects: dict[str, ObjectInfo] = {}
        self.contents: dict[str, bytes] = {}
        self.copies: list[tuple] = []
        self.deletes: list[tuple] = []

    def list_objects(self, bucket, prefix=""):
        return [o for k, o in self.objects.items() if k.startswith(prefix)]

    def get(self, bucket, key, max_bytes=None):
        data = self.contents.get(key, b"")
        return data[:max_bytes] if max_bytes else data

    def copy(self, sb, sk, db, dk):
        self.copies.append((sb, sk, db, dk))
        return dk

    def delete(self, bucket, key):
        self.deletes.append((bucket, key))
        self.objects.pop(key, None)


async def test_bind_staged_inputs_copies_to_canonical_key(env: Env, monkeypatch):
    from task_service.storage_keys import input_staging_key

    fake = _FakeStore()
    monkeypatch.setattr("core.storage.get_object_store", lambda: fake)

    # Simulate a staged upload sitting in scratch space (no DB row). The bind
    # path validates the file content, so provide valid JSON compound data.
    input_id = str(uuid.uuid4())
    skey = input_staging_key(env.tool.slug, env.version.version, input_id, "hits.json")
    content = b'[{"smiles": "CCO", "id": "c1"}]'
    fake.objects[skey] = ObjectInfo(
        bucket="techneos-data", key=skey, size=len(content), content_type="application/json"
    )
    fake.contents[skey] = content

    factory = get_session_factory()
    async with factory() as session:
        tr = await _create(
            session,
            env,
            input_artifact_ids=[input_id],
            input_snapshot={"input_file_format": "json"},
        )
        await session.commit()
        tr_id, run_slug, run_v = tr.id, tr.tool_slug, env.version.version

    async with factory() as session:
        art = (
            await session.execute(select(TaskRunArtifact).where(TaskRunArtifact.id == input_id))
        ).scalar_one()
        assert art.task_run_id == tr_id
        assert art.status == "bound"
        assert art.action_type == "start"
        assert art.event_id is not None
        assert art.file_name == "hits.json"
        assert art.file_size == len(content)
        assert art.content_type == "application/json"
        # Flat layout: file sits directly under {action_type}/, no artifact-id segment.
        assert art.storage_key == f"task-runs/{run_slug}/v{run_v}/{tr_id}/start/hits.json"

    # Copied from scratch → canonical, then scratch copy deleted.
    assert len(fake.copies) == 1
    assert len(fake.deletes) == 1
    assert skey not in fake.objects

    async with factory() as session:
        tr = (await session.execute(select(TaskRun).where(TaskRun.id == tr_id))).scalar_one()
        resp = await build_response(session, tr)
        assert [i.file_name for i in resp.inputs] == ["hits.json"]
        assert resp.inputs[0].status == "bound"


# ── Visibility + listing ─────────────────────────────────────────────────────


async def test_visibility_and_list_filter(env: Env):
    factory = get_session_factory()
    async with factory() as session:
        tr = await _create(session, env)
        await session.commit()
        tr_id = tr.id

    async with factory() as session:
        tr = (await session.execute(select(TaskRun).where(TaskRun.id == tr_id))).scalar_one()
        # Holder and lead can access + act; outsider cannot.
        assert await user_can_access(session, tr, env.assignee_id, None, False)
        assert await user_can_access(session, tr, env.lead_id, None, False)
        assert not await user_can_access(session, tr, env.outsider_id, None, False)
        assert await user_can_act(session, tr, env.assignee_id, None)
        assert not await user_can_act(session, tr, env.outsider_id, None)

        items, _ = await list_task_runs(
            session, org_id=env.org_id, user_id=env.assignee_id, status="pending"
        )
        assert any(i.id == tr_id for i in items)
        # Outsider's list does not include it.
        items_out, _ = await list_task_runs(session, org_id=env.org_id, user_id=env.outsider_id)
        assert all(i.id != tr_id for i in items_out)
