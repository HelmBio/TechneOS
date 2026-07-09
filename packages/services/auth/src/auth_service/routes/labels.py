"""Platform UI label override routes.

``GET /admin/labels`` is available to any authenticated user — the web shell
needs the override map to render nav labels. ``PUT /admin/labels`` requires the
``platform_admin`` role.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.crud.labels import get_label_overrides, set_label_overrides
from core.auth.dependencies import get_current_superuser, get_current_user
from core.database.postgres import get_async_session
from core.models.common import TokenPayload
from core.schemas.labels import LabelOverrides, LabelOverridesResponse

router = APIRouter()


@router.get("/labels", response_model=LabelOverridesResponse)
async def get_labels(
    _user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> LabelOverridesResponse:
    """Return the current platform label overrides."""
    overrides = await get_label_overrides(session)
    return LabelOverridesResponse(overrides=overrides)


@router.put("/labels", response_model=LabelOverridesResponse)
async def put_labels(
    data: LabelOverrides,
    _admin: TokenPayload = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> LabelOverridesResponse:
    """Replace the platform label overrides (platform_admin only)."""
    overrides = await set_label_overrides(session, data.overrides)
    return LabelOverridesResponse(overrides=overrides)
