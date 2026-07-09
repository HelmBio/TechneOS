"""CRUD for task-service (human task runs).

The state model is one ``TaskRun`` row carrying the current holder + final
submission, an append-only ``TaskRunEvent`` log of *actions*, and a single
``TaskRunArtifact`` table for every file (tagged with the ``action_type`` that
produced it). The old assignment chain is gone — the holder lives on the row
and history is reconstructed from start/delegate/escalate events.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions import NotFoundError
from core.models.task_run import TaskRun, TaskRunArtifact, TaskRunEvent
from core.models.tool import HumanConfig, Tool, ToolVersion
from core.models.user import Team, User
from core.schemas.task_run import (
    TaskRunArtifactInfo,
    TaskRunDelegate,
    TaskRunInputInfo,
    TaskRunListItem,
    TaskRunResponse,
    TaskRunSubmit,
)
from core.task_actions import DEFAULT_ACTION_SLUGS
from task_service.storage_keys import (
    STAGING_PREFIX,
    action_prefix,
    input_staging_prefix,
    next_available_name,
    output_staging_prefix,
    run_prefix,
)

logger = logging.getLogger(__name__)

# Artifact action buckets for response shaping.
_INPUT_ACTIONS = ("start",)
_OUTPUT_ACTIONS = ("finish",)


# ── Loading ──────────────────────────────────────────────────────────────


async def get_task_run(session: AsyncSession, task_run_id: str) -> TaskRun:
    """Fetch a TaskRun by id with the creator eagerly loaded."""
    result = await session.execute(
        select(TaskRun).options(selectinload(TaskRun.starter)).where(TaskRun.id == task_run_id)
    )
    tr = result.scalar_one_or_none()
    if tr is None:
        raise NotFoundError("TaskRun", task_run_id)
    return tr


async def delete_task_run(session: AsyncSession, task_run_id: str) -> int:
    """Hard-delete a TaskRun and all its MinIO files.

    Satellite rows (events, artifacts) cascade automatically via the
    ``ondelete='CASCADE'`` FKs. The run's object-storage files are not covered
    by FKs, so we delete everything under the run prefix
    (``task-runs/{slug}/v{N}/{run_id}/``) explicitly. Returns the number of
    objects removed. Storage failures are logged, not fatal — the DB row is
    still deleted.
    """
    tr = await get_task_run(session, task_run_id)

    deleted = 0
    try:
        from core.storage import get_object_store

        store = get_object_store()
        bucket = "techneos-data"
        # Canonical run files + any leftover run-scoped output scratch.
        prefixes = [
            run_prefix(tool_slug=tr.tool_slug, version=tr.tool_version_no or 0, task_run_id=tr.id),
            output_staging_prefix(tr.tool_slug, tr.tool_version_no or 0, tr.id),
        ]
        for prefix in prefixes:
            for obj in store.list_objects(bucket, prefix):
                try:
                    store.delete(bucket, obj.key)
                    deleted += 1
                except Exception as e:  # pragma: no cover
                    logger.warning("Failed to delete object %s: %s", obj.key, e)
    except Exception as e:  # pragma: no cover
        logger.warning("Failed to enumerate MinIO files for run %s: %s", task_run_id, e)

    await session.delete(tr)
    await session.flush()
    logger.info("Deleted task run %s and %d MinIO object(s)", task_run_id, deleted)
    return deleted


_OUTCOME_TO_DISPLAY = {
    "completed": "completed",
    "declined": "declined",
    "cancelled": "cancelled",
    "expired": "cancelled",
}


def _merge_outputs(
    output_data: dict[str, Any] | None, artifacts: list[TaskRunArtifact]
) -> dict[str, Any] | None:
    """Merge output/update artifacts into the submission's output_data dict.

    Populates an ``attachments`` key from the output artifacts so the frontend
    can render JSON data and uploaded files together.
    """
    if output_data is None:
        return None
    outputs = [a for a in artifacts if a.action_type in _OUTPUT_ACTIONS]
    if not outputs:
        return output_data
    merged = dict(output_data)
    merged["attachments"] = [
        {
            "file_name": a.file_name,
            "storage_path": a.storage_key,
            "file_size": a.file_size,
            "content_type": a.content_type,
        }
        for a in outputs
    ]
    return merged


def _display_status(status: str, outcome: str | None, escalated_at: object | None) -> str:
    """Collapse (status, outcome, escalation) into one UI label."""
    if escalated_at is not None:
        return "escalated"
    if status == "terminal":
        return _OUTCOME_TO_DISPLAY.get(outcome or "", "cancelled")
    if status == "in_progress":
        return "in progress"
    return status


def _artifact_info(a: TaskRunArtifact) -> TaskRunArtifactInfo:
    return TaskRunArtifactInfo(
        id=a.id,
        action_type=a.action_type,
        name=a.name,
        file_name=a.file_name,
        file_size=a.file_size,
        content_type=a.content_type,
        storage_key=a.storage_key,
        status=a.status,
        event_id=a.event_id,
    )


# ── Listing ──────────────────────────────────────────────────────────────


def _participant_event_subq(user_id: str) -> Any:
    """Task-run ids the user has touched via the event log (past holders)."""
    return select(TaskRunEvent.task_run_id).where(
        or_(
            TaskRunEvent.actor_user_id == user_id,
            TaskRunEvent.payload["to_user_id"].astext == user_id,
            TaskRunEvent.payload["escalated_to"].astext == user_id,
            TaskRunEvent.payload["assigned_user_id"].astext == user_id,
        )
    )


def _visibility_clause(user_id: str, team_slug: str | None) -> Any:
    """Rows the caller may see: holder, lead, creator, team, past participant."""
    clause = or_(
        TaskRun.started_by == user_id,
        TaskRun.finished_by == user_id,
        TaskRun.assigned_user_id == user_id,
        TaskRun.project_lead_id == user_id,
        TaskRun.id.in_(_participant_event_subq(user_id)),
    )
    if team_slug:
        clause = or_(clause, TaskRun.assigned_team_slug == team_slug)
    return clause


async def list_task_runs(
    session: AsyncSession,
    org_id: str,
    user_id: str,
    team_slug: str | None = None,
    tool_slug: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[TaskRunListItem], int]:
    """List task runs visible to the caller. Org-scoped throughout."""
    conditions = [TaskRun.org_id == org_id, _visibility_clause(user_id, team_slug)]
    if tool_slug:
        conditions.append(TaskRun.tool_slug == tool_slug)
    if status:
        values = [s.strip() for s in status.split(",") if s.strip()]
        if values:
            status_conditions: list[Any] = []
            for s in values:
                if s in ("pending", "accepted", "in_progress"):
                    status_conditions.append(TaskRun.status == s)
                elif s == "completed":
                    status_conditions.append(
                        and_(TaskRun.status == "terminal", TaskRun.outcome == "completed")
                    )
                elif s == "declined":
                    status_conditions.append(
                        and_(TaskRun.status == "terminal", TaskRun.outcome == "declined")
                    )
                elif s == "cancelled":
                    status_conditions.append(
                        and_(TaskRun.status == "terminal", TaskRun.outcome == "cancelled")
                    )
                elif s == "escalated":
                    escalated_subq = (
                        select(TaskRunEvent.task_run_id)
                        .where(
                            TaskRunEvent.action_type == "escalate",
                            TaskRunEvent.task_run_id == TaskRun.id,
                        )
                        .correlate(TaskRun)
                        .exists()
                    )
                    status_conditions.append(and_(TaskRun.status != "terminal", escalated_subq))
            if status_conditions:
                conditions.append(or_(*status_conditions))

    total_q = select(func.count(TaskRun.id)).where(and_(*conditions))
    total = (await session.execute(total_q)).scalar() or 0

    q = (
        select(TaskRun)
        .options(
            selectinload(TaskRun.starter),
            selectinload(TaskRun.assigned_user),
            selectinload(TaskRun.finisher),
            selectinload(TaskRun.artifacts),
        )
        .where(and_(*conditions))
        .order_by(TaskRun.started_at.desc())
        .offset(skip)
    )
    if limit == 0:
        q = q.limit(0)
    elif limit > 0:
        q = q.limit(limit)
    rows = list((await session.execute(q)).scalars().all())

    team_slugs = {r.assigned_team_slug for r in rows if r.assigned_team_slug}
    team_names: dict[str, str] = {}
    if team_slugs:
        t_q = select(Team).where(Team.org_id == org_id, Team.slug.in_(team_slugs))
        for team in (await session.execute(t_q)).scalars():
            team_names[team.slug] = team.name

    items: list[TaskRunListItem] = []
    for r in rows:
        items.append(
            TaskRunListItem(
                id=r.id,
                org_id=r.org_id,
                tool_id=r.tool_id,
                tool_slug=r.tool_slug,
                tool_version_id=r.tool_version_id,
                tool_version_num=r.tool_version_no,
                status=r.status,
                outcome=r.outcome,
                display_status=_display_status(r.status, r.outcome, None),
                assigned_user_id=r.assigned_user_id,
                assigned_user_name=(r.assigned_user.full_name if r.assigned_user else None),
                assigned_team_slug=r.assigned_team_slug,
                assigned_team_name=(
                    team_names.get(r.assigned_team_slug) if r.assigned_team_slug else None
                ),
                project_lead_id=r.project_lead_id,
                due_at=r.due_at,
                accepted_at=r.accepted_at,
                pipeline_run_id=r.pipeline_run_id,
                step_name=r.step_name,
                started_by=r.started_by,
                started_by_name=(r.starter.full_name if r.starter else None),
                started_at=r.started_at,
                updated_at=r.updated_at,
                tool_run_id=None,
                input_snapshot=r.input_params or {},
                finished_by=r.finished_by,
                finished_by_name=(r.finisher.full_name if r.finisher else None),
                finished_at=r.finished_at,
                output_data=_merge_outputs(r.output_data, r.artifacts or []),
                delegation_history=[],
            )
        )
    return items, total


# ── Response shaping ─────────────────────────────────────────────────────


async def build_response(session: AsyncSession, tr: TaskRun) -> TaskRunResponse:
    """Project a TaskRun into the API response shape.

    Self-sufficient — fetches related rows explicitly so it works for both
    freshly-created TaskRuns and ones loaded via get_task_run.
    """
    art_q = await session.execute(
        select(TaskRunArtifact).where(TaskRunArtifact.task_run_id == tr.id)
    )
    artifacts = list(art_q.scalars())

    assigned_user_name = None
    if tr.assigned_user_id:
        u = await session.get(User, tr.assigned_user_id)
        assigned_user_name = u.full_name if u else None
    assigned_team_name = None
    if tr.assigned_team_slug:
        team_q = await session.execute(
            select(Team).where(Team.org_id == tr.org_id, Team.slug == tr.assigned_team_slug)
        )
        team = team_q.scalar_one_or_none()
        assigned_team_name = team.name if team else None
    project_lead_name = None
    if tr.project_lead_id:
        u = await session.get(User, tr.project_lead_id)
        project_lead_name = u.full_name if u else None
    finished_by_name = None
    if tr.finished_by:
        u = await session.get(User, tr.finished_by)
        finished_by_name = u.full_name if u else None
    started_by_name = None
    if tr.started_by:
        starter = await session.get(User, tr.started_by)
        started_by_name = starter.full_name if starter else None

    output_schema: dict[str, Any] = {}
    input_schema: dict[str, Any] = {}
    if tr.tool_version_id:
        tv = await session.get(ToolVersion, tr.tool_version_id)
        if tv:
            output_schema = tv.output_schema or {}
            input_schema = tv.input_schema or {}

    events_q = await session.execute(
        select(TaskRunEvent)
        .where(TaskRunEvent.task_run_id == tr.id)
        .order_by(TaskRunEvent.occurred_at)
    )
    events = list(events_q.scalars())

    # Resolve user_ids → emails for human-readable identifiers.
    user_ids: set[str] = set()
    for ev in events:
        if ev.actor_user_id:
            user_ids.add(ev.actor_user_id)
        payload = ev.payload or {}
        for key in ("to_user_id", "escalated_to", "assigned_user_id"):
            v = payload.get(key)
            if v:
                user_ids.add(v)
    email_by_id: dict[str, str] = {}
    if user_ids:
        u_q = await session.execute(select(User).where(User.id.in_(user_ids)))
        for u in u_q.scalars():
            email_by_id[u.id] = u.email

    def _label(uid: str | None) -> str | None:
        if not uid:
            return None
        return email_by_id.get(uid, uid)

    # Group artifacts by the event that produced them.
    artifacts_by_event: dict[str, list[TaskRunArtifact]] = {}
    for a in artifacts:
        if a.event_id:
            artifacts_by_event.setdefault(a.event_id, []).append(a)

    delegation_history: list[dict[str, Any]] = []
    event_history: list[dict[str, Any]] = []
    escalated_at: datetime | None = None

    for ev in events:
        payload = ev.payload or {}
        actor_label = _label(ev.actor_user_id) or ("system" if ev.actor_type == "system" else "—")
        target_label: str | None = None
        detail: str | None = None

        if ev.action_type == "start":
            target_label = _label(payload.get("assigned_user_id")) or payload.get(
                "assigned_team_slug"
            )
            detail = f"assigned to {target_label}" if target_label else "created"
        elif ev.action_type == "accept":
            detail = "accepted"
        elif ev.action_type == "decline":
            detail = payload.get("reason") or "declined"
        elif ev.action_type == "delegate":
            target_label = _label(payload.get("to_user_id"))
            detail = payload.get("reason") or "delegated"
        elif ev.action_type == "escalate":
            target_label = _label(payload.get("escalated_to"))
            detail = "escalated (overdue)"
            escalated_at = ev.occurred_at
        elif ev.action_type == "finish":
            detail = "submitted"
        elif ev.action_type == "cancel":
            detail = "cancelled"
        elif ev.action_type == "update":
            detail = ev.message or "update"
        elif ev.action_type == "remind":
            detail = payload.get("kind") or "reminder"
        else:
            detail = ev.action_type

        ev_artifacts = artifacts_by_event.get(ev.id, [])
        event_history.append(
            {
                "id": ev.id,
                "parent_event_id": ev.parent_event_id,
                "action_type": ev.action_type,
                "event_type": ev.action_type,  # back-compat alias
                "actor": actor_label,
                "target": target_label,
                "detail": detail,
                "message": ev.message,
                "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
                "payload": payload,
                "artifacts": [_artifact_info(a).model_dump() for a in ev_artifacts],
            }
        )

        # Back-compat: legacy delegation_history carried delegate/escalate rows.
        if ev.action_type in ("delegate", "escalate"):
            delegation_history.append(
                {
                    "from": actor_label,
                    "to": target_label,
                    "assigned_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
                    "due_at": payload.get("new_due_at"),
                    "reason": detail,
                    "event_type": ev.action_type,
                }
            )

    inputs = [a for a in artifacts if a.action_type in _INPUT_ACTIONS]

    return TaskRunResponse(
        id=tr.id,
        org_id=tr.org_id,
        tool_id=tr.tool_id,
        tool_slug=tr.tool_slug,
        tool_version_id=tr.tool_version_id,
        tool_version_num=tr.tool_version_no,
        pipeline_run_id=tr.pipeline_run_id,
        pipeline_step_run_id=tr.pipeline_step_run_id,
        step_name=tr.step_name,
        input_snapshot=tr.input_params or {},
        status=tr.status,
        outcome=tr.outcome,
        display_status=_display_status(tr.status, tr.outcome, escalated_at),
        assigned_user_id=tr.assigned_user_id,
        assigned_team_slug=tr.assigned_team_slug,
        project_lead_id=tr.project_lead_id,
        due_at=tr.due_at,
        original_due_at=tr.original_due_at,
        accepted_at=tr.accepted_at,
        snapshot_require_attachments=tr.require_attachments,
        snapshot_due_in_hours=tr.cfg_due_in_hours,
        snapshot_assignment_type=tr.assignment_type,
        started_by=tr.started_by,
        started_at=tr.started_at,
        updated_at=tr.updated_at,
        output_data=_merge_outputs(tr.output_data, artifacts),
        output_schema=output_schema,
        input_schema=input_schema,
        finished_by=tr.finished_by,
        finished_at=tr.finished_at,
        assigned_user_name=assigned_user_name,
        assigned_team_name=assigned_team_name,
        started_by_name=started_by_name,
        finished_by_name=finished_by_name,
        project_lead_name=project_lead_name,
        tool_run_id=None,
        escalated_at=escalated_at,
        delegation_history=delegation_history,
        require_attachments=tr.require_attachments,
        event_history=event_history,
        inputs=[
            TaskRunInputInfo(
                id=a.id,
                file_name=a.file_name,
                file_size=a.file_size,
                storage_key=a.storage_key,
                status=a.status,
            )
            for a in inputs
        ],
        artifacts=[_artifact_info(a) for a in artifacts],
    )


# ── Visibility checks ────────────────────────────────────────────────────


async def user_can_access(
    session: AsyncSession,
    tr: TaskRun,
    user_id: str,
    user_team_slug: str | None,
    is_admin: bool,
) -> bool:
    """Return True if the user is allowed to read this task run."""
    if is_admin:
        return True
    if tr.started_by == user_id:
        return True
    if tr.finished_by == user_id:
        return True
    if tr.assigned_user_id == user_id:
        return True
    if tr.project_lead_id == user_id:
        return True
    if user_team_slug and tr.assigned_team_slug == user_team_slug:
        return True
    # Past participant via the event log.
    seen = await session.execute(
        _participant_event_subq(user_id).where(TaskRunEvent.task_run_id == tr.id).limit(1)
    )
    return seen.scalar_one_or_none() is not None


async def user_can_act(
    session: AsyncSession,
    tr: TaskRun,
    user_id: str,
    user_team_slug: str | None,
) -> bool:
    """Return True if the user can act on the current holder.

    Acting = accept / submit / decline / delegate / update. The current
    assignee (user or team member) plus the project lead may act.
    """
    if tr.assigned_user_id == user_id:
        return True
    if tr.project_lead_id == user_id:
        return True
    return bool(user_team_slug and tr.assigned_team_slug == user_team_slug)


# ── Validation ──────────────────────────────────────────────────────────


def _validate_schema(schema: dict[str, Any], data: dict[str, Any], label: str = "output") -> None:
    """Validate ``data`` against a JSON Schema-like object.

    Checks:
    - Required properties are present and non-empty.
    - No unknown properties (extra keys not in schema.properties).
    - Property value types match the schema (string, number, integer, boolean).

    An empty schema (no properties) accepts any data.
    """
    props: dict[str, Any] = schema.get("properties") or {}
    if not props:
        return  # No constraints defined — anything goes.

    required: list[str] = schema.get("required") or []
    allowed = set(props)

    unknown = [k for k in data if k not in allowed]
    if unknown:
        raise ValueError(
            f"Unknown {label} fields: {', '.join(unknown)}. Allowed: {', '.join(sorted(allowed))}"
        )

    for field in required:
        if field not in data or data[field] is None or data[field] == "":
            raise ValueError(f"Missing required {label} field: {field}")

    for key, value in data.items():
        prop = props.get(key) or {}
        ptype = prop.get("type", "")
        if ptype == "string" and not isinstance(value, str):
            raise ValueError(
                f"{label.title()} field '{key}' must be a string, got {type(value).__name__}"
            )
        if ptype == "number" and not isinstance(value, (int, float)):
            raise ValueError(
                f"{label.title()} field '{key}' must be a number, got {type(value).__name__}"
            )
        if ptype == "integer" and not isinstance(value, int):
            raise ValueError(
                f"{label.title()} field '{key}' must be an integer, got {type(value).__name__}"
            )
        if ptype == "boolean" and not isinstance(value, bool):
            raise ValueError(
                f"{label.title()} field '{key}' must be a boolean, got {type(value).__name__}"
            )


# ── Mutations ────────────────────────────────────────────────────────────


def _validate_output_file(
    store: Any,
    bucket: str,
    key: str,
    expected_format: str,
    output_schema: dict[str, Any],
) -> None:
    """Validate an uploaded output file matches the expected format and
    conforms to the output schema schema."""
    fmt = (expected_format or "json").lower()
    allowed_formats = {"sdf", "csv", "tsv", "json", "txt"}
    if fmt not in allowed_formats:
        return  # Binary format (e.g. xlsx) — skip content validation.

    raw = store.get(bucket, key, max_bytes=65536)
    if not raw or not raw.strip():
        raise ValueError("Output file is empty")

    parsed: Any = None
    if fmt in ("json", "txt"):
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Output file is not valid JSON: {e}") from e
    elif fmt == "csv":
        try:
            text = raw.decode("utf-8", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        except Exception as e:
            raise ValueError(f"Output file is not valid CSV: {e}") from e
        if not rows:
            raise ValueError("CSV output file has no data rows")
    elif fmt == "tsv":
        try:
            text = raw.decode("utf-8", errors="replace")
            reader = csv.DictReader(io.StringIO(text), delimiter="\t")
            rows = list(reader)
        except Exception as e:
            raise ValueError(f"Output file is not valid TSV: {e}") from e
        if not rows:
            raise ValueError("TSV output file has no data rows")
    elif fmt == "sdf":
        text = raw.decode("utf-8", errors="replace")
        blocks = [b for b in text.split("$$$$") if b.strip()]
        if not blocks:
            raise ValueError("SDF output file contains no valid records")

    # Validate parsed JSON data against output_schema.
    props = (output_schema.get("properties") or {}) if output_schema else {}
    if parsed is not None and props:
        _validate_schema(output_schema, parsed if isinstance(parsed, dict) else {}, label="output")


def _now() -> datetime:
    return datetime.now(UTC)


def _log_event(
    session: AsyncSession,
    tr: TaskRun,
    action_type: str,
    actor_user_id: str | None,
    actor_type: str = "user",
    payload: dict[str, Any] | None = None,
    parent_event_id: str | None = None,
    message: str | None = None,
) -> TaskRunEvent:
    """Append an action to the event log and return it.

    Built-in transitions must use a slug from the default vocabulary; this
    guards against typos. Runtime-extended slugs are validated by callers
    against the platform list before reaching here.
    """
    assert action_type in DEFAULT_ACTION_SLUGS, f"unknown action_type {action_type!r}"
    ev = TaskRunEvent(
        id=str(uuid.uuid4()),
        task_run_id=tr.id,
        action_type=action_type,
        actor_user_id=actor_user_id,
        actor_type=actor_type,
        payload=payload or {},
        parent_event_id=parent_event_id,
        message=message,
        occurred_at=_now(),
    )
    session.add(ev)
    return ev


async def _latest_event_id(
    session: AsyncSession, tr: TaskRun, action_types: tuple[str, ...]
) -> str | None:
    """Most recent event id of the given action types (for threading)."""
    q = (
        select(TaskRunEvent.id)
        .where(
            TaskRunEvent.task_run_id == tr.id,
            TaskRunEvent.action_type.in_(action_types),
        )
        .order_by(TaskRunEvent.occurred_at.desc())
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none()


def _validate_input_file(
    store: Any,
    bucket: str,
    key: str,
    expected_format: str,
) -> None:
    """Validate an uploaded input file matches the expected format and contains
    valid compound data.

    ``expected_format`` is the run's ``input_file_format`` parameter value (the
    single source of truth for format); there is no separate ``file_format``
    property on ``input_schema``.
    """
    fmt = (expected_format or "json").lower()

    allowed_formats = {"sdf", "csv", "tsv", "json", "txt"}
    if fmt not in allowed_formats:
        raise ValueError(
            f"Unsupported input file format '{fmt}'. Allowed: {', '.join(sorted(allowed_formats))}"
        )

    # Read the first 64 KB for sampling.
    raw = store.get(bucket, key, max_bytes=65536)
    if not raw or not raw.strip():
        raise ValueError("Input file is empty")

    if fmt in ("json", "txt"):
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Input file is not valid JSON: {e}") from e
        if isinstance(data, dict):
            # Single record — wrap.
            data = [data]
        if not isinstance(data, list) or len(data) == 0:
            raise ValueError("Input JSON must be a non-empty array of compound objects")
        # Check that at least one record has a compound-like field.
        compound_fields = {"smiles", "smile", "canonical_smiles", "id", "compound_id", "name"}
        has_compound = any(
            isinstance(item, dict) and any(k.lower() in compound_fields for k in item)
            for item in data
        )
        if not has_compound:
            raise ValueError(
                "Input JSON does not contain compound data. "
                "Each record should have a field like 'smiles' or 'id'."
            )
    elif fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        try:
            text = raw.decode("utf-8", errors="replace")
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            rows = list(reader)
        except Exception as e:
            raise ValueError(f"Input file is not valid CSV: {e}") from e
        if not rows:
            raise ValueError("CSV file has no data rows")
        headers = set(h.lower() for h in (reader.fieldnames or []))
        compound_fields = {"smiles", "smile", "canonical_smiles", "id", "compound_id", "name"}
        if not headers & compound_fields:
            # Detect delimiter mismatch (e.g. TSV file parsed as CSV).
            sample = text.split("\n", 2)
            sample[1] if len(sample) > 1 else ""
            hint = ""
            if fmt == "csv" and "\t" in (reader.fieldnames or [""])[0]:
                hint = "File appears to be TSV (tab-delimited) but CSV (comma-delimited) was expected. "
            elif fmt == "tsv" and "," in (reader.fieldnames or [""])[0]:
                hint = "File appears to be CSV (comma-delimited) but TSV (tab-delimited) was expected. "
            raise ValueError(
                hint + "File is missing compound columns. "
                "Expected at least one of: " + ", ".join(sorted(compound_fields))
            )
    elif fmt == "sdf":
        text = raw.decode("utf-8", errors="replace")
        # Count SDF records by "$$$$" delimiter.
        blocks = [b for b in text.split("$$$$") if b.strip()]
        if len(blocks) == 0:
            raise ValueError("SDF file contains no valid records (no '$$$$' delimiters found)")


async def _bind_input_artifacts(
    session: AsyncSession,
    tr: TaskRun,
    tool_version: ToolVersion,
    input_ids: list[str],
    event_id: str | None,
    input_file_format: str | None = None,
) -> None:
    """Bind scratch-space ``start`` inputs to a freshly-created run.

    Staged uploads live only in scratch space (no DB row). For each id we
    locate the object under its scratch prefix, copy it to the canonical
    per-run key, create the ``task_run_artifacts`` row (status ``bound``,
    linked to the start event), and best-effort delete the scratch copy.
    """
    if not input_ids:
        return
    from core.storage import get_object_store

    store = get_object_store()
    bucket = "techneos-data"
    prefix = action_prefix(
        tool_slug=tr.tool_slug,
        version=tool_version.version,
        task_run_id=tr.id,
        action_type="start",
    )
    # Track names already used in this action so a batch of identically-named
    # inputs gets -1, -2, … appended.
    used = {o.key.rsplit("/", 1)[-1] for o in store.list_objects(bucket, prefix)}
    for input_id in input_ids:
        objs = store.list_objects(bucket, input_staging_prefix(tr.tool_slug, tool_version.version, input_id))
        if not objs:
            logger.warning("Staged input %s not found in scratch space; skipping", input_id)
            continue
        obj = objs[0]
        file_name = next_available_name(used, obj.key.rsplit("/", 1)[-1])
        used.add(file_name)

        # Validate the staged file before binding.
        try:
            _validate_input_file(store, bucket, obj.key, input_file_format or "")
        except ValueError as e:
            raise ValueError(f"Input file '{file_name}' is invalid: {e}") from e

        dest = f"{prefix}{file_name}"
        try:
            store.copy(bucket, obj.key, bucket, dest)
        except Exception as e:  # pragma: no cover — leave scratch copy on failure
            logger.warning("Failed to relocate staged input %s: %s", input_id, e)
            continue
        session.add(
            TaskRunArtifact(
                id=input_id,
                task_run_id=tr.id,
                org_id=tr.org_id,
                action_type="start",
                event_id=event_id,
                name=file_name,
                file_name=file_name,
                file_size=obj.size,
                content_type=obj.content_type or "application/octet-stream",
                storage_bucket=bucket,
                storage_key=dest,
                status="bound",
                created_by=tr.started_by,
            )
        )
        with contextlib.suppress(Exception):  # pragma: no cover
            store.delete(bucket, obj.key)


async def create_task_run(
    session: AsyncSession,
    *,
    org_id: str,
    tool: Tool,
    tool_version: ToolVersion,
    human_config: HumanConfig | None,
    pipeline_run_id: str | None,
    pipeline_step_run_id: str | None,
    step_name: str | None,
    input_snapshot: dict[str, Any],
    assigned_user_id: str | None,
    assigned_team_slug: str | None,
    project_lead_id: str | None,
    started_by: str,
    due_at: datetime | None,
    input_artifact_ids: list[str] | None = None,
    priority: str | None = None,
) -> TaskRun:
    """Create a TaskRun + its 'start' action, binding any staged inputs."""
    if not assigned_user_id and not assigned_team_slug:
        raise ValueError("At least one of assigned_user_id / assigned_team_slug must be set")
    if assigned_user_id and assigned_team_slug:
        raise ValueError("assigned_user_id and assigned_team_slug are mutually exclusive")

    # Validate input_snapshot — nothing to validate against input_schema here;
    # input_schema describes the input file content, not the parameter snapshot.

    require_attachments = bool(human_config.require_attachments) if human_config else False
    cfg_due_in_hours = human_config.due_in_hours if human_config else None
    assignment_type = (
        human_config.assignment_type if human_config else ("user" if assigned_user_id else "team")
    )
    resolved_priority = priority or (human_config.priority if human_config else None) or "medium"

    tr_id = str(uuid.uuid4())
    tr = TaskRun(
        id=tr_id,
        org_id=org_id,
        tool_id=tool.id,
        tool_slug=tool.slug,
        tool_version_id=tool_version.id,
        tool_version_no=tool_version.version,
        pipeline_run_id=pipeline_run_id,
        pipeline_step_run_id=pipeline_step_run_id,
        step_name=step_name,
        input_params=input_snapshot or {},
        status="pending",
        outcome=None,
        assigned_user_id=assigned_user_id,
        assigned_team_slug=assigned_team_slug,
        project_lead_id=project_lead_id,
        due_at=due_at,
        original_due_at=due_at,
        require_attachments=require_attachments,
        cfg_due_in_hours=cfg_due_in_hours,
        assignment_type=assignment_type,
        priority=resolved_priority,
        started_by=started_by,
        started_at=_now(),
    )
    session.add(tr)
    await session.flush()

    ev = _log_event(
        session,
        tr,
        "start",
        actor_user_id=started_by,
        actor_type="user",
        payload={
            "assigned_user_id": assigned_user_id,
            "assigned_team_slug": assigned_team_slug,
            "project_lead_id": project_lead_id,
        },
    )
    await session.flush()  # populate ev.id

    await _bind_input_artifacts(
        session,
        tr,
        tool_version,
        input_artifact_ids or [],
        ev.id,
        input_file_format=(input_snapshot or {}).get("input_file_format"),
    )
    await session.flush()
    logger.info("Created task run %s for tool %s", tr.id, tool.slug)
    return tr


async def accept_task_run(session: AsyncSession, tr: TaskRun, user_id: str) -> TaskRun:
    if tr.status not in ("pending",):
        raise ValueError(f"Cannot accept task run in status {tr.status}")
    tr.status = "accepted"
    tr.accepted_at = _now()
    _log_event(session, tr, "accept", actor_user_id=user_id)
    await session.flush()
    return tr


async def submit_task_run(
    session: AsyncSession,
    tr: TaskRun,
    data: TaskRunSubmit,
    user_id: str,
) -> TaskRun:
    if tr.status not in ("pending", "accepted", "in_progress"):
        raise ValueError(f"Cannot submit task run in status {tr.status}")

    # Validate output_data against output_schema if present.
    tv = None
    if tr.tool_version_id:
        tv = await session.get(ToolVersion, tr.tool_version_id)
        if tv:
            _validate_schema(tv.output_schema or {}, dict(data.output_data or {}), label="output")

    now = _now()

    tr.output_data = dict(data.output_data or {})
    tr.finished_by = user_id
    tr.finished_at = now

    ev = _log_event(
        session,
        tr,
        "finish",
        actor_user_id=user_id,
        payload={"has_attachments": bool(data.attachments)},
        message=data.message,
    )
    await session.flush()  # ev.id

    # Bind finish artifacts.
    # Files pre-uploaded via upload-output live in scratch space and need to
    # be moved to the canonical per-run key. Inline attachments with a
    # storage_path that does not point to scratch space are used as-is.
    for att in data.attachments or []:
        storage_key = att.get("storage_path") or att.get("storage_key") or ""
        if storage_key and storage_key.startswith(STAGING_PREFIX):
            from core.storage import get_object_store

            store = get_object_store()
            bucket = "techneos-data"
            prefix = action_prefix(
                tool_slug=tr.tool_slug,
                version=tr.tool_version_no or 0,
                task_run_id=tr.id,
                action_type="finish",
            )
            # Check the scratch file exists, validate format & schema, then copy.
            objs = store.list_objects(bucket, storage_key)
            if not objs:
                raise ValueError(
                    f"Uploaded file storage_key={storage_key!r} not found in scratch space"
                )
            file_name = storage_key.rsplit("/", 1)[-1]
            # input_params stores creation-time inputs; use it to read defaults
            output_fmt = (tr.input_params or {}).get("output_file_format") or ""
            if tv:
                _validate_output_file(
                    store, bucket, storage_key, output_fmt, tv.output_schema or {}
                )
            existing = {o.key.rsplit("/", 1)[-1] for o in store.list_objects(bucket, prefix)}
            file_name = next_available_name(existing, file_name)
            dest = f"{prefix}{file_name}"
            store.copy(bucket, storage_key, bucket, dest)
            # Clean up the scratch copy (mirrors input bind).
            with contextlib.suppress(Exception):  # pragma: no cover
                store.delete(bucket, storage_key)
            session.add(
                TaskRunArtifact(
                    id=str(uuid.uuid4()),
                    task_run_id=tr.id,
                    org_id=tr.org_id,
                    action_type="finish",
                    event_id=ev.id,
                    name=file_name,
                    file_name=file_name,
                    file_size=int(att.get("file_size") or 0),
                    content_type=att.get("content_type") or "application/octet-stream",
                    storage_bucket=bucket,
                    storage_key=dest,
                    status="active",
                    created_by=user_id,
                )
            )
        elif storage_key:
            session.add(
                TaskRunArtifact(
                    id=str(uuid.uuid4()),
                    task_run_id=tr.id,
                    org_id=tr.org_id,
                    action_type="finish",
                    event_id=ev.id,
                    name=att.get("file_name") or att.get("name") or "attachment",
                    file_name=att.get("file_name") or "attachment",
                    file_size=int(att.get("file_size") or 0),
                    content_type=att.get("content_type") or "application/octet-stream",
                    checksum_sha256=att.get("checksum_sha256"),
                    storage_bucket=att.get("storage_bucket") or "techneos-data",
                    storage_key=storage_key,
                    status="active",
                    created_by=user_id,
                    metadata_=att.get("metadata") or {},
                )
            )

    tr.status = "terminal"
    tr.outcome = "completed"
    await session.flush()
    return tr


async def add_update(
    session: AsyncSession,
    tr: TaskRun,
    user_id: str,
    message: str | None = None,
    parent_event_id: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> TaskRunEvent:
    """Post a threaded 'update' action (message + optional files) on a run."""
    if tr.status == "terminal":
        raise ValueError("Cannot post an update to a terminal task run")
    ev = _log_event(
        session,
        tr,
        "update",
        actor_user_id=user_id,
        payload={"has_attachments": bool(attachments)},
        parent_event_id=parent_event_id,
        message=message,
    )
    await session.flush()
    existing = await session.execute(
        select(TaskRunArtifact).where(
            TaskRunArtifact.task_run_id == tr.id,
            TaskRunArtifact.action_type == "update",
            TaskRunArtifact.event_id.is_(None),
        )
    )
    existing_by_key = {a.storage_key: a for a in existing.scalars()}
    for att in attachments or []:
        storage_key = att.get("storage_path") or att.get("storage_key") or ""
        if storage_key and storage_key in existing_by_key:
            existing_by_key[storage_key].event_id = ev.id
        else:
            session.add(
                TaskRunArtifact(
                    id=str(uuid.uuid4()),
                    task_run_id=tr.id,
                    org_id=tr.org_id,
                    action_type="update",
                    event_id=ev.id,
                    name=att.get("file_name") or att.get("name") or "attachment",
                    file_name=att.get("file_name") or "attachment",
                    file_size=int(att.get("file_size") or 0),
                    content_type=att.get("content_type") or "application/octet-stream",
                    checksum_sha256=att.get("checksum_sha256"),
                    storage_bucket=att.get("storage_bucket") or "techneos-data",
                    storage_key=storage_key,
                    status="active",
                    created_by=user_id,
                    metadata_=att.get("metadata") or {},
                )
            )
    await session.flush()
    return ev


async def decline_task_run(
    session: AsyncSession,
    tr: TaskRun,
    user_id: str,
    reason: str | None = None,
) -> TaskRun:
    if tr.status not in ("pending", "accepted"):
        raise ValueError(f"Cannot decline task run in status {tr.status}")
    now = _now()
    tr.status = "terminal"
    tr.outcome = "declined"
    tr.finished_by = user_id
    tr.finished_at = now
    _log_event(session, tr, "decline", actor_user_id=user_id, payload={"reason": reason})
    await session.flush()
    return tr


async def delegate_task_run(
    session: AsyncSession,
    tr: TaskRun,
    data: TaskRunDelegate,
    from_user_id: str,
) -> TaskRun:
    if tr.status not in ("pending", "accepted", "in_progress"):
        raise ValueError(f"Cannot delegate task run in status {tr.status}")
    if data.new_due_at:
        tr.due_at = datetime.fromisoformat(data.new_due_at)

    parent = await _latest_event_id(session, tr, ("start", "delegate", "escalate"))
    tr.assigned_user_id = data.to_user_id
    tr.assigned_team_slug = None
    tr.status = "pending"
    tr.accepted_at = None
    _log_event(
        session,
        tr,
        "delegate",
        actor_user_id=from_user_id,
        parent_event_id=parent,
        payload={
            "to_user_id": data.to_user_id,
            "reason": data.reason,
            "new_due_at": data.new_due_at,
        },
    )
    await session.flush()
    return tr


async def escalate_task_run(session: AsyncSession, tr: TaskRun) -> TaskRun:
    """Escalate to the project lead. Called by HumanBackend when overdue."""
    if tr.status not in ("pending", "accepted", "in_progress"):
        raise ValueError(f"Cannot escalate task run in status {tr.status}")
    if tr.project_lead_id is None:
        raise ValueError("Cannot escalate: no project lead configured")
    # Idempotency — already with the project lead.
    if tr.assigned_user_id == tr.project_lead_id:
        return tr

    parent = await _latest_event_id(session, tr, ("start", "delegate", "escalate"))
    tr.assigned_user_id = tr.project_lead_id
    tr.assigned_team_slug = None
    tr.status = "pending"
    tr.accepted_at = None
    _log_event(
        session,
        tr,
        "escalate",
        actor_user_id=None,
        actor_type="system",
        parent_event_id=parent,
        payload={"escalated_to": tr.project_lead_id},
    )
    await session.flush()
    return tr


async def cancel_task_run(session: AsyncSession, tr: TaskRun, user_id: str | None) -> TaskRun:
    if tr.status == "terminal":
        return tr
    now = _now()
    tr.status = "terminal"
    tr.outcome = "cancelled"
    tr.finished_by = user_id
    tr.finished_at = now
    _log_event(
        session,
        tr,
        "cancel",
        actor_user_id=user_id,
        actor_type=("user" if user_id else "system"),
    )
    await session.flush()
    return tr
