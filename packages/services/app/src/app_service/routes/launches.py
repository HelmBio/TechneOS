"""Cross-app launch audit routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app_service.crud.launches import list_launches
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters
from core.database.postgres import get_async_session
from core.models.app import AppLaunch
from core.models.common import PaginatedResponse, TokenPayload
from core.schemas.app import AppLaunchResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse)
async def list_launches_endpoint(
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "read", "own")),
) -> PaginatedResponse:
    """All launches visible to the current user (scope-filtered by org/own)."""
    scope_filters = build_scope_filters(current_user, AppLaunch, "app")
    items, total = await list_launches(session, skip=skip, limit=limit, extra_filters=scope_filters)
    return PaginatedResponse(
        items=[AppLaunchResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )
