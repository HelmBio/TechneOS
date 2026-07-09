"""CRUD operations for Apps."""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.app import App
from core.schemas.app import AppCreate, AppUpdate


async def get_app(session: AsyncSession, app_id: str) -> App:
    result = await session.execute(select(App).where(App.id == app_id))
    a = result.scalar_one_or_none()
    if a is None:
        raise NotFoundError("App", app_id)
    return a


async def get_app_by_slug(session: AsyncSession, slug: str) -> App | None:
    result = await session.execute(select(App).where(App.slug == slug))
    return result.scalar_one_or_none()


async def create_app(
    session: AsyncSession,
    data: AppCreate,
    org_id: str,
    user_id: str,
) -> App:
    existing = await get_app_by_slug(session, data.slug)
    if existing is not None:
        raise AlreadyExistsError("App", data.slug)

    a = App(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=data.slug,
        description=data.description,
        category=data.category,
        tags=data.tags,
        icon_url=data.icon_url,
        thumbnail_url=data.thumbnail_url,
        launch_mode=data.launch_mode,
        external_url=data.external_url,
        docker_image=data.docker_image,
        docker_tag=data.docker_tag,
        container_port=data.container_port,
        env=data.env,
        resource_requirements=data.resource_requirements,
        health_check_path=data.health_check_path,
        embed_sandbox=data.embed_sandbox,
        embed_allow=data.embed_allow,
        auth_mode=data.auth_mode,
        oidc_client_id=data.oidc_client_id,
        launch_token_audience=data.launch_token_audience,
        launch_token_ttl_seconds=data.launch_token_ttl_seconds,
        status=data.status,
        is_public=data.is_public,
        org_id=org_id,
        created_by=user_id,
    )
    session.add(a)
    await session.flush()
    await session.refresh(a, attribute_names=["creator", "org"])
    return a


async def update_app(
    session: AsyncSession,
    app_id: str,
    data: AppUpdate,
    user_id: str | None = None,
) -> App:
    a = await get_app(session, app_id)
    update_data = data.model_dump(exclude_unset=True)
    update_data.pop("org_id", None)
    for field, value in update_data.items():
        setattr(a, field, value)
    if user_id:
        a.updated_by = user_id
    await session.flush()
    await session.refresh(a, attribute_names=["creator", "updater", "org"])
    return a


async def delete_app(session: AsyncSession, app_id: str) -> None:
    a = await get_app(session, app_id)
    await session.delete(a)
    await session.flush()


async def list_apps(
    session: AsyncSession,
    q: str | None = None,
    category: str | None = None,
    launch_mode: str | None = None,
    is_public: bool | None = None,
    skip: int = 0,
    limit: int = 50,
    extra_filters: list[Any] | None = None,
) -> tuple[list[App], int]:
    stmt = select(App)
    count_stmt = select(func.count(App.id))

    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    if q:
        like = f"%{q}%"
        cond = or_(App.name.ilike(like), App.description.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if category:
        stmt = stmt.where(App.category == category)
        count_stmt = count_stmt.where(App.category == category)

    if launch_mode:
        stmt = stmt.where(App.launch_mode == launch_mode)
        count_stmt = count_stmt.where(App.launch_mode == launch_mode)

    if is_public is not None:
        stmt = stmt.where(App.is_public == is_public)
        count_stmt = count_stmt.where(App.is_public == is_public)

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(App.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
