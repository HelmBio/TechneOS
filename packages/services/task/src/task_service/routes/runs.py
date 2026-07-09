"""Task-service routes.

API contract is preserved at the path level (``/task-runs/*``) so the existing
web client keeps working — gateway proxy forwards to task-service. Files are
unified under ``task_run_artifacts`` and stored at the canonical per-run key
``task-runs/{tool_slug}/v{N}/{task_run_id}/{action_type}/{file}`` (an action can
carry multiple files; each is its own ``task_run_artifacts`` row).
"""

from __future__ import annotations

import contextlib
import io
import traceback
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.database.postgres import get_async_session
from core.models.common import PaginatedResponse, TokenPayload
from core.models.pipeline import PipelineStepRun
from core.models.task_run import TaskRun, TaskRunArtifact
from core.models.tool import HumanConfig, Tool, ToolVersion
from core.models.user import Team, User
from core.schemas.task_run import (
    TaskFileDownloadResponse,
    TaskInputUploadResponse,
    TaskOutputUploadResponse,
    TaskRunCreateFromTool,
    TaskRunCreateInternal,
    TaskRunDecline,
    TaskRunDelegate,
    TaskRunResponse,
    TaskRunSubmit,
)
from task_service.crud.runs import (
    accept_task_run,
    add_update,
    build_response,
    cancel_task_run,
    create_task_run,
    decline_task_run,
    delegate_task_run,
    delete_task_run,
    escalate_task_run,
    get_task_run,
    list_task_runs,
    submit_task_run,
    user_can_access,
    user_can_act,
)
from task_service.events import (
    publish_task_run_accepted,
    publish_task_run_cancelled,
    publish_task_run_created,
    publish_task_run_declined,
    publish_task_run_delegated,
    publish_task_run_escalated,
    publish_task_run_submitted,
    publish_task_run_updated,
)
from task_service.storage_keys import (
    action_prefix,
    input_staging_key,
    next_available_name,
    output_staging_prefix,
)

router = APIRouter()

_INPUT_ACTIONS = ("start",)
_OUTPUT_ACTIONS = ("finish", "update")


# ── Helpers ──────────────────────────────────────────────────────────────


def _require_org(current_user: TokenPayload) -> str:
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


def _is_admin(user: TokenPayload) -> bool:
    return bool(user.permissions and "*:*:platform" in user.permissions)


async def _resolve_user_team_slug(session: AsyncSession, user: TokenPayload) -> str | None:
    """Resolve the caller's team slug for team-membership checks."""
    if not user.team_id:
        return None
    team = await session.get(Team, user.team_id)
    return team.slug if team else None


async def _resolve_for_access(session: AsyncSession, user: TokenPayload, tr: TaskRun) -> None:
    """Raise 403 unless the caller can read this TaskRun."""
    team_slug = await _resolve_user_team_slug(session, user)
    if not await user_can_access(session, tr, user.sub, team_slug, _is_admin(user)):
        raise HTTPException(status_code=403, detail="Not authorized to access this task run")


async def _resolve_for_action(session: AsyncSession, user: TokenPayload, tr: TaskRun) -> None:
    """Raise 403 unless the caller can act on the current holder."""
    team_slug = await _resolve_user_team_slug(session, user)
    if not await user_can_act(session, tr, user.sub, team_slug):
        raise HTTPException(
            status_code=403,
            detail="Only the current assignee, a team member, or the project lead may act on this task run",
        )


_MAX_INPUT_BYTES = 50 * 1024 * 1024  # 50 MB — protects against oversize uploads.


async def _store_run_file(
    session: AsyncSession,
    tr: TaskRun,
    action_type: str,
    file: UploadFile,
) -> tuple[TaskRunArtifact, bytes]:
    """Read + store an uploaded file at the canonical key, return the row.

    The artifact is added to the session but not linked to an event — callers
    that need event linkage (e.g. the ``update`` action) set ``event_id``.
    """
    content = await file.read()
    if len(content) > _MAX_INPUT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {_MAX_INPUT_BYTES // (1024 * 1024)} MB",
        )
    safe_filename = (file.filename or "file").replace("/", "_").replace("\\", "_")
    artifact_id = str(uuid.uuid4())

    from core.storage import get_object_store

    store = get_object_store()
    # De-duplicate within this run+action: append -N if the name already exists.
    prefix = action_prefix(
        tool_slug=tr.tool_slug,
        version=tr.tool_version_no or 0,
        task_run_id=tr.id,
        action_type=action_type,
    )
    existing = {o.key.rsplit("/", 1)[-1] for o in store.list_objects("techneos-data", prefix)}
    safe_filename = next_available_name(existing, safe_filename)
    storage_key = f"{prefix}{safe_filename}"

    store.put(
        bucket="techneos-data",
        key=storage_key,
        data=io.BytesIO(content),
        length=len(content),
        content_type=file.content_type or "application/octet-stream",
    )

    row = TaskRunArtifact(
        id=artifact_id,
        task_run_id=tr.id,
        org_id=tr.org_id,
        action_type=action_type,
        name=safe_filename,
        file_name=safe_filename,
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        storage_bucket="techneos-data",
        storage_key=storage_key,
        status="active",
        created_by="",  # set by caller
    )
    return row, content


# ── List ─────────────────────────────────────────────────────────────────


@router.get("", response_model=PaginatedResponse)
async def list_task_runs_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=0, le=100),
    status_filter: str | None = Query(None, alias="status"),
    tool_slug: str | None = Query(None),
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> PaginatedResponse:
    org_id = _require_org(current_user)
    team_slug = await _resolve_user_team_slug(session, current_user)
    items, total = await list_task_runs(
        session,
        org_id=org_id,
        user_id=current_user.sub,
        team_slug=team_slug,
        tool_slug=tool_slug,
        status=status_filter,
        skip=skip,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


# ── Create: internal (HumanBackend) ──────────────────────────────────────


@router.post("", response_model=TaskRunResponse, status_code=201)
async def create_task_run_internal_endpoint(
    data: TaskRunCreateInternal,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "create", "org")),
) -> TaskRunResponse:
    """Create a task run from the worker (HumanBackend)."""
    tool, version, hc = await _load_version_chain(session, data.tool_slug, data.tool_version_id)

    if data.assigned_user_id and data.assigned_team_slug:
        raise HTTPException(
            status_code=400,
            detail="Supply exactly one of assigned_user_id or assigned_team_slug, not both.",
        )
    if data.assigned_user_id or data.assigned_team_slug:
        assigned_user_id = data.assigned_user_id
        assigned_team_slug = data.assigned_team_slug
    elif data.assigned_user_email:
        assigned_user_id = await _resolve_user_email(session, data.assigned_user_email)
        assigned_team_slug = None
    else:
        if hc and hc.assignment_type == "user" and hc.default_user_email:
            assigned_user_id = await _resolve_user_email(session, hc.default_user_email)
            assigned_team_slug = None
        elif hc and hc.assignment_type == "team":
            assigned_user_id = None
            assigned_team_slug = hc.default_team_slug
        else:
            assigned_user_id = None
            assigned_team_slug = None
    if not assigned_user_id and not assigned_team_slug:
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{tool.slug}' has no default assignee; supply assigned_user_id or assigned_team_slug",
        )

    due_at = datetime.fromisoformat(data.due_at) if data.due_at else None

    # Resolve project lead email to UUID if provided.
    project_lead_id = data.project_lead_id
    if project_lead_id is None and data.project_lead_email:
        project_lead_id = await _resolve_user_email(session, data.project_lead_email)
    if project_lead_id is None and hc and hc.default_project_lead_email:
        project_lead_id = await _resolve_user_email(session, hc.default_project_lead_email)

    pipeline_step_run_id = data.pipeline_step_run_id
    if pipeline_step_run_id is None and data.pipeline_run_id and data.step_name:
        result = await session.execute(
            select(PipelineStepRun).where(
                PipelineStepRun.run_id == data.pipeline_run_id,
                PipelineStepRun.step_name == data.step_name,
            )
        )
        step_run = result.scalar_one_or_none()
        if step_run is not None:
            pipeline_step_run_id = step_run.id

    try:
        tr = await create_task_run(
            session,
            org_id=data.org_id,
            tool=tool,
            tool_version=version,
            human_config=hc,
            pipeline_run_id=data.pipeline_run_id,
            pipeline_step_run_id=pipeline_step_run_id,
            step_name=data.step_name,
            input_snapshot=data.input_snapshot,
            assigned_user_id=assigned_user_id,
            assigned_team_slug=assigned_team_slug,
            project_lead_id=project_lead_id,
            started_by=data.created_by or current_user.sub,
            due_at=due_at,
            priority=data.priority,
        )
    except (ValueError, IntegrityError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    with contextlib.suppress(Exception):
        await publish_task_run_created(
            task_run_id=tr.id,
            tool_version_id=version.id,
            tool_name=tool.slug,
            assigned_user_id=assigned_user_id,
            assigned_team_slug=assigned_team_slug,
            project_lead_id=project_lead_id,
            created_by=tr.started_by,
        )
    return await build_response(session, tr)


@router.post("/from-tool", response_model=TaskRunResponse, status_code=201)
async def create_task_run_from_tool_endpoint(
    data: TaskRunCreateFromTool,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "create", "org")),
) -> TaskRunResponse:
    """User-facing — run a human tool directly (no pipeline)."""
    org_id = _require_org(current_user)
    tool, version, hc = await _load_version_chain(session, data.tool_slug, data.tool_version_id)

    if data.assigned_user_id and data.assigned_team_slug:
        raise HTTPException(
            status_code=400,
            detail="Supply exactly one of assigned_user_id or assigned_team_slug, not both.",
        )
    if data.assigned_user_id or data.assigned_team_slug:
        assigned_user_id = data.assigned_user_id
        assigned_team_slug = data.assigned_team_slug
    else:
        if hc and hc.assignment_type == "user" and hc.default_user_email:
            assigned_user_id = await _resolve_user_email(session, hc.default_user_email)
            assigned_team_slug = None
        elif hc and hc.assignment_type == "team":
            assigned_user_id = None
            assigned_team_slug = hc.default_team_slug
        else:
            assigned_user_id = None
            assigned_team_slug = None
    if not assigned_user_id and not assigned_team_slug:
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{tool.slug}' has no default assignee; supply assigned_user_id or assigned_team_slug",
        )

    due_hours = (
        data.due_in_hours
        if data.due_in_hours is not None
        else (hc.due_in_hours if hc and hc.due_in_hours is not None else 72)
    )
    due_at = datetime.now(UTC) + timedelta(hours=due_hours)

    # Resolve project lead from payload or human config.
    project_lead_id: str | None = None
    if data.project_lead_email:
        project_lead_id = await _resolve_user_email(session, data.project_lead_email)
    if project_lead_id is None and hc and hc.default_project_lead_email:
        project_lead_id = await _resolve_user_email(session, hc.default_project_lead_email)

    try:
        tr = await create_task_run(
            session,
            org_id=org_id,
            tool=tool,
            tool_version=version,
            human_config=hc,
            pipeline_run_id=None,
            pipeline_step_run_id=None,
            step_name=None,
            input_snapshot=data.input_snapshot or {},
            assigned_user_id=assigned_user_id,
            assigned_team_slug=assigned_team_slug,
            project_lead_id=project_lead_id,
            started_by=current_user.sub,
            due_at=due_at,
            input_artifact_ids=data.input_ids,
            priority=data.priority,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        msg = str(e)
        if "assigned_user" in msg or "fk_task_runs_assigned_user" in msg:
            raise HTTPException(status_code=400, detail="Assigned user does not exist.") from e
        raise HTTPException(status_code=400, detail=f"Database error: {msg}") from e

    with contextlib.suppress(Exception):
        await publish_task_run_created(
            task_run_id=tr.id,
            tool_version_id=version.id,
            tool_name=tool.slug,
            assigned_user_id=assigned_user_id,
            assigned_team_slug=assigned_team_slug,
            project_lead_id=project_lead_id,
            created_by=current_user.sub,
        )
    return await build_response(session, tr)


async def _load_tool_chain(session: AsyncSession, tool_slug: str) -> Tool:
    """Resolve a human-type Tool by slug (no version selection)."""
    result = await session.execute(
        select(Tool).where(Tool.slug == tool_slug, Tool.tool_type == "human")
    )
    tool = result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Human task '{tool_slug}' not found")
    return tool


async def _load_version_chain(
    session: AsyncSession, tool_slug: str, tool_version_id: str
) -> tuple[Tool, ToolVersion, HumanConfig | None]:
    """Resolve a specific (Tool, ToolVersion, HumanConfig) triple."""
    result = await session.execute(
        select(ToolVersion)
        .options(
            selectinload(ToolVersion.tool),
            selectinload(ToolVersion.human_config),
        )
        .where(ToolVersion.id == tool_version_id)
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"Tool version '{tool_version_id}' not found",
        )
    tool = version.tool
    if tool is None or tool.tool_type != "human":
        raise HTTPException(
            status_code=400,
            detail=f"Tool version '{tool_version_id}' does not belong to a human task",
        )
    if tool.slug != tool_slug:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tool version '{tool_version_id}' belongs to task '{tool.slug}', not '{tool_slug}'"
            ),
        )
    return tool, version, version.human_config


async def _resolve_user_email(session: AsyncSession, email: str) -> str | None:
    """Resolve a user email to a user UUID, or return None if not found."""
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    return user.id if user else None


# ── Single-task operations ───────────────────────────────────────────────


@router.get("/{task_run_id}", response_model=TaskRunResponse)
async def get_task_run_endpoint(
    task_run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "read", "own")),
) -> TaskRunResponse:
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_access(session, current_user, tr)
    return await build_response(session, tr)


@router.post("/{task_run_id}/accept", response_model=TaskRunResponse)
async def accept_task_run_endpoint(
    task_run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "update", "own")),
) -> TaskRunResponse:
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_action(session, current_user, tr)
    try:
        tr = await accept_task_run(session, tr, current_user.sub)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    with contextlib.suppress(Exception):
        await publish_task_run_accepted(
            task_run_id=tr.id, tool_name=tr.tool_slug, accepted_by=current_user.sub
        )
    return await build_response(session, tr)


@router.post("/{task_run_id}/submit", response_model=TaskRunResponse)
async def submit_task_run_endpoint(
    task_run_id: str,
    data: TaskRunSubmit,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "update", "own")),
) -> TaskRunResponse:
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_action(session, current_user, tr)
    try:
        tr = await submit_task_run(session, tr, data, current_user.sub)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        # Surface detailed error for debugging; in production, consider sanitizing this.
        traceback.print_exc()
        detail = getattr(e, "detail", None) or str(e)
        raise HTTPException(status_code=500, detail=detail) from e
    with contextlib.suppress(Exception):
        await publish_task_run_submitted(
            task_run_id=tr.id,
            tool_name=tr.tool_slug,
            submitted_by=current_user.sub,
        )
    return await build_response(session, tr)


@router.post("/{task_run_id}/actions", response_model=TaskRunResponse, status_code=201)
async def post_task_run_action_endpoint(
    task_run_id: str,
    message: str | None = Form(None),
    parent_event_id: str | None = Form(None),
    file: UploadFile | None = File(None),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "update", "own")),
) -> TaskRunResponse:
    """Post a threaded ``update`` action: a message and/or a file, optionally
    in reply to a prior action (``parent_event_id``)."""
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_action(session, current_user, tr)
    if not message and file is None:
        raise HTTPException(status_code=400, detail="Provide a message and/or a file")

    attachments: list[dict[str, Any]] = []
    if file is not None:
        row, _ = await _store_run_file(session, tr, "update", file)
        attachments.append(
            {
                "file_name": row.file_name,
                "file_size": row.file_size,
                "content_type": row.content_type,
                "storage_path": row.storage_key,
                "storage_bucket": row.storage_bucket,
            }
        )
    try:
        await add_update(
            session,
            tr,
            current_user.sub,
            message=message,
            parent_event_id=parent_event_id,
            attachments=attachments or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    with contextlib.suppress(Exception):
        await publish_task_run_updated(
            task_run_id=tr.id, tool_name=tr.tool_slug, actor=current_user.sub
        )
    return await build_response(session, tr)


@router.post("/{task_run_id}/decline", response_model=TaskRunResponse)
async def decline_task_run_endpoint(
    task_run_id: str,
    data: TaskRunDecline | None = None,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "update", "own")),
) -> TaskRunResponse:
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_action(session, current_user, tr)
    reason = data.reason if data else None
    try:
        tr = await decline_task_run(session, tr, current_user.sub, reason)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    with contextlib.suppress(Exception):
        await publish_task_run_declined(
            task_run_id=tr.id, tool_name=tr.tool_slug, declined_by=current_user.sub
        )
    return await build_response(session, tr)


@router.post("/{task_run_id}/delegate", response_model=TaskRunResponse)
async def delegate_task_run_endpoint(
    task_run_id: str,
    data: TaskRunDelegate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "update", "own")),
) -> TaskRunResponse:
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_action(session, current_user, tr)
    try:
        tr = await delegate_task_run(session, tr, data, current_user.sub)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    with contextlib.suppress(Exception):
        await publish_task_run_delegated(
            task_run_id=tr.id,
            tool_name=tr.tool_slug,
            delegated_from=current_user.sub,
            delegated_to=data.to_user_id,
        )
    return await build_response(session, tr)


@router.post("/{task_run_id}/escalate", response_model=TaskRunResponse)
async def escalate_task_run_endpoint(
    task_run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "update", "org")),
) -> TaskRunResponse:
    """Escalate to project lead. Called by HumanBackend; admin can also invoke."""
    tr = await get_task_run(session, task_run_id)
    try:
        tr = await escalate_task_run(session, tr)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    with contextlib.suppress(Exception):
        await publish_task_run_escalated(
            task_run_id=tr.id,
            tool_name=tr.tool_slug,
            escalated_to=tr.project_lead_id or "",
        )
    return await build_response(session, tr)


@router.post("/{task_run_id}/cancel", response_model=TaskRunResponse)
async def cancel_task_run_endpoint(
    task_run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "delete", "own")),
) -> TaskRunResponse:
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_access(session, current_user, tr)
    tr = await cancel_task_run(session, tr, current_user.sub)
    with contextlib.suppress(Exception):
        await publish_task_run_cancelled(task_run_id=tr.id, tool_name=tr.tool_slug)
    return await build_response(session, tr)


@router.delete("/{task_run_id}", status_code=204)
async def delete_task_run_endpoint(
    task_run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "delete", "own")),
) -> None:
    """Hard-delete a TaskRun (cascades to events / artifacts)."""
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_access(session, current_user, tr)
    await delete_task_run(session, task_run_id)


# ── Input file upload (staged → bound on TaskRun creation) ───────────────


def _parse_sdf_compounds(content: str) -> list[dict[str, Any]]:
    """Parse SDF text and extract compound entries (correct ``$$$$`` split)."""
    compounds: list[dict[str, Any]] = []
    for mol in content.split("$$$$"):
        lines = mol.strip().split("\n")
        if len(lines) < 4:
            continue
        properties: dict[str, str] = {}
        reading_props = False
        current_prop = ""
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("> <"):
                reading_props = True
                current_prop = stripped.replace(">", "").replace("<", "").strip()
                continue
            if reading_props:
                if stripped == "" or stripped == "$$$$":
                    reading_props = False
                else:
                    properties[current_prop] = stripped
        compound_id = (
            properties.get("Compound_ID") or properties.get("ID") or properties.get("Name") or ""
        )
        if not compound_id:
            continue
        compound: dict[str, Any] = {"id": compound_id}
        if properties.get("SMILES"):
            compound["smiles"] = properties["SMILES"]
        if properties.get("MW"):
            with contextlib.suppress(ValueError):
                compound["mw"] = float(properties["MW"])
        if properties.get("Desired_Amount"):
            compound["desired_amount"] = properties["Desired_Amount"]
        if properties.get("Notes"):
            compound["notes"] = properties["Notes"]
        compounds.append(compound)
    return compounds


@router.post(
    "/from-tool/upload",
    response_model=TaskInputUploadResponse,
    status_code=201,
)
async def upload_task_input_endpoint(
    tool_slug: str = Form(...),
    tool_version_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "create", "org")),
) -> TaskInputUploadResponse:
    """Stage an input file for a human task in scratch space.

    The file is written to ``scratch-space/task-runs/{tool_slug}/v{N}/{input_id}/…``
    (version is preselected so always known). Pass the returned ``input_id`` in
    ``input_ids`` when creating the run; only then is the file copied to its
    canonical per-run key and a ``task_run_artifacts`` row created. Unbound
    scratch files can be cleared periodically. For SDF files, also extracts
    compound metadata.
    """
    _require_org(current_user)
    _, version, _ = await _load_version_chain(session, tool_slug, tool_version_id)

    content = await file.read()
    if len(content) > _MAX_INPUT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {_MAX_INPUT_BYTES // (1024 * 1024)} MB",
        )
    content_str: str | None = None
    with contextlib.suppress(UnicodeDecodeError):
        content_str = content.decode("utf-8")

    input_id = str(uuid.uuid4())
    storage_key = input_staging_key(tool_slug, version.version, input_id, file.filename)

    from core.storage import get_object_store

    store = get_object_store()
    store.put(
        bucket="techneos-data",
        key=storage_key,
        data=io.BytesIO(content),
        length=len(content),
        content_type=file.content_type or "application/octet-stream",
    )

    compounds = _parse_sdf_compounds(content_str) if content_str is not None else []

    return TaskInputUploadResponse(
        input_id=input_id,
        storage_path=storage_key,
        compounds_count=len(compounds) if compounds else None,
        file_size=len(content),
    )


@router.get("/{task_run_id}/download-input", response_model=TaskFileDownloadResponse)
async def download_task_run_input(
    task_run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "read", "own")),
) -> TaskFileDownloadResponse:
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_access(session, current_user, tr)

    bound = await session.execute(
        select(TaskRunArtifact)
        .where(
            TaskRunArtifact.task_run_id == tr.id,
            TaskRunArtifact.action_type.in_(_INPUT_ACTIONS),
        )
        .limit(1)
    )
    row = bound.scalar_one_or_none()
    file_path: str | None = row.storage_key if row else None
    bucket = row.storage_bucket if row else "techneos-data"
    if not file_path:
        snap = tr.input_params or {}
        file_path = snap.get("file_path")
    if not file_path:
        raise HTTPException(status_code=404, detail="No input file found for this task run")

    from core.storage import get_object_store

    store = get_object_store()
    download_url = store.presigned_url(bucket, file_path, expires_seconds=3600)
    return TaskFileDownloadResponse(download_url=download_url, storage_path=file_path)


# ── Output file upload ───────────────────────────────────────────────────


@router.post(
    "/{task_run_id}/upload-output",
    response_model=TaskOutputUploadResponse,
    status_code=201,
)
async def upload_task_output_endpoint(
    task_run_id: str,
    file: UploadFile = File(...),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "update", "own")),
) -> TaskOutputUploadResponse:
    """Stage an output file in scratch space (not yet stored in the DB).

    Written to ``scratch-space/task-runs/{tool_slug}/v{N}/{run_id}/…`` (run-scoped,
    so no per-upload id needed). Pass the returned ``storage_path`` in
    ``attachments`` when submitting the run; only then is it copied to its
    canonical ``finish/`` key and recorded.
    """
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_action(session, current_user, tr)
    if tr.status == "terminal":
        raise HTTPException(
            status_code=422,
            detail="Cannot upload outputs to a task run that is already terminal",
        )

    content = await file.read()
    if len(content) > _MAX_INPUT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {_MAX_INPUT_BYTES // (1024 * 1024)} MB",
        )

    from core.storage import get_object_store

    store = get_object_store()
    # De-duplicate within the run's output scratch so same-named uploads don't
    # overwrite each other (the canonical name is finalised again at submit).
    prefix = output_staging_prefix(tr.tool_slug, tr.tool_version_no or 0, tr.id)
    existing = {o.key.rsplit("/", 1)[-1] for o in store.list_objects("techneos-data", prefix)}
    safe_filename = (file.filename or "output").replace("/", "_").replace(
        "\\", "_"
    ).strip() or "output"
    safe_filename = next_available_name(existing, safe_filename)
    storage_key = f"{prefix}{safe_filename}"

    store.put(
        bucket="techneos-data",
        key=storage_key,
        data=io.BytesIO(content),
        length=len(content),
        content_type=file.content_type or "application/octet-stream",
    )

    return TaskOutputUploadResponse(
        output_id=tr.id,
        storage_path=storage_key,
        file_name=safe_filename,
        content_type=file.content_type or "application/octet-stream",
        file_size=len(content),
    )


@router.get("/{task_run_id}/download-output", response_model=TaskFileDownloadResponse)
async def download_task_run_output(
    task_run_id: str,
    file_name: str = Query(..., description="The filename to download"),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("task_run", "read", "own")),
) -> TaskFileDownloadResponse:
    tr = await get_task_run(session, task_run_id)
    await _resolve_for_access(session, current_user, tr)

    target: TaskRunArtifact | None = None
    q = await session.execute(
        select(TaskRunArtifact).where(
            TaskRunArtifact.task_run_id == tr.id,
        )
    )
    for row in q.scalars():
        if row.file_name == file_name or row.storage_key.endswith(f"/{file_name}"):
            target = row
            break
    if target is None:
        raise HTTPException(status_code=404, detail="Output file not found")

    from core.storage import get_object_store

    store = get_object_store()
    download_url = store.presigned_url(
        target.storage_bucket, target.storage_key, expires_seconds=3600
    )
    return TaskFileDownloadResponse(download_url=download_url, storage_path=target.storage_key)
