"""Org-scoped ObjectStoreBucket routes — same pattern as LLM providers.

Mounted at /api/v1/orgs/{org_id}/buckets.
Uses RBAC require_permission (not superuser-only).
"""

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.crud.admin import write_audit_log
from core.audit import client_ip as _client_ip
from auth_service.crud.buckets import (
    create_bucket,
    get_bucket,
)
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.database.postgres import get_async_session
from core.exceptions import NotFoundError
from core.models.bucket import ObjectStoreBucket
from core.models.common import PaginatedResponse, TokenPayload
from core.schemas.bucket import BucketCreate, BucketResponse, BucketUpdate
from core.security.fernet import decrypt_value
from core.storage import MinIOStore, ObjectInfo, create_object_store

router = APIRouter()


def _response(b: ObjectStoreBucket) -> BucketResponse:
    """Build response with org_name from eagerly-loaded relationship."""
    data = BucketResponse.model_validate(b)
    org = getattr(b, "org", None)
    if org is not None:
        data.org_name = getattr(org, "name", None)
    data.has_access_key = getattr(b, "encrypted_access_key", None) is not None
    data.has_secret_key = getattr(b, "encrypted_secret_key", None) is not None
    return data


@router.get("", response_model=PaginatedResponse)
async def list_org_buckets(
    org_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> PaginatedResponse:
    """List object store buckets within an organization."""
    total = (
        await session.execute(
            select(func.count(ObjectStoreBucket.id)).where(ObjectStoreBucket.org_id == org_id)
        )
    ).scalar_one()
    result = await session.execute(
        select(ObjectStoreBucket)
        .where(ObjectStoreBucket.org_id == org_id)
        .order_by(ObjectStoreBucket.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = list(result.scalars().all())
    return PaginatedResponse(
        items=[_response(b) for b in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=BucketResponse, status_code=201)
async def create_org_bucket(
    org_id: str,
    data: BucketCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("bucket", "create", "org")),
) -> BucketResponse:
    """Register a new object store bucket for an organization."""
    from core.security.fernet import encrypt_value

    encrypted_access_key = encrypt_value(data.access_key) if data.access_key else None
    encrypted_secret_key = encrypt_value(data.secret_key) if data.secret_key else None

    b = await create_bucket(
        session=session,
        data=data,
        org_id=org_id,
        user_id=current_user.sub,
        encrypted_access_key=encrypted_access_key,
        encrypted_secret_key=encrypted_secret_key,
    )

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="create_bucket",
        resource_type="object_store_bucket",
        resource_id=b.id,
        details={
            "name": data.name,
            "slug": data.slug,
            "bucket_name": data.bucket_name,
            "org_id": org_id,
        },
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _response(b)


@router.put("/{bucket_id}", response_model=BucketResponse)
async def update_org_bucket(
    org_id: str,
    bucket_id: str,
    data: BucketUpdate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("bucket", "update", "org")),
) -> BucketResponse:
    """Update a registered object store bucket."""
    b = await get_bucket(session, bucket_id)
    if b.org_id != org_id:
        raise NotFoundError("ObjectStoreBucket", bucket_id)

    from core.security.fernet import encrypt_value

    update_data = data.model_dump(exclude_unset=True)

    access_key = update_data.pop("access_key", None)
    if access_key is not None:
        update_data["encrypted_access_key"] = encrypt_value(access_key)

    secret_key = update_data.pop("secret_key", None)
    if secret_key is not None:
        update_data["encrypted_secret_key"] = encrypt_value(secret_key)

    for field, value in update_data.items():
        setattr(b, field, value)
    await session.flush()
    await session.refresh(b, ["org", "creator"])

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="update_bucket",
        resource_type="object_store_bucket",
        resource_id=bucket_id,
        details=update_data,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _response(b)


@router.delete("/{bucket_id}", status_code=204)
async def delete_org_bucket(
    org_id: str,
    bucket_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("bucket", "delete", "org")),
) -> None:
    """Delete a registered object store bucket."""
    b = await get_bucket(session, bucket_id)
    if b.org_id != org_id:
        raise NotFoundError("ObjectStoreBucket", bucket_id)

    await session.delete(b)
    await session.flush()

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="delete_bucket",
        resource_type="object_store_bucket",
        resource_id=bucket_id,
        details={"name": b.name, "slug": b.slug, "org_id": org_id},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.get("/{bucket_id}/files", response_model=list[ObjectInfo])
async def list_bucket_files(
    org_id: str,
    bucket_id: str,
    prefix: str = Query("", description="Prefix to filter objects (like a directory path)"),
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> list[ObjectInfo]:
    """List files in a registered object store bucket, optionally filtered by prefix."""
    b = await get_bucket(session, bucket_id)
    if b.org_id != org_id:
        raise NotFoundError("ObjectStoreBucket", bucket_id)
    if not b.is_active:
        raise HTTPException(status_code=400, detail="Bucket is not active")

    access_key = decrypt_value(b.encrypted_access_key) if b.encrypted_access_key else None
    secret_key = decrypt_value(b.encrypted_secret_key) if b.encrypted_secret_key else None

    if b.endpoint_url:
        parsed = urlparse(b.endpoint_url)
        endpoint = parsed.netloc or parsed.path
        store = create_object_store(
            endpoint=endpoint,
            access_key=access_key or "",
            secret_key=secret_key or "",
            secure=b.secure,
        )
    else:
        store = MinIOStore()

    return store.list_objects(b.bucket_name, prefix=prefix)
