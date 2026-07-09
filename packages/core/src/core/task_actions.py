"""Platform-level controlled vocabulary for task-run *actions*.

Every state change on a ``TaskRun`` is an *action* drawn from this list. The
same slug is used three ways:

1. ``task_run_events.action_type`` — the kind of action that was logged.
2. ``task_run_artifacts.action_type`` — which action produced/consumed a file.
3. The MinIO key segment under
   ``task-runs/{tool_slug}/v{N}/{task_run_id}/{action_type}/…``.

The list lives in ``platform_settings`` (key ``task_action_types``) so a
``platform_admin`` can extend it at runtime — mirroring the ``label_overrides``
pattern in ``auth_service.crud.labels``. The constants below are the seeded
default and the validation fallback used when the row is absent.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.models.platform import PlatformSetting

TASK_ACTION_TYPES_KEY = "task_action_types"

# Ordered default vocabulary. ``produces_artifacts`` flags the actions that may
# carry files (used by the UI to decide whether to show an upload control).
DEFAULT_TASK_ACTION_TYPES: list[dict[str, Any]] = [
    {"slug": "start", "label": "Start", "produces_artifacts": True},
    {"slug": "accept", "label": "Accept", "produces_artifacts": False},
    {"slug": "update", "label": "Update", "produces_artifacts": True},
    {"slug": "delegate", "label": "Delegate", "produces_artifacts": False},
    {"slug": "escalate", "label": "Escalate", "produces_artifacts": False},
    {"slug": "decline", "label": "Decline", "produces_artifacts": False},
    {"slug": "finish", "label": "Finish", "produces_artifacts": True},
    {"slug": "cancel", "label": "Cancel", "produces_artifacts": False},
    {"slug": "remind", "label": "Remind", "produces_artifacts": False},
]

DEFAULT_ACTION_SLUGS: frozenset[str] = frozenset(a["slug"] for a in DEFAULT_TASK_ACTION_TYPES)


async def get_task_action_types(session: AsyncSession) -> list[dict[str, Any]]:
    """Return the platform action-type list, falling back to the default."""
    setting = await session.get(PlatformSetting, TASK_ACTION_TYPES_KEY)
    if setting is not None and setting.value:
        return list(setting.value)
    return [dict(a) for a in DEFAULT_TASK_ACTION_TYPES]


async def get_action_slugs(session: AsyncSession) -> set[str]:
    """Return the set of valid action slugs for validation."""
    return {a["slug"] for a in await get_task_action_types(session)}
