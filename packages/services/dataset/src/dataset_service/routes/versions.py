"""Dataset version routes — upload, transfer, list, status management."""

import contextlib
import csv
import hashlib
import io
import json
import logging
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.config import get_settings
from core.database.postgres import get_async_session
from core.exceptions import NotFoundError
from core.models.bucket import (
    ObjectStoreBucket,
)
from core.models.common import TokenPayload
from core.schemas.dataset import DatasetVersionResponse, VersionTransferRequest
from core.storage import create_object_store, get_object_store
from dataset_service.crud.datasets import get_dataset
from dataset_service.crud.versions import (
    create_version,
    delete_version,
    get_version,
    list_versions,
    next_version_number,
    replace_version_files,
    update_version_status,
)

logger = logging.getLogger(__name__)
router = APIRouter()

DATASET_BUCKET = "techneos-data"


def _require_org(current_user: TokenPayload) -> str:
    """Extract org_id from token, raising 403 if absent."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


# --- Upload (small files, synchronous) ---


@router.post("", response_model=DatasetVersionResponse, status_code=201)
async def upload_version(
    dataset_id: str,
    file: UploadFile = File(...),
    description: str | None = Form(default=None),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> DatasetVersionResponse:
    """Upload a new version of a dataset (single file).

    Files larger than ``max_upload_file_size_mb`` (configurable) will be
    rejected — use the ``/transfer`` endpoint for large files.
    """
    return await _upload_version_files(
        dataset_id=dataset_id,
        files=[file],
        descriptions=[description] if description else [None],
        current_user=current_user,
        session=session,
    )


@router.post("/batch", response_model=DatasetVersionResponse, status_code=201)
async def upload_version_batch(
    dataset_id: str,
    files: list[UploadFile] = File(...),
    description: str | None = Form(default=None),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> DatasetVersionResponse:
    """Upload multiple files as a single dataset version.

    All files are stored under the same version directory in MinIO.
    """
    return await _upload_version_files(
        dataset_id=dataset_id,
        files=files,
        descriptions=[description] * len(files),
        current_user=current_user,
        session=session,
    )


async def _upload_version_files(
    dataset_id: str,
    files: list[UploadFile],
    descriptions: list[str | None],
    current_user: TokenPayload,
    session: AsyncSession,
) -> DatasetVersionResponse:
    """Shared logic: create a version with one or more uploaded files."""
    ds = await get_dataset(session, dataset_id)

    settings = get_settings()
    max_bytes = settings.max_upload_file_size_mb * 1024 * 1024

    # Read all file content upfront for validation
    file_contents: list[tuple[str, str | None, bytes]] = []
    for idx, file in enumerate(files):
        content = await file.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File '{file.filename or f'file_{idx}'}' exceeds the "
                    f"{settings.max_upload_file_size_mb} MB upload limit "
                    f"({len(content)} bytes). Use the /transfer endpoint "
                    "for large files."
                ),
            )
        file_contents.append((file.filename or f"file_{idx}", file.content_type, content))

    # Validate file format, columns, and data schema
    _validate_upload_files(file_contents, ds.metadata_, ds.data_schema)

    version_num = await next_version_number(session, dataset_id)
    # Use the dataset slug (human-readable, immutable per dataset) instead of
    # the UUID so MinIO browsing is legible. Slugs are unique by DB constraint.
    storage_base = f"datasets/{ds.slug}/v{version_num}"
    store = get_object_store()

    file_infos = []
    for _idx, (original_name, content_type, content) in enumerate(file_contents):
        file_size = len(content)
        checksum = hashlib.sha256(content).hexdigest()
        storage_key = f"{storage_base}/{original_name}"

        store.put(
            bucket=DATASET_BUCKET,
            key=storage_key,
            data=io.BytesIO(content),
            length=file_size,
            content_type=content_type or "application/octet-stream",
        )

        file_infos.append(
            {
                "file_name": original_name,
                "file_size": file_size,
                "content_type": content_type or "application/octet-stream",
                "storage_key": storage_key,
                "checksum_sha256": checksum,
            }
        )

    v = await create_version(
        session=session,
        dataset_id=dataset_id,
        version_num=version_num,
        user_id=current_user.sub,
        storage_bucket=DATASET_BUCKET,
        description=descriptions[0],
        files=file_infos,
        transfer_method="upload",
    )

    v = await update_version_status(session, v.id, status="ready", user_id=current_user.sub)

    # Publish event (best-effort)
    from dataset_service.events import publish_dataset_version_uploaded

    total_size = sum(cast(int, f["file_size"]) for f in file_infos)
    await publish_dataset_version_uploaded(
        dataset_id=dataset_id,
        dataset_slug=ds.slug,
        dataset_name=ds.name,
        version=version_num,
        file_name=cast(str, file_infos[0]["file_name"]),
        file_size=total_size,
    )

    return DatasetVersionResponse.model_validate(v)


# --- Transfer (large / external files, background) ---


@router.post("/transfer", response_model=DatasetVersionResponse, status_code=202)
async def transfer_version(
    dataset_id: str,
    data: VersionTransferRequest,
    background_tasks: BackgroundTasks,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> DatasetVersionResponse:
    """Transfer files from a registered object store bucket as a new version.

    Files are copied in the background.  The version is created immediately
    with ``status="transferring"`` and transitions to ``"ready"`` once the
    copy completes.
    """
    ds = await get_dataset(session, dataset_id)
    org_id = _require_org(current_user)

    # Validate source bucket exists and belongs to the same org
    from sqlalchemy import select

    result = await session.execute(
        select(ObjectStoreBucket).where(
            ObjectStoreBucket.id == data.source_bucket_id,
            ObjectStoreBucket.org_id == org_id,
            ObjectStoreBucket.is_active.is_(True),
        )
    )
    bucket = result.scalar_one_or_none()
    if bucket is None:
        raise HTTPException(
            status_code=404,
            detail=f"ObjectStoreBucket '{data.source_bucket_id}' not found or not accessible",
        )

    # Verify source files exist
    from core.security.fernet import decrypt_value

    access_key = decrypt_value(bucket.encrypted_access_key) if bucket.encrypted_access_key else None
    secret_key = decrypt_value(bucket.encrypted_secret_key) if bucket.encrypted_secret_key else None

    if bucket.endpoint_url:
        parsed = urlparse(bucket.endpoint_url)
        source_endpoint = parsed.netloc or parsed.path
        source_store = create_object_store(
            endpoint=source_endpoint,
            access_key=access_key or "",
            secret_key=secret_key or "",
            secure=bucket.secure,
        )
    else:
        from core.storage import MinIOStore

        source_store = MinIOStore()
        source_endpoint = ""

    for fp in data.file_paths:
        try:
            obj_info = source_store.list_objects(bucket.bucket_name, prefix=fp)
            if not obj_info:
                raise HTTPException(
                    status_code=404,
                    detail=f"Source file '{fp}' not found in bucket '{bucket.bucket_name}'",
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to access source bucket: {e}",
            ) from e

    # Validate data schema against source files (sample first 10 MB per file)
    MAX_VALIDATION_BYTES = 10 * 1024 * 1024  # noqa: N806
    try:
        sample_data: list[tuple[str, str | None, bytes]] = []
        for fp in data.file_paths:
            obj_data = source_store.get(bucket.bucket_name, fp, max_bytes=MAX_VALIDATION_BYTES)
            sample_data.append((fp, None, obj_data))
        _validate_upload_files(sample_data, ds.metadata_, ds.data_schema)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Data schema validation failed against source files: {e}",
        ) from e

    version_num = await next_version_number(session, dataset_id)

    v = await create_version(
        session=session,
        dataset_id=dataset_id,
        version_num=version_num,
        user_id=current_user.sub,
        storage_bucket=DATASET_BUCKET,
        description=data.description,
        transfer_method="transfer",
        source_bucket_id=data.source_bucket_id,
        source_files=data.file_paths,
    )

    # Commit so the background task's session can see the new version
    await session.commit()

    # Kick off background copy
    background_tasks.add_task(
        _transfer_files_task,
        version_id=v.id,
        dataset_id=dataset_id,
        dataset_slug=ds.slug,
        dataset_name=ds.name,
        version_num=version_num,
        source_bucket_name=bucket.bucket_name,
        source_file_paths=data.file_paths,
        source_endpoint_url=bucket.endpoint_url,
        source_access_key=access_key or "",
        source_secret_key=secret_key or "",
        source_secure=bucket.secure,
        dest_bucket=DATASET_BUCKET,
        user_id=current_user.sub,
    )

    # Publish event (best-effort)
    from dataset_service.events import publish_dataset_transfer_requested

    await publish_dataset_transfer_requested(
        dataset_id=dataset_id,
        dataset_slug=ds.slug,
        dataset_name=ds.name,
        version=version_num,
        source_bucket_id=data.source_bucket_id,
        file_count=len(data.file_paths),
    )

    return DatasetVersionResponse.model_validate(v)


async def _transfer_files_task(
    version_id: str,
    dataset_id: str,
    dataset_slug: str,
    dataset_name: str,
    version_num: int,
    source_bucket_name: str,
    source_file_paths: list[str],
    source_endpoint_url: str | None,
    source_access_key: str,
    source_secret_key: str,
    source_secure: bool,
    dest_bucket: str,
    user_id: str,
) -> None:
    """Background task: copy files from source bucket to platform storage."""
    import asyncio

    logger.info(
        "[transfer] _transfer_files_task START: version_id=%s files=%s",
        version_id,
        source_file_paths,
    )

    from core.database.postgres import get_async_session_context
    from core.storage import MinIOStore

    if source_endpoint_url:
        parsed = urlparse(source_endpoint_url)
        source_endpoint = parsed.netloc or parsed.path
        source_store = create_object_store(
            endpoint=source_endpoint,
            access_key=source_access_key,
            secret_key=source_secret_key,
            secure=source_secure,
        )
    else:
        source_store = MinIOStore()
    dest_store = get_object_store()
    # Mirror the upload path layout — slug instead of UUID for legibility.
    storage_base = f"datasets/{dataset_slug}/v{version_num}"

    try:
        file_infos = []
        errors: list[str] = []

        for fp in source_file_paths:
            try:
                data = await asyncio.to_thread(source_store.get, source_bucket_name, fp)
                file_size = len(data)
                checksum = await asyncio.to_thread(hashlib.sha256, data)
                checksum_hex = checksum.hexdigest()
                original_name = fp.rsplit("/", 1)[-1] if "/" in fp else fp
                if not original_name:
                    original_name = fp
                storage_key = f"{storage_base}/{original_name}"

                await asyncio.to_thread(
                    dest_store.put,
                    bucket=dest_bucket,
                    key=storage_key,
                    data=io.BytesIO(data),
                    length=file_size,
                    content_type="application/octet-stream",
                )

                file_infos.append(
                    {
                        "file_name": original_name,
                        "file_size": file_size,
                        "content_type": "application/octet-stream",
                        "storage_key": storage_key,
                        "checksum_sha256": checksum_hex,
                    }
                )
            except Exception as e:
                errors.append(f"Failed to transfer '{fp}': {e}")

        async with get_async_session_context() as session:
            await session.commit()  # ensure clean state
            try:
                v = await get_version(session, version_id)
            except NotFoundError:
                logger.error(
                    f"Version {version_id} not found — transfer cancelled (service restart?)"
                )
                return

            if errors and not file_infos:
                v.files = []
                await update_version_status(session, version_id, status="failed", user_id=user_id)
                logger.error(f"Transfer failed for version {version_id}: {'; '.join(errors)}")
            else:
                v.files = file_infos
                await update_version_status(session, version_id, status="ready", user_id=user_id)

                if errors:
                    logger.warning(
                        f"Transfer partial for version {version_id}: {'; '.join(errors)}"
                    )

                from dataset_service.events import publish_dataset_version_uploaded

                total_size = sum(cast(int, f["file_size"]) for f in file_infos)
                await publish_dataset_version_uploaded(
                    dataset_id=dataset_id,
                    dataset_slug=dataset_slug,
                    dataset_name=dataset_name,
                    version=version_num,
                    file_name=cast(str, file_infos[0]["file_name"]),
                    file_size=total_size,
                )

            await session.commit()
    except Exception:
        logger.exception(f"Unexpected error in transfer background task for version {version_id}")


# --- Validation helpers ---


_FORMAT_EXTENSIONS = {
    "csv": ".csv",
    "tsv": ".tsv",
    "parquet": ".parquet",
    "sdf": ".sdf",
    "pdb": ".pdb",
    "fasta": ".fasta",
    "fa": ".fasta",
    "json": ".json",
}


def _extract_columns(content: bytes, filename: str) -> list[str] | None:
    """Extract column names from a file if possible (CSV/TSV/Parquet)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    try:
        if ext in ("csv", "tsv"):
            delimiter = "\t" if ext == "tsv" else ","
            reader = csv.DictReader(io.StringIO(content.decode("utf-8")), delimiter=delimiter)
            if reader.fieldnames:
                return list(reader.fieldnames)
        elif ext == "parquet":
            try:
                import pyarrow.parquet as pq

                table = pq.read_table(io.BytesIO(content))
                return cast(list[str] | None, table.column_names)
            except ImportError:
                pass
        elif ext == "json":
            data = json.loads(content)
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                return list(data[0].keys())
    except Exception:
        pass
    return None


def _validate_upload_files(
    file_contents: list[tuple[str, str | None, bytes]],
    ds_metadata: dict[str, Any],
    data_schema: dict[str, Any] | None = None,
) -> None:
    """Validate file format, required columns, and data schema."""
    file_format = (ds_metadata.get("file_format") or "").lower()
    expected_columns = ds_metadata.get("columns")

    # --- Format check ---
    if file_format:
        expected_ext = _FORMAT_EXTENSIONS.get(file_format)
        if expected_ext:
            for fname, _content_type, _content in file_contents:
                if fname and not fname.lower().endswith(expected_ext):
                    raise HTTPException(
                        status_code=422,
                        detail=f"File '{fname}' does not match expected format '{file_format}' (expected extension '{expected_ext}')",
                    )

    # --- Column check (from metadata) ---
    if expected_columns and isinstance(expected_columns, list):
        required = [str(c).strip() for c in expected_columns if c]
        if required:
            errors = []
            for fname, _content_type, content in file_contents:
                cols = _extract_columns(content, fname or "")
                if cols is not None:
                    missing = [c for c in required if c not in cols]
                    if missing:
                        errors.append(
                            f"File '{fname}' is missing required columns: {', '.join(missing)}"
                        )
            if errors:
                raise HTTPException(status_code=422, detail="\n".join(errors))

    # --- JSON Schema validation ---
    if data_schema is not None:
        _validate_json_schema(file_contents, data_schema)


def _validate_json_schema(
    file_contents: list[tuple[str, str | None, bytes]],
    schema: dict[str, Any],
) -> None:
    """Validate file content against a JSON Schema (draft).

    For tabular formats (CSV/TSV) we check that all required properties
    exist as columns.  For JSON files we validate each record directly.
    """
    import jsonschema

    required_props = set(schema.get("required", []))
    properties = schema.get("properties", {})

    for fname, _content_type, content in file_contents:
        ext = fname.rsplit(".", 1)[-1].lower() if "." in (fname or "") else ""

        if ext in ("csv", "tsv"):
            delimiter = "\t" if ext == "tsv" else ","
            try:
                reader = csv.DictReader(io.StringIO(content.decode("utf-8")), delimiter=delimiter)
                cols = set(reader.fieldnames or [])
            except Exception as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Failed to parse '{fname}' for schema validation: {e}",
                ) from e

            missing = required_props - cols
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"File '{fname}' fails data schema: missing required "
                        f"properties: {', '.join(sorted(missing))}"
                    ),
                )

            # Type-check a sample of rows
            type_errors = _check_column_types(reader, properties)
            if type_errors:
                raise HTTPException(
                    status_code=422,
                    detail=f"File '{fname}' fails data schema: {'; '.join(type_errors[:5])}",
                )

        elif ext == "json":
            try:
                data = json.loads(content)
                records = data if isinstance(data, list) else [data]
                for i, record in enumerate(records):
                    try:
                        jsonschema.validate(record, schema)
                    except jsonschema.ValidationError as e:
                        raise HTTPException(
                            status_code=422,
                            detail=f"File '{fname}' record {i} fails data schema: {e.message}",
                        ) from e
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Failed to validate '{fname}' against data schema: {e}",
                ) from e

        elif ext in ("parquet",):
            try:
                import pyarrow.parquet as pq

                table = pq.read_table(io.BytesIO(content))
                cols = set(table.column_names)
                missing = required_props - cols
                if missing:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"File '{fname}' fails data schema: missing required "
                            f"properties: {', '.join(sorted(missing))}"
                        ),
                    )

                for col, prop in properties.items():
                    if col in cols:
                        _check_parquet_column_type(table, col, prop)
            except HTTPException:
                raise
            except ImportError:
                pass
            except Exception as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Failed to validate '{fname}' against data schema: {e}",
                ) from e


def _check_column_types(reader: csv.DictReader[str], properties: dict[str, Any]) -> list[str]:
    """Sample rows and check column types against schema properties."""
    errors: list[str] = []
    for row_idx, row in enumerate(reader):
        if row_idx >= 20:
            break
        for col, prop in properties.items():
            if col not in row:
                continue
            val = row[col]
            if val is None or val == "":
                continue
            expected_type = prop.get("type", "string")
            try:
                if expected_type == "number":
                    float(val)
                elif expected_type == "integer":
                    int(val)
                elif expected_type == "boolean":
                    if val.lower() not in ("true", "false", "1", "0"):
                        errors.append(
                            f"Column '{col}' row {row_idx}: expected boolean, got '{val}'"
                        )
                elif expected_type == "string":
                    pass
            except (ValueError, TypeError):
                errors.append(
                    f"Column '{col}' row {row_idx}: expected {expected_type}, got '{val}'"
                )
            if len(errors) >= 5:
                break
        if len(errors) >= 5:
            break
    return errors


def _check_parquet_column_type(table: Any, col: str, prop: dict[str, Any]) -> None:
    """Check that a parquet column type matches the schema property."""
    import pyarrow as _pa

    expected_type = prop.get("type", "string")
    pa_type = table.column(col).type
    if expected_type == "number" and not _pa.types.is_floating(pa_type):
        raise HTTPException(
            status_code=422,
            detail=f"Parquet column '{col}' has type {pa_type}, expected float",
        )
    elif expected_type == "integer" and not _pa.types.is_integer(pa_type):
        raise HTTPException(
            status_code=422,
            detail=f"Parquet column '{col}' has type {pa_type}, expected integer",
        )
    elif expected_type == "string" and not _pa.types.is_string(pa_type):
        raise HTTPException(
            status_code=422,
            detail=f"Parquet column '{col}' has type {pa_type}, expected string",
        )


# --- Standard CRUD routes ---


@router.get("", response_model=list[DatasetVersionResponse])
async def list_dataset_versions(
    dataset_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[DatasetVersionResponse]:
    """List all versions of a dataset."""
    await get_dataset(session, dataset_id)
    versions = await list_versions(session, dataset_id)
    return [DatasetVersionResponse.model_validate(v) for v in versions]


@router.get("/{version_id}", response_model=DatasetVersionResponse)
async def get_dataset_version(
    dataset_id: str,
    version_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> DatasetVersionResponse:
    """Get a specific dataset version."""
    v = await get_version(session, version_id)
    return DatasetVersionResponse.model_validate(v)


@router.get("/latest/storage")
async def get_latest_version_storage(
    dataset_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str | int]:
    """Return the storage location of the latest ready version.

    This is an internal endpoint used by the pipeline worker to resolve
    a dataset_id into a MinIO bucket/key for pre-downloading data into
    containers.
    """
    await get_dataset(session, dataset_id)
    versions = await list_versions(session, dataset_id)
    ready = [v for v in versions if v.status == "ready"]
    if not ready:
        from core.exceptions import NotFoundError

        raise NotFoundError("DatasetVersion", f"no ready version for dataset {dataset_id}")
    latest = ready[0]
    files_data = getattr(latest, "files", None) or []
    primary_file = files_data[0] if files_data else None
    if len(files_data) > 1:
        return {
            "storage_bucket": latest.storage_bucket,
            "storage_key": primary_file["storage_key"] if primary_file else "",
            "file_name": primary_file["file_name"] if primary_file else "",
            "version": latest.version,
            "files": files_data,  # type: ignore[dict-item]
        }
    return {
        "storage_bucket": latest.storage_bucket,
        "storage_key": primary_file["storage_key"] if primary_file else "",
        "file_name": primary_file["file_name"] if primary_file else "",
        "version": latest.version,
    }


@router.get("/{version_id}/download")
async def download_version(
    dataset_id: str,
    version_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str | int]:
    """Get a presigned download URL for the primary file of a dataset version."""
    v = await get_version(session, version_id)
    store = get_object_store()
    files = getattr(v, "files", None) or []
    file_info = files[0] if files else None
    if not file_info:
        raise HTTPException(status_code=404, detail="No files in this version")
    return {
        "download_url": store.presigned_url(v.storage_bucket, file_info["storage_key"]),
        "file_name": file_info["file_name"],
        "expires_in_seconds": 3600,
    }


@router.get("/{version_id}/files/{file_index}/download")
async def download_version_file(
    dataset_id: str,
    version_id: str,
    file_index: int,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Get a presigned download URL for a specific file within a dataset version."""
    v = await get_version(session, version_id)
    store = get_object_store()

    files = getattr(v, "files", None) or []
    if file_index < 0 or file_index >= len(files):
        raise HTTPException(
            status_code=404,
            detail=f"File index {file_index} out of range (version has {len(files)} files)",
        )

    file_info = files[file_index]
    return {
        "file_name": file_info["file_name"],
        "download_url": store.presigned_url(v.storage_bucket, file_info["storage_key"]),
        "expires_in_seconds": 3600,
    }


@router.delete("/{version_id}", status_code=204)
async def delete_dataset_version(
    dataset_id: str,
    version_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete a specific dataset version and its files from object storage."""
    v = await get_version(session, version_id)

    files = getattr(v, "files", None) or []
    storage_keys = [{"bucket": v.storage_bucket, "key": f["storage_key"]} for f in files]

    store = get_object_store()
    for sk in storage_keys:
        with contextlib.suppress(Exception):
            store.delete(sk["bucket"], sk["key"])

    await delete_version(session, version_id)


@router.post("/{version_id}/retry-transfer", response_model=DatasetVersionResponse, status_code=202)
async def retry_transfer(
    dataset_id: str,
    version_id: str,
    background_tasks: BackgroundTasks,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> DatasetVersionResponse:
    """Retry a failed transfer on an existing version.

    Re-uses the version's stored ``source_bucket_id`` and ``source_files``
    to re-run the background copy.  The version status is reset to
    ``"transferring"`` and old files are cleared.
    """
    v = await get_version(session, version_id)
    if v.transfer_method != "transfer":
        raise HTTPException(status_code=400, detail="Version was not created by transfer")
    if not v.source_bucket_id or not v.source_files:
        raise HTTPException(
            status_code=400, detail="Version has no source bucket or files to retry"
        )
    if v.status == "ready":
        raise HTTPException(status_code=400, detail="Version is already ready — cannot retry")

    ds = await get_dataset(session, dataset_id)
    org_id = _require_org(current_user)

    # Validate source bucket still exists and is active
    from sqlalchemy import select

    result = await session.execute(
        select(ObjectStoreBucket).where(
            ObjectStoreBucket.id == v.source_bucket_id,
            ObjectStoreBucket.org_id == org_id,
            ObjectStoreBucket.is_active.is_(True),
        )
    )
    bucket = result.scalar_one_or_none()
    if bucket is None:
        raise HTTPException(
            status_code=404,
            detail=f"Source bucket '{v.source_bucket_id}' not found or no longer accessible",
        )

    from core.security.fernet import decrypt_value

    access_key = decrypt_value(bucket.encrypted_access_key) if bucket.encrypted_access_key else None
    secret_key = decrypt_value(bucket.encrypted_secret_key) if bucket.encrypted_secret_key else None

    # Reset version status and clear old files
    v.status = "uploading"
    v.files = []
    v.updated_by = current_user.sub
    await session.commit()

    # Kick off background copy
    background_tasks.add_task(
        _transfer_files_task,
        version_id=v.id,
        dataset_id=dataset_id,
        dataset_slug=ds.slug,
        dataset_name=ds.name,
        version_num=v.version,
        source_bucket_name=bucket.bucket_name,
        source_file_paths=cast("list[str]", v.source_files),
        source_endpoint_url=bucket.endpoint_url,
        source_access_key=access_key or "",
        source_secret_key=secret_key or "",
        source_secure=bucket.secure,
        dest_bucket=DATASET_BUCKET,
        user_id=current_user.sub,
    )

    return DatasetVersionResponse.model_validate(v)


@router.put("/{version_id}/files", response_model=DatasetVersionResponse)
async def replace_version_files_endpoint(
    dataset_id: str,
    version_id: str,
    files: list[UploadFile] = File(...),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> DatasetVersionResponse:
    """Replace all files in an existing dataset version.

    Deletes existing files from object storage, uploads new files
    to the same version directory, and updates the version record.
    """
    v = await get_version(session, version_id)
    ds = await get_dataset(session, dataset_id)

    # Read content and check size
    settings = get_settings()
    max_bytes = settings.max_upload_file_size_mb * 1024 * 1024
    file_contents: list[tuple[str, str | None, bytes]] = []
    for idx, file in enumerate(files):
        content = await file.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File '{file.filename or f'file_{idx}'}' exceeds the "
                    f"{settings.max_upload_file_size_mb} MB upload limit. "
                    "Use the /transfer endpoint for large files."
                ),
            )
        file_contents.append((file.filename or f"file_{idx}", file.content_type, content))

    _validate_upload_files(file_contents, ds.metadata_, ds.data_schema)

    # Delete existing files from object store
    store = get_object_store()
    existing_files = getattr(v, "files", None) or []
    for f in existing_files:
        with contextlib.suppress(Exception):
            store.delete(v.storage_bucket, f["storage_key"])

    storage_base = (
        "/".join(existing_files[0]["storage_key"].split("/")[:-1]) if existing_files else ""
    )
    if not storage_base:
        raise HTTPException(status_code=404, detail="Version has no files to replace")

    file_infos = []
    for _idx, (original_name, content_type, content) in enumerate(file_contents):
        file_size = len(content)
        checksum = hashlib.sha256(content).hexdigest()
        storage_key = f"{storage_base}/{original_name}"

        store.put(
            bucket=v.storage_bucket,
            key=storage_key,
            data=io.BytesIO(content),
            length=file_size,
            content_type=content_type or "application/octet-stream",
        )

        file_infos.append(
            {
                "file_name": original_name,
                "file_size": file_size,
                "content_type": content_type or "application/octet-stream",
                "storage_key": storage_key,
                "checksum_sha256": checksum,
            }
        )

    v = await replace_version_files(
        session=session,
        version_id=version_id,
        files=file_infos,
        user_id=current_user.sub,
    )
    v = await update_version_status(session, v.id, status="ready", user_id=current_user.sub)

    return DatasetVersionResponse.model_validate(v)
