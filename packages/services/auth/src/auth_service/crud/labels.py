"""CRUD for platform UI label overrides (stored in ``platform_settings``)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models.platform import PlatformSetting

# The single ``platform_settings`` row that holds the label override map.
LABEL_OVERRIDES_KEY = "label_overrides"


async def get_label_overrides(session: AsyncSession) -> dict[str, str]:
    """Return the current label override map, or an empty dict if unset."""
    result = await session.execute(
        select(PlatformSetting).where(PlatformSetting.key == LABEL_OVERRIDES_KEY)
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.value:
        return {}
    return dict(setting.value)


async def set_label_overrides(session: AsyncSession, overrides: dict[str, str]) -> dict[str, str]:
    """Replace the label override map, creating the row if needed."""
    result = await session.execute(
        select(PlatformSetting).where(PlatformSetting.key == LABEL_OVERRIDES_KEY)
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = PlatformSetting(key=LABEL_OVERRIDES_KEY, value=overrides)
        session.add(setting)
    else:
        setting.value = overrides
    await session.flush()
    return dict(setting.value)
