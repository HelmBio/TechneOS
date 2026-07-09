"""Compute backend routes — list, create, update, delete."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.database.postgres import get_async_session
from core.models.common import TokenPayload
from core.schemas.compute_backend import (
    ComputeBackendCreate,
    ComputeBackendResponse,
    ComputeBackendUpdate,
)
from tool_service.crud.compute_backends import (
    create_compute_backend,
    delete_compute_backend,
    get_compute_backend_by_name,
    list_compute_backends,
    update_compute_backend,
)

router = APIRouter()


@router.get("", response_model=list[ComputeBackendResponse])
async def list_backends(
    enabled_only: bool = True,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ComputeBackendResponse]:
    backends = await list_compute_backends(session, enabled_only=enabled_only)
    return [ComputeBackendResponse.model_validate(b) for b in backends]


@router.get("/{name}", response_model=ComputeBackendResponse)
async def get_backend(
    name: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> ComputeBackendResponse:
    backend = await get_compute_backend_by_name(session, name)
    return ComputeBackendResponse.model_validate(backend)


@router.post("", response_model=ComputeBackendResponse, status_code=201)
async def create_backend(
    data: ComputeBackendCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("compute_backend", "create", "*")),
) -> ComputeBackendResponse:
    backend = await create_compute_backend(session, data)
    return ComputeBackendResponse.model_validate(backend)


@router.patch("/{name}", response_model=ComputeBackendResponse)
async def update_backend(
    name: str,
    data: ComputeBackendUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("compute_backend", "update", "*")),
) -> ComputeBackendResponse:
    backend = await update_compute_backend(session, name, data)
    return ComputeBackendResponse.model_validate(backend)


@router.delete("/{name}", status_code=204)
async def delete_backend(
    name: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("compute_backend", "delete", "*")),
) -> None:
    await delete_compute_backend(session, name)
