"""Tool run routes — submit, list, status, cancel, restart, sync,
input staging, artifacts, logs."""

import hashlib
import io
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from core.auth.dependencies import get_current_superuser, get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters, check_resource_access
from core.config import get_settings
from core.database.postgres import get_async_session
from core.exceptions import ValidationError
from core.inputs import looks_like_storage_ref
from core.models.common import PaginatedResponse, TokenPayload
from core.models.tool_run import ToolRun
from core.schemas.tool_run import (
    ToolRunArtifactCreate,
    ToolRunArtifactDownloadResponse,
    ToolRunArtifactResponse,
    ToolRunCreate,
    ToolRunDetail,
    ToolRunInputDownloadResponse,
    ToolRunInputPaste,
    ToolRunInputStage,
    ToolRunResponse,
    ToolRunUpdate,
)
from tool_service.crud.runs import (
    create_artifact,
    create_run,
    delete_run,
    get_artifact,
    get_run,
    list_artifacts_for_run,
    list_runs,
    update_run,
)
from tool_service.crud.tools import get_tool
from tool_service.crud.versions import get_latest_version, get_tool_version
from tool_service.orchestrator import (
    dispatch_tool_run,
    handle_cancel,
    persist_tool_run_logs,
    sync_tool_run_status,
)

logger = logging.getLogger(__name__)

# Bucket convention mirrors datasets — single platform-data bucket with key prefixes.
TOOL_RUN_BUCKET = "techneos-data"

# Soft cap on inline pastes — anything bigger should be an upload.
PASTE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

# Content-type → filename extension for synthesised paste files.
_PASTE_EXT_BY_TYPE = {
    "text/plain": "txt",
    "text/csv": "csv",
    "text/tab-separated-values": "tsv",
    "application/json": "json",
    "chemical/x-mdl-sdfile": "sdf",
    "chemical/x-daylight-smiles": "smi",
}

router = APIRouter()


def _require_org(current_user: TokenPayload) -> str:
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


# ── Input staging (scratch-only, no DB row) ─────────────────────────


@router.post("/inputs", response_model=ToolRunInputStage, status_code=201)
async def stage_input_endpoint(
    file: UploadFile = File(...),
    parameter_name: str = Form(...),
    tool_slug: str = Form(...),
    tool_version: int = Form(...),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("tool-run", "execute", "own")),
) -> ToolRunInputStage:
    """Stage an uploaded file for use as a tool-run input.

    The file is written to MinIO scratch space only — no DB row is created.
    The returned ``input_id`` is passed back at submit time so the service
    can relocate the file to the canonical per-run prefix and create the
    ToolRunArtifact row.
    """
    from core.storage import get_object_store

    _require_org(current_user)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    input_id = str(uuid.uuid4())
    safe_name = file.filename or "upload.bin"
    storage_key = f"scratch-space/tool-runs/{tool_slug}/v{tool_version}/{input_id}/{safe_name}"
    checksum = hashlib.sha256(content).hexdigest()

    store = get_object_store()
    store.put(
        bucket=TOOL_RUN_BUCKET,
        key=storage_key,
        data=io.BytesIO(content),
        length=len(content),
        content_type=file.content_type or "application/octet-stream",
    )

    return ToolRunInputStage(
        id=input_id,
        parameter_name=parameter_name,
        file_name=safe_name,
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        storage_bucket=TOOL_RUN_BUCKET,
        storage_key=storage_key,
        source="upload",
        checksum_sha256=checksum,
    )


@router.post("/inputs/paste", response_model=ToolRunInputStage, status_code=201)
async def stage_paste_endpoint(
    data: ToolRunInputPaste,
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("tool-run", "execute", "own")),
) -> ToolRunInputStage:
    """Stage pasted text as a tool-run input (no DB row).

    The text is written to MinIO scratch space. ``source='paste'`` so the
    runtime knows the content was pasted inline (affects parser selection).
    """
    from core.storage import get_object_store

    _require_org(current_user)
    content_bytes = data.content.encode("utf-8")
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Empty paste content")
    if len(content_bytes) > PASTE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Paste exceeds {PASTE_MAX_BYTES // (1024 * 1024)} MB cap; "
                "use the file upload endpoint instead."
            ),
        )

    input_id = str(uuid.uuid4())
    ext = _PASTE_EXT_BY_TYPE.get(data.content_type.lower(), "txt")
    safe_name = data.file_name or f"paste.{ext}"
    storage_key = (
        f"scratch-space/tool-runs/{data.tool_slug}/v{data.tool_version}/{input_id}/{safe_name}"
    )
    checksum = hashlib.sha256(content_bytes).hexdigest()

    store = get_object_store()
    store.put(
        bucket=TOOL_RUN_BUCKET,
        key=storage_key,
        data=io.BytesIO(content_bytes),
        length=len(content_bytes),
        content_type=data.content_type or "text/plain",
    )

    return ToolRunInputStage(
        id=input_id,
        parameter_name=data.parameter_name,
        file_name=safe_name,
        file_size=len(content_bytes),
        content_type=data.content_type or "text/plain",
        storage_bucket=TOOL_RUN_BUCKET,
        storage_key=storage_key,
        source="paste",
        checksum_sha256=checksum,
    )


@router.get("/inputs/{input_id}/download", response_model=ToolRunInputDownloadResponse)
async def download_input_endpoint(
    input_id: str,
    tool_slug: str,
    tool_version: int,
    file_name: str,
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("tool-run", "read", "own")),
) -> ToolRunInputDownloadResponse:
    """Presigned URL for downloading a staged input file from scratch space."""
    from core.storage import get_object_store

    _require_org(current_user)
    storage_key = f"scratch-space/tool-runs/{tool_slug}/v{tool_version}/{input_id}/{file_name}"

    store = get_object_store()
    download_url = store.presigned_url(TOOL_RUN_BUCKET, storage_key, expires_seconds=3600)

    return ToolRunInputDownloadResponse(
        input_id=input_id,
        download_url=download_url,
        expires_in_seconds=3600,
    )


# ── Run submission ─────────────────────────────────────────────────────


tool_scoped_router = APIRouter()


@tool_scoped_router.post("/{tool_id}/runs", response_model=ToolRunResponse, status_code=201)
async def submit_tool_scoped_run(
    tool_id: str,
    data: ToolRunCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "execute", "own")),
) -> ToolRunResponse:
    """Convenience alias: submit a run for the tool in the URL path."""
    if data.tool_id and data.tool_id != tool_id:
        raise HTTPException(status_code=400, detail="tool_id in body does not match URL")
    data.tool_id = tool_id
    return await submit_run(data, current_user, session, True)


@tool_scoped_router.get("/{tool_id}/runs", response_model=PaginatedResponse)
async def list_runs_for_tool(
    tool_id: str,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "read", "own")),
) -> PaginatedResponse:
    """List runs for a specific tool (across all versions)."""
    return await list_runs_endpoint(
        tool_id=tool_id,
        tool_version_id=None,
        status=status,
        skip=skip,
        limit=limit,
        current_user=current_user,
        session=session,
        _perm=True,
    )


@router.post("", response_model=ToolRunResponse, status_code=201)
async def submit_run(
    data: ToolRunCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "execute", "own")),
) -> ToolRunResponse:
    """Submit a new tool run.

    Resolves the target ToolVersion, relocates staged uploads from scratch
    to the canonical per-run prefix, creates artifact rows, rewrites
    parameters to typed pointers, and dispatches to Airflow.
    """
    from core.storage import get_object_store

    org_id = _require_org(current_user)

    tool = await get_tool(session, data.tool_id)
    check_resource_access(current_user, tool, resource_name="tool")

    if data.version_id:
        version = await get_tool_version(session, data.version_id)
        if version.tool_id != data.tool_id:
            raise HTTPException(status_code=400, detail="version_id does not belong to this tool")
    else:
        _latest = await get_latest_version(session, data.tool_id)
        if _latest is None:
            raise HTTPException(
                status_code=409,
                detail="Tool has no active version. Publish a version before running.",
            )
        version = _latest

    merged_params = _merge_with_schema_defaults(version.parameters_schema, data.parameters)

    run = await create_run(
        session,
        tool_version_id=version.id,
        parameters=merged_params,
        org_id=org_id,
        user_id=current_user.sub,
    )

    tool_slug = version.tool.slug if version.tool else "unknown"

    if data.inputs:
        store = get_object_store()
        bucket = TOOL_RUN_BUCKET

        # Relocate each staged input from scratch to canonical prefix and
        # create the artifact row.
        for inp in data.inputs:
            old_key = inp.storage_key
            file_name = inp.file_name
            new_key = f"tool-runs/{tool_slug}/v{version.version}/{run.id}/input/{file_name}"

            # Copy scratch → canonical, then delete scratch
            if old_key != new_key:
                try:
                    store.copy(bucket, old_key, bucket, new_key)
                    store.delete(bucket, old_key)
                except Exception:
                    logger.warning(
                        "Failed to relocate input %s from %s to %s",
                        inp.id,
                        old_key,
                        new_key,
                        exc_info=True,
                    )

            await create_artifact(
                session,
                tool_run_id=run.id,
                io_type="input",
                file_name=file_name,
                file_size=inp.file_size,
                content_type=inp.content_type,
                checksum_sha256=inp.checksum_sha256 or None,
                storage_bucket=bucket,
                storage_key=new_key if old_key != new_key else old_key,
                metadata={
                    "parameter_name": inp.parameter_name,
                    "source": inp.source,
                },
            )

            run.parameters[inp.parameter_name] = {
                "type": inp.source,
                "input_id": inp.id,
                "content_type": inp.content_type,
                "file_name": file_name,
                "storage_key": new_key if old_key != new_key else old_key,
                "storage_bucket": bucket,
            }

    # Canonicalize dataset reference strings to typed pointers
    rewritten = not data.inputs  # already did flag_modified above if we had inputs
    for key, value in list(run.parameters.items()):
        if (
            isinstance(value, str)
            and looks_like_storage_ref(value)
            and not value.startswith("upload:")
        ):
            run.parameters[key] = {"type": "dataset", "ref": value}
            rewritten = True

    if rewritten or data.inputs:
        flag_modified(run, "parameters")
        await session.flush()

    try:
        settings = get_settings()
        run = await dispatch_tool_run(
            session, run, version, callback_token=settings.internal_service_token
        )
    except Exception:
        logger.exception("Failed to dispatch tool run %s to Airflow", run.id)

    run = await get_run(session, run.id)
    return ToolRunResponse.from_orm_with_names(run)


# ── Listing ────────────────────────────────────────────────────────────


@router.get("", response_model=PaginatedResponse)
async def list_runs_endpoint(
    tool_id: str | None = None,
    tool_version_id: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "read", "own")),
) -> PaginatedResponse:
    """List tool runs visible to the caller."""
    scope_filters = build_scope_filters(current_user, ToolRun, "tool-run")
    items, total = await list_runs(
        session,
        tool_id=tool_id,
        tool_version_id=tool_version_id,
        status=status,
        skip=skip,
        limit=limit,
        extra_filters=scope_filters,
    )
    return PaginatedResponse(
        items=[ToolRunResponse.from_orm_with_names(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{run_id}", response_model=ToolRunDetail)
async def get_run_endpoint(
    run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "read", "own")),
) -> ToolRunDetail:
    """Get a tool run with all artifacts (inputs + outputs).

    Auto-syncs status from Airflow if the run is not yet terminal.
    """
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="tool-run")

    if run.status not in ("completed", "failed", "cancelled"):
        try:
            run = await sync_tool_run_status(session, run)
        except Exception:
            logger.warning("Auto-sync failed for tool run %s", run_id, exc_info=True)

    # Retry log persistence for terminal runs that missed it
    if run.status in ("completed", "failed", "cancelled") and not run.log_storage_key:
        try:
            await persist_tool_run_logs(run, session)
            await session.refresh(run)
        except Exception:
            logger.warning("Failed to persist logs on GET for run %s", run_id, exc_info=True)

    artifacts = await list_artifacts_for_run(session, run_id)

    base = ToolRunResponse.from_orm_with_names(run)
    return ToolRunDetail(
        **base.model_dump(),
        artifacts=[ToolRunArtifactResponse.model_validate(a) for a in artifacts],
    )


# ── Run lifecycle ──────────────────────────────────────────────────────


@router.patch("/{run_id}", response_model=ToolRunResponse)
async def update_run_endpoint(
    run_id: str,
    data: ToolRunUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "update", "own")),
) -> ToolRunResponse:
    """Update a tool run — typically called by the Airflow callback."""
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="tool-run", write=True)
    run = await update_run(session, run_id, data)
    return ToolRunResponse.from_orm_with_names(run)


@router.patch("/{run_id}/steps/{step_name}/status", response_model=ToolRunResponse)
async def update_step_status_shim(
    run_id: str,
    step_name: str,
    data: dict[str, Any],
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "update", "own")),
) -> ToolRunResponse:
    """Shim for the ToolOperator's step-style status callbacks."""
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="tool-run", write=True)

    if run.status == "cancelled":
        logger.info("Ignoring callback for cancelled run %s", run_id)
        return ToolRunResponse.from_orm_with_names(run)

    status = data.get("status")
    error_message = data.get("error_message")
    outputs = data.get("outputs")

    update_data: dict[str, Any] = {}
    if status:
        run_status_map = {
            "pending": "pending",
            "running": "running",
            "completed": "completed",
            "failed": "failed",
            "skipped": "cancelled",
            "retrying": "running",
        }
        mapped = run_status_map.get(status, status)
        update_data["status"] = mapped

        now = datetime.now(UTC)
        if mapped == "running" and run.started_at is None:
            update_data["started_at"] = now
        if mapped in ("completed", "failed", "cancelled") and run.finished_at is None:
            update_data["finished_at"] = now

    if error_message:
        update_data["error_message"] = error_message
    if outputs is not None:
        merged_outputs = dict(run.outputs or {})
        merged_outputs.update({step_name: outputs} if step_name else outputs)
        update_data["outputs"] = merged_outputs

        # On terminal status, persist container logs to MinIO
        terminal_statuses = {"completed", "failed", "cancelled"}
        if update_data.get("status") in terminal_statuses or mapped in terminal_statuses:
            logs_content: str | None = None
            for val in merged_outputs.values():
                if isinstance(val, dict) and isinstance(val.get("logs_tail"), str):
                    logs_content = val["logs_tail"]
                    break
            if not logs_content and isinstance(merged_outputs.get("logs_tail"), str):
                logs_content = merged_outputs["logs_tail"]
            if logs_content:
                key = await persist_tool_run_logs(run, session, logs_content=logs_content)
                if key:
                    update_data["log_storage_key"] = key

    run = await update_run(session, run_id, ToolRunUpdate(**update_data))
    return ToolRunResponse.from_orm_with_names(run)


@router.post("/{run_id}/cancel", response_model=ToolRunResponse)
async def cancel_run_endpoint(
    run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "update", "own")),
) -> ToolRunResponse:
    """Cancel a pending or running tool run."""
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="tool-run", write=True)

    if run.status in ("completed", "failed", "cancelled"):
        raise ValidationError(f"Cannot cancel run in '{run.status}' state")

    run = await handle_cancel(session, run)
    return ToolRunResponse.from_orm_with_names(run)


@router.delete("/{run_id}", status_code=204)
async def delete_run_endpoint(
    run_id: str,
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> None:
    """Hard-delete a tool run (admin only)."""
    await delete_run(session, run_id)


@router.post("/{run_id}/restart", response_model=ToolRunResponse, status_code=201)
async def restart_run_endpoint(
    run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "execute", "own")),
) -> ToolRunResponse:
    """Restart a failed or cancelled tool run."""
    org_id = _require_org(current_user)

    original = await get_run(session, run_id)
    check_resource_access(current_user, original, resource_name="tool-run")

    if original.status not in ("failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Only failed or cancelled runs can be restarted (current: '{original.status}')",
        )

    if original.restarted_from is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot restart a run that is itself a restart. Restart the original run instead.",
        )

    version = original.tool_version

    run = await create_run(
        session,
        tool_version_id=version.id,
        parameters=original.parameters or {},
        org_id=org_id,
        user_id=current_user.sub,
        restarted_from=str(original.id),
    )

    try:
        run = await dispatch_tool_run(session, run, version)
    except Exception:
        logger.exception("Failed to dispatch restarted tool run %s", run.id)

    return ToolRunResponse.from_orm_with_names(run)


@router.post("/{run_id}/sync", response_model=ToolRunDetail)
async def sync_run_endpoint(
    run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "read", "own")),
) -> ToolRunDetail:
    """Force a status sync from Airflow."""
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="tool-run")

    run = await sync_tool_run_status(session, run, force=True)

    if run.status in ("completed", "failed", "cancelled") and not run.log_storage_key:
        try:
            await persist_tool_run_logs(run, session)
            await session.refresh(run)
        except Exception:
            logger.warning("Failed to persist logs on sync for run %s", run_id, exc_info=True)

    artifacts = await list_artifacts_for_run(session, run_id)

    base = ToolRunResponse.from_orm_with_names(run)
    return ToolRunDetail(
        **base.model_dump(),
        artifacts=[ToolRunArtifactResponse.model_validate(a) for a in artifacts],
    )


# ── Logs (proxy Airflow task logs) ─────────────────────────────────────


@router.get("/{run_id}/logs")
async def get_run_logs_endpoint(
    run_id: str,
    try_number: int = 1,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "read", "own")),
) -> dict[str, str | int]:
    """Fetch Airflow task logs for the tool run."""
    from core.airflow.client import AirflowClient, AirflowClientError
    from core.airflow.config import get_airflow_settings

    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="tool-run")

    if not run.airflow_dag_id or not run.airflow_run_id:
        raise HTTPException(status_code=404, detail="Run has no Airflow reference")

    settings = get_airflow_settings()
    if not settings.configured:
        raise HTTPException(status_code=503, detail="Airflow is not configured")

    # Terminal runs with persisted logs — read from MinIO
    terminal_statuses = {"completed", "failed", "cancelled"}
    if run.status in terminal_statuses and run.log_storage_key:
        try:
            from core.storage import get_object_store

            store = get_object_store()
            file_obj = store.get("techneos-data", run.log_storage_key)
            content = file_obj.decode("utf-8", errors="replace") if file_obj else ""
            error_msg = run.error_message or ""
            if error_msg and error_msg not in content:
                content = f"{content}\n--- error ---\n{error_msg}"
            return {"run_id": run_id, "try_number": try_number, "logs": content}
        except Exception:
            logger.warning(
                "Failed to read persisted logs from MinIO for run %s", run_id, exc_info=True
            )
            # Fall through to logs_tail or Airflow

    stored = (run.outputs or {}).get("logs_tail")
    if isinstance(stored, str) and stored:
        error_msg = run.error_message or ""
        combined = stored
        if error_msg and error_msg not in combined:
            combined = f"{combined}\n--- error ---\n{error_msg}"
        return {"run_id": run_id, "try_number": try_number, "logs": combined}

    async with AirflowClient(settings) as af:
        try:
            task_instances = await af.get_task_instances(run.airflow_dag_id, run.airflow_run_id)
            matched = None
            for ti in task_instances:
                if ti.get("task_id") == "run_pipeline":
                    matched = ti
                    break
            if not matched and task_instances:
                matched = task_instances[0]

            if not matched:
                return {
                    "run_id": run_id,
                    "try_number": try_number,
                    "logs": "No logs available yet.",
                }

            task_try_number = matched.get("try_number", try_number)
            if task_try_number < 1:
                return {
                    "run_id": run_id,
                    "try_number": task_try_number,
                    "logs": "No logs available yet — the task has not started running.",
                }

            logs = await af.get_task_logs(
                run.airflow_dag_id,
                run.airflow_run_id,
                matched["task_id"],
                try_number=task_try_number,
                map_index=matched.get("map_index", -1),
            )
        except AirflowClientError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch logs: {exc}") from exc

    return {"run_id": run_id, "try_number": try_number, "logs": logs}


# ── Artifact endpoints ─────────────────────────────────────────────────


@router.post("/{run_id}/artifacts", response_model=ToolRunArtifactResponse, status_code=201)
async def create_artifact_endpoint(
    run_id: str,
    data: ToolRunArtifactCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "update", "own")),
) -> ToolRunArtifactResponse:
    """Register an output artifact for a tool run.

    Called by the ToolOperator after uploading a file to MinIO.
    """
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="tool-run", write=True)

    artifact = await create_artifact(
        session,
        tool_run_id=run_id,
        io_type="output",
        file_name=data.file_name,
        file_size=data.file_size,
        content_type=data.content_type,
        checksum_sha256=data.checksum_sha256,
        storage_bucket=data.storage_bucket,
        storage_key=data.storage_key,
        metadata=data.metadata,
    )
    return ToolRunArtifactResponse.model_validate(artifact)


@router.get(
    "/{run_id}/artifacts/{artifact_id}/download",
    response_model=ToolRunArtifactDownloadResponse,
)
async def download_artifact_endpoint(
    run_id: str,
    artifact_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool-run", "read", "own")),
) -> ToolRunArtifactDownloadResponse:
    """Presigned URL for downloading an artifact."""
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="tool-run")

    artifact = await get_artifact(session, artifact_id)
    if artifact.tool_run_id != run_id:
        raise HTTPException(status_code=404, detail="Artifact not found for this run")

    from core.storage import get_object_store

    store = get_object_store()
    download_url = store.presigned_url(
        artifact.storage_bucket, artifact.storage_key, expires_seconds=3600
    )

    return ToolRunArtifactDownloadResponse(
        artifact_id=artifact_id,
        download_url=download_url,
        expires_in_seconds=3600,
    )


# ── Helpers ────────────────────────────────────────────────────────────


def _merge_with_schema_defaults(
    schema: dict[str, Any] | None, user_params: dict[str, Any]
) -> dict[str, Any]:
    """Apply JSON-Schema property defaults under fields the user didn't set."""
    if not schema or not isinstance(schema, dict):
        return dict(user_params)

    properties = schema.get("properties") or {}
    merged: dict[str, Any] = {}
    for key, prop in properties.items():
        if isinstance(prop, dict) and "default" in prop:
            merged[key] = prop["default"]
    merged.update(user_params)
    return merged
