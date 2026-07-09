"""CRUD operations for AppLaunch records."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models.app import AppLaunch


async def record_launch(
    session: AsyncSession,
    *,
    app_id: str,
    org_id: str,
    user_id: str,
    launch_mode: str,
    auth_mode: str,
    client_ip: str | None,
    user_agent: str | None,
) -> AppLaunch:
    row = AppLaunch(
        id=str(uuid.uuid4()),
        app_id=app_id,
        org_id=org_id,
        launched_by=user_id,
        launch_mode=launch_mode,
        auth_mode=auth_mode,
        client_ip=client_ip,
        user_agent=(user_agent or None) if user_agent is None else user_agent[:512],
    )
    session.add(row)
    await session.flush()
    await session.refresh(row, attribute_names=["launcher"])
    return row


async def list_launches(
    session: AsyncSession,
    *,
    app_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
    extra_filters: list[Any] | None = None,
) -> tuple[list[AppLaunch], int]:
    stmt = select(AppLaunch)
    count_stmt = select(func.count(AppLaunch.id))

    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    if app_id:
        stmt = stmt.where(AppLaunch.app_id == app_id)
        count_stmt = count_stmt.where(AppLaunch.app_id == app_id)

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(AppLaunch.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
