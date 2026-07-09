"""CRUD operations for compute backends."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.compute_backend import ComputeBackend
from core.schemas.compute_backend import ComputeBackendCreate, ComputeBackendUpdate


async def list_compute_backends(
    session: AsyncSession,
    *,
    enabled_only: bool = False,
) -> list[ComputeBackend]:
    stmt = select(ComputeBackend).order_by(ComputeBackend.name)
    if enabled_only:
        stmt = stmt.where(ComputeBackend.status == "enabled")
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_compute_backend_by_name(
    session: AsyncSession, name: str
) -> ComputeBackend:
    result = await session.execute(
        select(ComputeBackend).where(ComputeBackend.name == name)
    )
    backend = result.scalar_one_or_none()
    if backend is None:
        raise NotFoundError("ComputeBackend", name)
    return backend


async def create_compute_backend(
    session: AsyncSession, data: ComputeBackendCreate
) -> ComputeBackend:
    existing = await session.execute(
        select(ComputeBackend).where(ComputeBackend.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise AlreadyExistsError("ComputeBackend", data.name)

    backend = ComputeBackend(
        name=data.name,
        display_name=data.display_name,
        backend_type=data.backend_type,
        description=data.description,
        status=data.status,
        config=data.config,
        capabilities=data.capabilities,
    )
    session.add(backend)
    await session.flush()
    await session.refresh(backend)
    return backend


async def update_compute_backend(
    session: AsyncSession, name: str, data: ComputeBackendUpdate
) -> ComputeBackend:
    backend = await get_compute_backend_by_name(session, name)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(backend, field, value)
    await session.flush()
    await session.refresh(backend)
    return backend


async def delete_compute_backend(session: AsyncSession, name: str) -> None:
    backend = await get_compute_backend_by_name(session, name)
    await session.delete(backend)
    await session.flush()
