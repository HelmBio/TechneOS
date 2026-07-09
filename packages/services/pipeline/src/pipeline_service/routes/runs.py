"""Pipeline run routes — submit, list, status, cancel, sync, step callbacks,
input staging."""

import hashlib
import io
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from core.auth.dependencies import get_current_superuser, get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters, check_resource_access
from core.config import get_settings
from core.database.postgres import get_async_session
from core.models.common import PaginatedResponse, TokenPayload
from core.models.pipeline import PipelineRun
from core.pipeline_topology import merge, schema_defaults
from core.schemas.pipeline import (
    PipelineArtifactCreate,
    PipelineArtifactDownloadResponse,
    PipelineArtifactResponse,
    PipelineRunCreate,
    PipelineRunDetail,
    PipelineRunInputDownloadResponse,
    PipelineRunInputPaste,
    PipelineRunInputStage,
    PipelineRunResponse,
    PipelineRunUpdate,
    StepRunResponse,
    StepStatusUpdate,
)
from pipeline_service.crud.pipelines import get_pipeline
from pipeline_service.crud.runs import (
    create_artifact,
    create_run,
    create_step_run,
    delete_run,
    get_artifact,
    get_run,
    get_step_runs,
    list_runs,
    update_run,
    update_step_run_by_name,
)
from pipeline_service.crud.versions import get_latest_active_version
from pipeline_service.events import publish_pipeline_run_completed, publish_pipeline_run_failed
from pipeline_service.orchestrator import dispatch_run, handle_cancel, sync_run_status

logger = logging.getLogger(__name__)

# Bucket convention mirrors datasets/tool-runs — single platform-data bucket.
PIPELINE_RUN_BUCKET = "techneos-data"

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
    """Extract org_id from token, raising 403 if absent."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


# ── Input staging (scratch-only, no DB row) ─────────────────────────


@router.post("/inputs", response_model=PipelineRunInputStage, status_code=201)
async def stage_input_endpoint(
    file: UploadFile = File(...),
    parameter_name: str = Form(...),
    pipeline_slug: str = Form(...),
    pipeline_version: int = Form(...),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("pipeline-run", "execute", "own")),
) -> PipelineRunInputStage:
    """Stage an uploaded file for use as a pipeline-run input.

    The file is written to MinIO scratch space only — no DB row is created.
    The returned ``input_id`` is passed back at submit time so the service
    can relocate the file to the canonical per-run ``inputs/`` prefix and
    create the PipelineRunArtifact row (``io_type='input'``).
    """
    from core.storage import get_object_store

    _require_org(current_user)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    input_id = str(uuid.uuid4())
    safe_name = file.filename or "upload.bin"
    storage_key = (
        f"scratch-space/pipeline-runs/{pipeline_slug}/v{pipeline_version}/{input_id}/{safe_name}"
    )
    checksum = hashlib.sha256(content).hexdigest()

    store = get_object_store()
    store.put(
        bucket=PIPELINE_RUN_BUCKET,
        key=storage_key,
        data=io.BytesIO(content),
        length=len(content),
        content_type=file.content_type or "application/octet-stream",
    )

    return PipelineRunInputStage(
        id=input_id,
        parameter_name=parameter_name,
        file_name=safe_name,
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        storage_bucket=PIPELINE_RUN_BUCKET,
        storage_key=storage_key,
        source="upload",
        checksum_sha256=checksum,
    )


@router.post("/inputs/paste", response_model=PipelineRunInputStage, status_code=201)
async def stage_paste_endpoint(
    data: PipelineRunInputPaste,
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("pipeline-run", "execute", "own")),
) -> PipelineRunInputStage:
    """Stage pasted text as a pipeline-run input (no DB row)."""
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
        f"scratch-space/pipeline-runs/{data.pipeline_slug}"
        f"/v{data.pipeline_version}/{input_id}/{safe_name}"
    )
    checksum = hashlib.sha256(content_bytes).hexdigest()

    store = get_object_store()
    store.put(
        bucket=PIPELINE_RUN_BUCKET,
        key=storage_key,
        data=io.BytesIO(content_bytes),
        length=len(content_bytes),
        content_type=data.content_type or "text/plain",
    )

    return PipelineRunInputStage(
        id=input_id,
        parameter_name=data.parameter_name,
        file_name=safe_name,
        file_size=len(content_bytes),
        content_type=data.content_type or "text/plain",
        storage_bucket=PIPELINE_RUN_BUCKET,
        storage_key=storage_key,
        source="paste",
        checksum_sha256=checksum,
    )


@router.get("/inputs/{input_id}/download", response_model=PipelineRunInputDownloadResponse)
async def download_input_endpoint(
    input_id: str,
    pipeline_slug: str,
    pipeline_version: int,
    file_name: str,
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("pipeline-run", "read", "own")),
) -> PipelineRunInputDownloadResponse:
    """Presigned URL for downloading a staged input file from scratch space."""
    from core.storage import get_object_store

    _require_org(current_user)
    storage_key = (
        f"scratch-space/pipeline-runs/{pipeline_slug}/v{pipeline_version}/{input_id}/{file_name}"
    )

    store = get_object_store()
    download_url = store.presigned_url(PIPELINE_RUN_BUCKET, storage_key, expires_seconds=3600)

    return PipelineRunInputDownloadResponse(
        input_id=input_id,
        download_url=download_url,
        expires_in_seconds=3600,
    )


@router.post("", response_model=PipelineRunResponse, status_code=201)
async def submit_run(
    data: PipelineRunCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "execute", "own")),
) -> PipelineRunResponse:
    """Submit a new pipeline run.

    Validates the pipeline exists, merges default parameters with
    user-provided ones, creates the run record, initialises step run
    records, and dispatches to Airflow for execution.
    """
    org_id = _require_org(current_user)

    # Validate pipeline exists and check access
    pipeline = await get_pipeline(session, data.pipeline_id)
    check_resource_access(current_user, pipeline, resource_name="pipeline")

    # Resolve the version to run against
    if data.version_id:
        from pipeline_service.crud.versions import get_pipeline_version

        version = await get_pipeline_version(session, data.version_id)
        if version.pipeline_id != data.pipeline_id:
            raise HTTPException(
                status_code=400, detail="version_id does not belong to this pipeline"
            )
    else:
        _latest = await get_latest_active_version(session, data.pipeline_id)
        if _latest is None:
            raise HTTPException(
                status_code=409,
                detail="Pipeline has no active version. Publish a version before running.",
            )
        version = _latest

    # Effective DAG = parent shape merged with this version's bindings.
    effective_steps = merge(pipeline.steps or [], version.bindings or {})
    # Run-input defaults come from the schema's per-property `default`s.
    defaults = schema_defaults(pipeline.parameters_schema)

    # Merge run-input defaults with user-supplied overrides
    merged_params = {**defaults, **data.parameters}

    # Create the run
    run = await create_run(
        session,
        version_id=version.id,
        parameters=merged_params,
        org_id=org_id,
        user_id=current_user.sub,
        name=data.name,
    )

    # Create step run records for each step in the version
    for step in effective_steps:
        await create_step_run(
            session,
            run_id=run.id,
            step_name=step.get("name", "unnamed"),
            parameters=step.get("parameters", {}),
        )

    # Relocate staged inputs from scratch to the run's canonical inputs/
    # prefix, record an input artifact, and inject a typed pointer into the
    # run parameters under its owning step's namespace (mirrors tool runs).
    if data.inputs:
        from core.storage import get_object_store

        store = get_object_store()
        schema_props = (pipeline.parameters_schema or {}).get("properties", {})

        for inp in data.inputs:
            prop = schema_props.get(inp.parameter_name)
            owning_step = prop.get("x-step") if isinstance(prop, dict) else None

            old_key = inp.storage_key
            new_key = (
                f"pipeline-runs/{pipeline.slug}/v{version.version}/{run.id}/inputs/{inp.file_name}"
            )
            if old_key != new_key:
                try:
                    store.copy(PIPELINE_RUN_BUCKET, old_key, PIPELINE_RUN_BUCKET, new_key)
                    store.delete(PIPELINE_RUN_BUCKET, old_key)
                except Exception:
                    logger.warning(
                        "Failed to relocate pipeline input %s from %s to %s",
                        inp.id,
                        old_key,
                        new_key,
                        exc_info=True,
                    )
                    new_key = old_key

            await create_artifact(
                session,
                run_id=run.id,
                io_type="input",
                step_name=owning_step,
                name=inp.parameter_name,
                artifact_type="file",
                file_name=inp.file_name,
                file_size=inp.file_size,
                content_type=inp.content_type,
                checksum_sha256=inp.checksum_sha256 or None,
                storage_bucket=PIPELINE_RUN_BUCKET,
                storage_key=new_key,
                metadata={"parameter_name": inp.parameter_name, "source": inp.source},
            )

            # Pointer shape matches what the orchestrator already consumes
            # ({type, storage_key, storage_bucket, ...}); key is namespaced to
            # the owning step so dispatch routes it correctly.
            param_key = f"{owning_step}.{inp.parameter_name}" if owning_step else inp.parameter_name
            run.parameters[param_key] = {
                "type": inp.source,
                "id": inp.id,
                "parameter_name": inp.parameter_name,
                "file_name": inp.file_name,
                "file_size": inp.file_size,
                "content_type": inp.content_type,
                "storage_bucket": PIPELINE_RUN_BUCKET,
                "storage_key": new_key,
                "source": inp.source,
                "checksum_sha256": inp.checksum_sha256,
            }
        flag_modified(run, "parameters")
        await session.flush()

    # Dispatch to Airflow (non-blocking — if Airflow is not configured,
    # the run stays in 'pending' status for manual / external execution)
    try:
        settings = get_settings()
        run = await dispatch_run(
            session, run, version, callback_token=settings.internal_service_token
        )
    except Exception:
        logger.exception("Failed to dispatch run %s to Airflow", run.id)
        # Run is still created — it can be retried or picked up manually

    return PipelineRunResponse.model_validate(run)


@router.get("", response_model=PaginatedResponse)
async def list_runs_endpoint(
    pipeline_id: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "read", "own")),
) -> PaginatedResponse:
    """List pipeline runs with optional filters."""
    scope_filters = build_scope_filters(current_user, PipelineRun, "pipeline-run")
    items, total = await list_runs(
        session,
        pipeline_id=pipeline_id,
        status=status,
        skip=skip,
        limit=limit,
        extra_filters=scope_filters,
    )
    return PaginatedResponse(
        items=[PipelineRunResponse.from_orm_with_names(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{run_id}", response_model=PipelineRunDetail)
async def get_run_endpoint(
    run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "read", "own")),
) -> PipelineRunDetail:
    """Get a pipeline run with its step details and artifacts.

    Automatically syncs status from Airflow if the run is still active.
    """
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="pipeline-run")

    # Auto-sync from Airflow if the run is not yet terminal,
    # or if it's terminal but steps haven't been synced yet
    steps = await get_step_runs(session, run_id)
    steps_stale = all(s.status == "pending" for s in steps) and len(steps) > 0
    if run.status not in ("completed", "failed", "cancelled") or steps_stale:
        try:
            run = await sync_run_status(session, run, force=steps_stale)
            steps = await get_step_runs(session, run_id)
        except Exception:
            logger.warning("Auto-sync failed for run %s, returning stale data", run_id)

    # Get artifacts for this run
    from sqlalchemy import select

    from core.models.pipeline import PipelineRunArtifact

    artifact_result = await session.execute(
        select(PipelineRunArtifact).where(PipelineRunArtifact.run_id == run_id)
    )
    artifacts = list(artifact_result.scalars().all())

    # Build base response with denormalized names from eagerly loaded relationships
    base = PipelineRunResponse.from_orm_with_names(run)
    return PipelineRunDetail(
        **base.model_dump(),
        steps=[StepRunResponse.model_validate(s) for s in steps],
        artifacts=[PipelineArtifactResponse.model_validate(a) for a in artifacts],
    )


@router.patch("/{run_id}", response_model=PipelineRunResponse)
async def update_run_endpoint(
    run_id: str,
    data: PipelineRunUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "update", "own")),
) -> PipelineRunResponse:
    """Update a pipeline run (status, timing, airflow refs).

    Typically called by the orchestrator / Airflow callback, not end users.
    """
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="pipeline-run", write=True)
    old_status = run.status
    run = await update_run(session, run_id, data)

    # Fire events on terminal status transitions
    if run.status != old_status and run.status in ("completed", "failed"):
        pipeline = await get_pipeline(session, run.version.pipeline_id)
        if run.status == "completed":
            await publish_pipeline_run_completed(
                run_id=run.id,
                pipeline_id=pipeline.id,
                pipeline_name=pipeline.name,
                submitted_by=run.submitted_by,
            )
        else:
            await publish_pipeline_run_failed(
                run_id=run.id,
                pipeline_id=pipeline.id,
                pipeline_name=pipeline.name,
                submitted_by=run.submitted_by,
            )

    return PipelineRunResponse.model_validate(run)


@router.post("/{run_id}/cancel", response_model=PipelineRunResponse)
async def cancel_run_endpoint(
    run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "update", "own")),
) -> PipelineRunResponse:
    """Cancel a pending or running pipeline run.

    Cancels in both the platform database and Airflow (if dispatched).
    """
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="pipeline-run", write=True)

    if run.status in ("completed", "failed", "cancelled"):
        from core.exceptions import ValidationError

        raise ValidationError(f"Cannot cancel run in '{run.status}' state")

    run = await handle_cancel(session, run)
    return PipelineRunResponse.model_validate(run)


@router.delete("/{run_id}", status_code=204)
async def delete_run_endpoint(
    run_id: str,
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> None:
    """Hard-delete a pipeline run.

    Requires ``platform_admin`` role.  Cascades to step runs and artifacts.
    Used by admin resource-cleanup scripts.
    """
    await delete_run(session, run_id)


@router.post("/{run_id}/restart", response_model=PipelineRunResponse, status_code=201)
async def restart_run_endpoint(
    run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "execute", "own")),
) -> PipelineRunResponse:
    """Restart a failed or cancelled pipeline run.

    Creates a new run with the same definition and parameters, then
    dispatches it to Airflow.  Returns the newly created run.
    """
    org_id = _require_org(current_user)

    original = await get_run(session, run_id)
    check_resource_access(current_user, original, resource_name="pipeline-run")

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

    pipeline = await get_pipeline(session, original.version.pipeline_id)

    # Restart uses the same version as the original run
    version = original.version

    # Create a fresh run cloning the original parameters
    run = await create_run(
        session,
        version_id=version.id,
        parameters=original.parameters or {},
        org_id=org_id,
        user_id=current_user.sub,
        restarted_from=str(original.id),
        name=f"Restart of {original.name}" if original.name else None,
    )

    effective_steps = merge(pipeline.steps or [], version.bindings or {})
    for step in effective_steps:
        await create_step_run(
            session,
            run_id=run.id,
            step_name=step.get("name", "unnamed"),
            parameters=step.get("parameters", {}),
        )

    try:
        run = await dispatch_run(session, run, version)
    except Exception:
        logger.exception("Failed to dispatch restarted run %s to Airflow", run.id)

    return PipelineRunResponse.model_validate(run)


@router.post("/{run_id}/sync", response_model=PipelineRunDetail)
async def sync_run_endpoint(
    run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "read", "own")),
) -> PipelineRunDetail:
    """Synchronise run status from Airflow.

    Polls the Airflow API for the current DAG run and task instance
    states, then updates the platform database.  Returns the updated
    run detail.
    """
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="pipeline-run")

    run = await sync_run_status(session, run)

    steps = await get_step_runs(session, run_id)

    from sqlalchemy import select

    from core.models.pipeline import PipelineRunArtifact

    artifact_result = await session.execute(
        select(PipelineRunArtifact).where(PipelineRunArtifact.run_id == run_id)
    )
    artifacts = list(artifact_result.scalars().all())

    base = PipelineRunResponse.model_validate(run)
    return PipelineRunDetail(
        **base.model_dump(),
        steps=[StepRunResponse.model_validate(s) for s in steps],
        artifacts=[PipelineArtifactResponse.model_validate(a) for a in artifacts],
    )


@router.patch("/{run_id}/steps/{step_name}/status", response_model=StepRunResponse)
async def update_step_status_endpoint(
    run_id: str,
    step_name: str,
    data: StepStatusUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "update", "own")),
) -> StepRunResponse:
    """Update a step's status — called by Airflow task callbacks.

    This is the endpoint that ``ToolOperator._report_step_status``
    calls to report progress back to the platform.
    """
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="pipeline-run", write=True)

    step_run = await update_step_run_by_name(
        session,
        run_id=run_id,
        step_name=step_name,
        status=data.status,
        outputs=data.outputs,
        error_message=data.error_message,
    )
    return StepRunResponse.model_validate(step_run)


@router.get("/{run_id}/steps/{step_name}/logs")
async def get_step_logs_endpoint(
    run_id: str,
    step_name: str,
    try_number: int = 1,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "read", "own")),
) -> dict[str, str | int]:
    """Fetch Airflow task logs for a pipeline step.

    Proxies the Airflow REST API so that the frontend does not need
    direct access to Airflow.
    """
    from core.airflow.client import AirflowClient, AirflowClientError
    from core.airflow.config import get_airflow_settings

    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="pipeline-run")

    if not run.airflow_dag_id or not run.airflow_run_id:
        raise HTTPException(status_code=404, detail="Run has no Airflow reference")

    settings = get_airflow_settings()
    if not settings.configured:
        raise HTTPException(status_code=503, detail="Airflow is not configured")

    # First, try to return container logs stored in the step run's outputs.
    # The ToolOperator stores these as outputs.logs_tail after each step.
    step_runs = await get_step_runs(session, run.id)
    for sr in step_runs:
        if sr.step_name == step_name:
            stored_logs = (sr.outputs or {}).get("logs_tail", "")
            error_msg = sr.error_message or ""
            if stored_logs or error_msg:
                combined = stored_logs
                if error_msg and error_msg not in combined:
                    combined = f"{combined}\n--- error ---\n{error_msg}" if combined else error_msg
                return {"step_name": step_name, "try_number": try_number, "logs": combined}
            break

    # Fall back to Airflow task logs.  The new DAG uses a single
    # "run_pipeline" task that orchestrates all steps; the old DAG
    # used mapped "run_tool_step" instances.  Try both patterns.
    async with AirflowClient(settings) as af:
        try:
            task_instances = await af.get_task_instances(run.airflow_dag_id, run.airflow_run_id)
            matched_ti = None
            for ti in task_instances:
                # Old DAG: mapped tasks with step name in rendered_fields
                rendered = ti.get("rendered_fields", {})
                step_conf = rendered.get("step_conf") if isinstance(rendered, dict) else None
                ti_step_name = step_conf.get("name", "") if isinstance(step_conf, dict) else ""
                if ti_step_name == step_name or ti.get("task_id") == step_name:
                    matched_ti = ti
                    break

            # New DAG: fall back to the "run_pipeline" task which
            # contains logs for all steps interleaved
            if not matched_ti:
                for ti in task_instances:
                    if ti.get("task_id") == "run_pipeline":
                        matched_ti = ti
                        break

            if not matched_ti:
                return {
                    "step_name": step_name,
                    "try_number": try_number,
                    "logs": "No logs available yet.",
                }

            actual_task_id = matched_ti["task_id"]
            map_index = matched_ti.get("map_index", -1)
            actual_try = matched_ti.get("try_number", try_number)

            if actual_try < 1:
                return {
                    "step_name": step_name,
                    "try_number": actual_try,
                    "logs": "No logs available yet — the task has not started running.",
                }

            logs = await af.get_task_logs(
                run.airflow_dag_id,
                run.airflow_run_id,
                actual_task_id,
                try_number=actual_try,
                map_index=map_index,
            )
        except AirflowClientError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch logs: {exc}") from exc

    return {"step_name": step_name, "try_number": try_number, "logs": logs}


# ── Artifact endpoints ──────────────────────────────────────────────


@router.post("/{run_id}/artifacts", response_model=PipelineArtifactResponse, status_code=201)
async def create_artifact_endpoint(
    run_id: str,
    data: PipelineArtifactCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "update", "own")),
) -> PipelineArtifactResponse:
    """Register a new artifact for a pipeline run.

    Called by the ToolOperator after uploading a file to MinIO.
    """
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="pipeline-run", write=True)

    artifact = await create_artifact(
        session,
        run_id=run_id,
        io_type=data.io_type,
        step_name=data.step_name,
        name=data.name,
        artifact_type=data.artifact_type,
        file_name=data.file_name,
        file_size=data.file_size,
        content_type=data.content_type,
        checksum_sha256=data.checksum_sha256,
        storage_bucket=data.storage_bucket,
        storage_key=data.storage_key,
    )
    return PipelineArtifactResponse.model_validate(artifact)


@router.get(
    "/{run_id}/artifacts/{artifact_id}/download",
    response_model=PipelineArtifactDownloadResponse,
)
async def download_artifact_endpoint(
    run_id: str,
    artifact_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline-run", "read", "own")),
) -> PipelineArtifactDownloadResponse:
    """Generate a presigned download URL for an artifact."""
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="pipeline-run")

    artifact = await get_artifact(session, artifact_id)
    if artifact.run_id != run_id:
        raise HTTPException(status_code=404, detail="Artifact not found for this run")

    from core.storage import get_object_store

    store = get_object_store()
    download_url = store.presigned_url(
        artifact.storage_bucket, artifact.storage_key, expires_seconds=3600
    )

    return PipelineArtifactDownloadResponse(
        artifact_id=artifact_id,
        download_url=download_url,
        expires_in_seconds=3600,
    )
