"""Dataset routes — CRUD, search, metadata management."""

import contextlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters, check_resource_access
from core.database.postgres import get_async_session
from core.models.common import PaginatedResponse, TokenPayload
from core.models.dataset import Dataset
from core.schemas.dataset import (
    DatasetCreate,
    DatasetResponse,
    DatasetSearchParams,
    DatasetUpdate,
    DatasetWithVersions,
)
from core.storage import get_object_store
from core.utils import is_uuid
from dataset_service.crud.datasets import (
    create_dataset,
    delete_dataset,
    get_dataset,
    get_dataset_by_slug,
    search_datasets,
    update_dataset,
)
from dataset_service.crud.versions import get_version_by_number, list_versions

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_org(current_user: TokenPayload) -> str:
    """Extract org_id from token, raising 403 if absent."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


@router.post("", response_model=DatasetResponse, status_code=201)
async def create_dataset_endpoint(
    data: DatasetCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("dataset", "create", "*")),
) -> DatasetResponse:
    """Create a new dataset."""
    org_id = _require_org(current_user)
    ds = await create_dataset(session, data, org_id=org_id, user_id=current_user.sub)

    # Publish event (best-effort, does not block response)
    from dataset_service.events import publish_dataset_created

    await publish_dataset_created(
        dataset_id=ds.id,
        dataset_slug=ds.slug,
        dataset_name=ds.name,
        data_type=ds.data_type,
        is_public=ds.is_public,
        created_by=current_user.sub,
    )

    return DatasetResponse.model_validate(ds)


@router.get("", response_model=PaginatedResponse)
async def list_datasets(
    q: str | None = None,
    data_type: str | None = None,
    tags: list[str] | None = Query(default=None),
    is_public: bool | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("dataset", "read", "own")),
) -> PaginatedResponse:
    """Search / list datasets."""
    scope_filters = build_scope_filters(current_user, Dataset, "dataset")
    params = DatasetSearchParams(
        q=q,
        data_type=data_type,
        tags=tags,
        is_public=is_public,
        skip=skip,
        limit=limit,
    )
    items, total = await search_datasets(session, params, extra_filters=scope_filters)
    return PaginatedResponse(
        items=[DatasetResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/resolve-storage")
async def resolve_dataset_storage(
    ref: str = Query(..., description="Dataset reference: slug:vN, slug (latest), or UUID"),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str | int]:
    """Resolve a dataset reference to its MinIO storage location.

    Accepts these formats:
    - ``my-dataset:v2`` — specific version by slug
    - ``my-dataset`` — latest ready version by slug
    - ``<uuid>:v3`` — specific version by dataset UUID
    - ``<uuid>`` — latest ready version by dataset UUID

    Returns ``{storage_bucket, storage_key, file_name, version, dataset_id}``.
    Used internally by the pipeline worker to download datasets into containers.
    """
    # Parse ref into (identifier, version_num)
    version_num: int | None = None
    identifier = ref
    if ":v" in ref:
        parts = ref.rsplit(":v", 1)
        identifier = parts[0]
        try:
            version_num = int(parts[1])
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid version format in '{ref}' — expected :vN"
            ) from None

    # Resolve identifier to dataset — try UUID first, then slug
    ds = None
    with contextlib.suppress(Exception):
        ds = await get_dataset(session, identifier)
    if ds is None:
        ds = await get_dataset_by_slug(session, identifier)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"Dataset not found: '{identifier}'")

    # Resolve version
    if version_num is not None:
        v = await get_version_by_number(session, ds.id, version_num)
        if v is None:
            raise HTTPException(
                status_code=404,
                detail=f"Version v{version_num} not found for dataset '{identifier}'",
            )
        if v.status != "ready":
            raise HTTPException(
                status_code=409,
                detail=f"Version v{version_num} of '{identifier}' has status '{v.status}', expected 'ready'",
            )
    else:
        # Latest ready version
        versions = await list_versions(session, ds.id)
        ready = [v for v in versions if v.status == "ready"]
        if not ready:
            raise HTTPException(
                status_code=404, detail=f"No ready versions for dataset '{identifier}'"
            )
        v = ready[0]

    files = getattr(v, "files", None) or []
    primary_file = files[0] if files else None
    return {
        "dataset_id": ds.id,
        "storage_bucket": v.storage_bucket,
        "storage_key": primary_file["storage_key"] if primary_file else "",
        "file_name": primary_file["file_name"] if primary_file else "",
        "version": v.version,
    }


@router.get("/{identifier}", response_model=DatasetWithVersions)
async def get_dataset_endpoint(
    identifier: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("dataset", "read", "own")),
) -> DatasetWithVersions:
    """Get a dataset with all its versions. Accepts UUID or slug."""
    if is_uuid(identifier):
        ds = await get_dataset(session, identifier)
    else:
        _obj = await get_dataset_by_slug(session, identifier)
        if _obj is None:
            raise HTTPException(status_code=404, detail=f"Dataset '{identifier}' not found")
        ds = _obj
    check_resource_access(current_user, ds, resource_name="dataset")
    versions = await list_versions(session, ds.id)
    base = DatasetResponse.model_validate(ds)
    from core.schemas.dataset import DatasetVersionResponse

    return DatasetWithVersions(
        **base.model_dump(),
        versions=[DatasetVersionResponse.model_validate(v) for v in versions],
    )


@router.patch("/{dataset_id}", response_model=DatasetResponse)
async def update_dataset_endpoint(
    dataset_id: str,
    data: DatasetUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("dataset", "update", "own")),
) -> DatasetResponse:
    """Update dataset metadata."""
    ds = await get_dataset(session, dataset_id)
    check_resource_access(current_user, ds, resource_name="dataset", write=True)
    ds = await update_dataset(session, dataset_id, data, current_user.sub)
    return DatasetResponse.model_validate(ds)


@router.delete("/{dataset_id}", status_code=204)
async def delete_dataset_endpoint(
    dataset_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("dataset", "delete", "own")),
) -> None:
    """Delete a dataset and all its versions.

    Also removes every file from object storage so we don't leak blobs in
    MinIO. Mirrors the per-version DELETE handler — failures on individual
    objects are logged but don't block the DB delete (treat storage cleanup
    as best-effort; a stale orphan is recoverable, but a wedged DB row is
    not).
    """
    ds = await get_dataset(session, dataset_id)
    check_resource_access(current_user, ds, resource_name="dataset", write=True)

    store = get_object_store()
    for v in ds.versions or []:
        for f in getattr(v, "files", None) or []:
            key = f.get("storage_key")
            if not key:
                continue
            try:
                store.delete(v.storage_bucket, key)
            except Exception as e:
                logger.warning(
                    "Failed to delete dataset object %s/%s during dataset %s removal: %s",
                    v.storage_bucket,
                    key,
                    dataset_id,
                    e,
                )

    await delete_dataset(session, dataset_id)
