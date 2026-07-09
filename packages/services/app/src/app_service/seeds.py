"""Runtime reconciliation on app_service startup.

Apps are user-registered (no platform seeding). On every app_service startup
we re-deploy all embedded Apps so their ``runtime_endpoint`` is fresh —
Docker Desktop may assign a new random host port when the daemon restarts
(e.g. after ``docker compose down``), leaving the DB record stale.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from core.database.postgres import get_async_session_context
from core.models.app import App

logger = logging.getLogger(__name__)

_NEEDS_DEPLOY = ("pending", "failed", "active")


async def reconcile_embedded_apps() -> None:
    """Enqueue (re)deploys for embedded Apps on startup."""
    from app_service.deployer import enqueue_deploy

    async with get_async_session_context() as session:
        rows = (
            (
                await session.execute(
                    select(App).where(
                        App.launch_mode == "embedded",
                        App.runtime_status.in_(_NEEDS_DEPLOY),
                    )
                )
            )
            .scalars()
            .all()
        )

        for app in rows:
            logger.info(
                "Enqueuing startup deploy for app=%s (status=%s)",
                app.slug,
                app.runtime_status,
            )
            await enqueue_deploy(app.id, app.slug)
