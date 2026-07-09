"""Notification service FastAPI application.

Handles subscriptions, notifications, and event-driven notification fanout.
Listens to EventBus events (e.g., tool.version.active) via a background task
and creates in-app notifications for subscribed users.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.database.postgres import dispose_engine, get_async_session_context
from core.exceptions import (
    AlreadyExistsError,
    AuthError,
    InsufficientPermissionsError,
    NotFoundError,
    PlatformError,
    ValidationError,
)

# Import models whose tables are referenced by ForeignKey so SQLAlchemy
# can resolve them when compiling the mapper.
from core.models.user import User  # noqa: F401
from notification_service.crud.notifications import create_bulk_notifications
from notification_service.crud.subscriptions import get_subscribers
from notification_service.routes import notifications, subscriptions

logger = logging.getLogger(__name__)


async def _handle_tool_version_active(payload: dict[str, Any]) -> None:
    """Handle tool.version.active events — notify subscribers."""
    tool_id = payload.get("tool_id", "")
    tool_name = payload.get("tool_name", "Unknown tool")
    version = payload.get("version", "?")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "tool", tool_id)
        if not subscribers:
            return

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Tool] {tool_name} v{version} is now available",
                message=f"[Tool] A new version of {tool_name} has been activated.",
                link=f"/tools/{tool_id}",
                category="tool_update",
                source_type="tool",
                source_id=tool_id,
            )
            for sub in subscribers
        ]
        count = await create_bulk_notifications(session, notifs)
        await session.commit()
        logger.info("Notified %d subscribers about %s v%s", count, tool_name, version)


async def _handle_tool_created(payload: dict[str, Any]) -> None:
    """Handle tool.created events — notify org members / followers."""
    tool_id = payload.get("tool_id", "")
    tool_name = payload.get("tool_name", "Unknown tool")
    tool_slug = payload.get("tool_slug", "")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "tool", tool_id)
        if not subscribers:
            return

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Tool] {tool_name} registered",
                message=f"New tool '{tool_name}' ({tool_slug}) has been registered.",
                link=f"/tools/{tool_id}",
                category="tool_update",
                source_type="tool",
                source_id=tool_id,
            )
            for sub in subscribers
        ]
        count = await create_bulk_notifications(session, notifs)
        await session.commit()
        logger.info("Notified %d subscribers about new tool %s", count, tool_name)


async def _handle_dataset_created(payload: dict[str, Any]) -> None:
    """Handle dataset.created events — notify subscribers."""
    dataset_id = payload.get("dataset_id", "")
    dataset_name = payload.get("dataset_name", "Unknown dataset")
    data_type = payload.get("data_type", "")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "dataset", dataset_id)
        if not subscribers:
            return

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Dataset] New dataset: {dataset_name}",
                message=f"[Dataset] Dataset '{dataset_name}' ({data_type}) has been created.",
                link=f"/datasets/{dataset_id}",
                category="dataset_created",
                source_type="dataset",
                source_id=dataset_id,
            )
            for sub in subscribers
        ]
        count = await create_bulk_notifications(session, notifs)
        await session.commit()
        logger.info("Notified %d subscribers about new dataset %s", count, dataset_name)


async def _handle_dataset_version_uploaded(payload: dict[str, Any]) -> None:
    """Handle dataset.version.uploaded events — notify subscribers."""
    dataset_id = payload.get("dataset_id", "")
    dataset_name = payload.get("dataset_name", "Unknown dataset")
    version = payload.get("version", "?")
    file_name = payload.get("file_name", "")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "dataset", dataset_id)
        if not subscribers:
            return

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Dataset] {dataset_name} v{version} uploaded",
                message=f"[Dataset] Version {version} of '{dataset_name}' has been uploaded ({file_name}).",
                link=f"/datasets/{dataset_id}",
                category="dataset_update",
                source_type="dataset",
                source_id=dataset_id,
            )
            for sub in subscribers
        ]
        count = await create_bulk_notifications(session, notifs)
        await session.commit()
        logger.info("Notified %d subscribers about %s v%s", count, dataset_name, version)


async def _handle_agent_created(payload: dict[str, Any]) -> None:
    """Handle agent.created events — notify subscribers."""
    agent_id = payload.get("agent_id", "")
    agent_name = payload.get("agent_name", "Unknown agent")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "agent", agent_id)
        if not subscribers:
            return

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Agent] New agent: {agent_name}",
                message=f"[Agent] Agent '{agent_name}' has been created.",
                link=f"/agents/{agent_id}",
                category="agent_created",
                source_type="agent",
                source_id=agent_id,
            )
            for sub in subscribers
        ]
        count = await create_bulk_notifications(session, notifs)
        await session.commit()
        logger.info("Notified %d subscribers about new agent %s", count, agent_name)


async def _handle_agent_updated(payload: dict[str, Any]) -> None:
    """Handle agent.updated events — notify subscribers."""
    agent_id = payload.get("agent_id", "")
    agent_name = payload.get("agent_name", "Unknown agent")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "agent", agent_id)
        if not subscribers:
            return

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Agent] {agent_name} updated",
                message=f"[Agent] Agent '{agent_name}' has been updated.",
                link=f"/agents/{agent_id}",
                category="agent_update",
                source_type="agent",
                source_id=agent_id,
            )
            for sub in subscribers
        ]
        count = await create_bulk_notifications(session, notifs)
        await session.commit()
        logger.info("Notified %d subscribers about agent update %s", count, agent_name)


async def _handle_pipeline_created(payload: dict[str, Any]) -> None:
    """Handle pipeline.created events — notify org members."""
    pipeline_id = payload.get("pipeline_id", "")
    pipeline_name = payload.get("pipeline_name", "Unknown pipeline")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "pipeline", pipeline_id)
        if not subscribers:
            return

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Pipeline] New pipeline: {pipeline_name}",
                message=f"[Pipeline] Pipeline '{pipeline_name}' has been created.",
                link=f"/pipelines/{pipeline_id}",
                category="pipeline_created",
                source_type="pipeline",
                source_id=pipeline_id,
            )
            for sub in subscribers
        ]
        count = await create_bulk_notifications(session, notifs)
        await session.commit()
        logger.info("Notified %d subscribers about new pipeline %s", count, pipeline_name)


async def _handle_pipeline_updated(payload: dict[str, Any]) -> None:
    """Handle pipeline.updated events — notify subscribers."""
    pipeline_id = payload.get("pipeline_id", "")
    pipeline_name = payload.get("pipeline_name", "Unknown pipeline")
    version = payload.get("version", "?")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "pipeline", pipeline_id)
        if not subscribers:
            return

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Pipeline] {pipeline_name} updated (v{version})",
                message=f"[Pipeline] Pipeline '{pipeline_name}' has been updated to version {version}.",
                link=f"/pipelines/{pipeline_id}",
                category="pipeline_update",
                source_type="pipeline",
                source_id=pipeline_id,
            )
            for sub in subscribers
        ]
        count = await create_bulk_notifications(session, notifs)
        await session.commit()
        logger.info(
            "Notified %d subscribers about pipeline update %s v%s", count, pipeline_name, version
        )


async def _handle_pipeline_version_created(payload: dict[str, Any]) -> None:
    """Handle pipeline.version.created events — notify subscribers."""
    pipeline_id = payload.get("pipeline_id", "")
    pipeline_name = payload.get("pipeline_name", "Unknown pipeline")
    version = payload.get("version", "?")
    changelog = payload.get("changelog", "")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "pipeline", pipeline_id)
        if not subscribers:
            return

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Pipeline] {pipeline_name} v{version} created",
                message=changelog
                or f"[Pipeline] Version {version} of '{pipeline_name}' has been created.",
                link=f"/pipelines/{pipeline_id}",
                category="pipeline_update",
                source_type="pipeline",
                source_id=pipeline_id,
            )
            for sub in subscribers
        ]
        count = await create_bulk_notifications(session, notifs)
        await session.commit()
        logger.info(
            "Notified %d subscribers about pipeline version %s v%s", count, pipeline_name, version
        )


async def _handle_pipeline_run_completed(payload: dict[str, Any]) -> None:
    """Handle pipeline.run.completed events — notify subscribers and the run submitter."""
    run_id = payload.get("run_id", "")
    pipeline_id = payload.get("pipeline_id", "")
    pipeline_name = payload.get("pipeline_name", "Unknown pipeline")
    submitted_by = payload.get("submitted_by", "")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "pipeline", pipeline_id)
        subscriber_ids = {sub.user_id for sub in subscribers}

        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Run] Run completed — {pipeline_name}",
                message=f"[Run] Pipeline '{pipeline_name}' run {run_id[:8]} completed successfully.",
                link=f"/runs/{run_id}",
                category="pipeline_run",
                source_type="pipeline",
                source_id=pipeline_id,
            )
            for sub in subscribers
        ]

        # Always notify the run submitter even if they are not subscribed
        if submitted_by and submitted_by not in subscriber_ids:
            notifs.append(
                NotificationCreate(
                    user_id=submitted_by,
                    title=f"[Run] Run completed — {pipeline_name}",
                    message=(
                        f"[Run] Your run {run_id[:8]} of '{pipeline_name}' completed successfully."
                    ),
                    link=f"/runs/{run_id}",
                    category="pipeline_run",
                    source_type="pipeline",
                    source_id=pipeline_id,
                )
            )

        if notifs:
            count = await create_bulk_notifications(session, notifs)
            await session.commit()
            logger.info("Notified %d users about pipeline run completed %s", count, run_id[:8])


async def _handle_pipeline_run_failed(payload: dict[str, Any]) -> None:
    """Handle pipeline.run.failed events — notify subscribers and the run submitter."""
    run_id = payload.get("run_id", "")
    pipeline_id = payload.get("pipeline_id", "")
    pipeline_name = payload.get("pipeline_name", "Unknown pipeline")
    submitted_by = payload.get("submitted_by", "")
    error = payload.get("error", "")

    async with get_async_session_context() as session:
        subscribers = await get_subscribers(session, "pipeline", pipeline_id)
        subscriber_ids = {sub.user_id for sub in subscribers}

        from core.schemas.notification import NotificationCreate

        fail_message = error or f"[Run] Pipeline '{pipeline_name}' run {run_id[:8]} failed."
        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Run] Run failed — {pipeline_name}",
                message=fail_message,
                link=f"/runs/{run_id}",
                category="pipeline_run",
                source_type="pipeline",
                source_id=pipeline_id,
            )
            for sub in subscribers
        ]

        # Always notify the run submitter even if they are not subscribed
        if submitted_by and submitted_by not in subscriber_ids:
            notifs.append(
                NotificationCreate(
                    user_id=submitted_by,
                    title=f"[Run] Run failed — {pipeline_name}",
                    message=error or (f"[Run] Your run {run_id[:8]} of '{pipeline_name}' failed."),
                    link=f"/runs/{run_id}",
                    category="pipeline_run",
                    source_type="pipeline",
                    source_id=pipeline_id,
                )
            )

        if notifs:
            count = await create_bulk_notifications(session, notifs)
            await session.commit()
            logger.info("Notified %d users about pipeline run failed %s", count, run_id[:8])


# ── Assignment event handlers ───────────────────────────────────────────


async def _handle_assignment_created(payload: dict[str, Any]) -> None:
    """Handle human.assignment.created events — notify creator + project lead."""
    assignment_id = payload.get("assignment_id", "")
    title = payload.get("title", "Untitled")
    created_by = payload.get("created_by", "")
    project_lead_id = payload.get("project_lead_id", "")

    async with get_async_session_context() as session:
        from core.schemas.notification import NotificationCreate

        notifs: list[NotificationCreate] = []
        target_ids = set()
        if created_by:
            target_ids.add(created_by)
        if project_lead_id:
            target_ids.add(project_lead_id)

        for uid in target_ids:
            if not uid:
                continue
            notifs.append(
                NotificationCreate(
                    user_id=uid,
                    title=f"[Assignment] {title}",
                    message=f"Assignment '{title}' has been created.",
                    link=f"/assignments/{assignment_id}",
                    category="human_assignment",
                    source_type="human_assignment",
                    source_id=assignment_id,
                )
            )

        if notifs:
            count = await create_bulk_notifications(session, notifs)
            await session.commit()
            logger.info("Notified %d users about assignment created %s", count, assignment_id[:8])


async def _handle_assignment_accepted(payload: dict[str, Any]) -> None:
    """Handle human.assignment.accepted events — notify creator."""
    assignment_id = payload.get("assignment_id", "")
    title = payload.get("title", "Untitled")
    accepted_by = payload.get("accepted_by", "")

    async with get_async_session_context() as session:
        from core.schemas.notification import NotificationCreate

        notifs = [
            NotificationCreate(
                user_id=uid,
                title=f"[Assignment] Accepted — {title}",
                message=f"Assignment '{title}' has been accepted.",
                link=f"/assignments/{assignment_id}",
                category="human_assignment",
                source_type="human_assignment",
                source_id=assignment_id,
            )
            for uid in [accepted_by]
            if uid
        ]
        if notifs:
            await create_bulk_notifications(session, notifs)
            await session.commit()
            logger.info("Notified about assignment accepted %s", assignment_id[:8])


async def _handle_assignment_submitted(payload: dict[str, Any]) -> None:
    """Handle human.assignment.submitted events — notify creator + project lead."""
    assignment_id = payload.get("assignment_id", "")
    title = payload.get("title", "Untitled")
    submitted_by = payload.get("submitted_by", "")
    payload.get("tool_name", "")

    async with get_async_session_context() as session:
        from core.schemas.notification import NotificationCreate

        subscribers = await get_subscribers(session, "human_assignment", assignment_id)
        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Assignment] Submitted — {title}",
                message=f"Assignment '{title}' has been completed and submitted.",
                link=f"/assignments/{assignment_id}",
                category="human_assignment",
                source_type="human_assignment",
                source_id=assignment_id,
            )
            for sub in subscribers
        ]
        # Always notify the submitter
        if submitted_by and not any(n.user_id == submitted_by for n in notifs):
            notifs.append(
                NotificationCreate(
                    user_id=submitted_by,
                    title=f"[Assignment] Submitted — {title}",
                    message=f"Your submission for '{title}' has been recorded.",
                    link=f"/assignments/{assignment_id}",
                    category="human_assignment",
                    source_type="human_assignment",
                    source_id=assignment_id,
                )
            )

        if notifs:
            count = await create_bulk_notifications(session, notifs)
            await session.commit()
            logger.info("Notified %d users about assignment submitted %s", count, assignment_id[:8])


async def _handle_assignment_declined(payload: dict[str, Any]) -> None:
    """Handle human.assignment.declined events."""
    assignment_id = payload.get("assignment_id", "")
    title = payload.get("title", "Untitled")

    async with get_async_session_context() as session:
        from core.schemas.notification import NotificationCreate

        subscribers = await get_subscribers(session, "human_assignment", assignment_id)
        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Assignment] Declined — {title}",
                message=f"Assignment '{title}' has been declined.",
                link=f"/assignments/{assignment_id}",
                category="human_assignment",
                source_type="human_assignment",
                source_id=assignment_id,
            )
            for sub in subscribers
        ]
        if notifs:
            count = await create_bulk_notifications(session, notifs)
            await session.commit()
            logger.info("Notified %d users about assignment declined %s", count, assignment_id[:8])


async def _handle_assignment_delegated(payload: dict[str, Any]) -> None:
    """Handle human.assignment.delegated events."""
    assignment_id = payload.get("assignment_id", "")
    title = payload.get("title", "Untitled")
    delegated_to = payload.get("delegated_to", "")

    async with get_async_session_context() as session:
        from core.schemas.notification import NotificationCreate

        notifs = []
        if delegated_to:
            notifs.append(
                NotificationCreate(
                    user_id=delegated_to,
                    title=f"[Assignment] Delegated to you — {title}",
                    message=f"Assignment '{title}' has been delegated to you.",
                    link=f"/assignments/{assignment_id}",
                    category="human_assignment",
                    source_type="human_assignment",
                    source_id=assignment_id,
                )
            )

        if notifs:
            await create_bulk_notifications(session, notifs)
            await session.commit()
            logger.info("Notified about assignment delegated %s", assignment_id[:8])


async def _handle_assignment_escalated(payload: dict[str, Any]) -> None:
    """Handle human.assignment.escalated events — notify project lead."""
    assignment_id = payload.get("assignment_id", "")
    title = payload.get("title", "Untitled")
    escalated_to = payload.get("escalated_to", "")

    async with get_async_session_context() as session:
        from core.schemas.notification import NotificationCreate

        notifs = []
        if escalated_to:
            notifs.append(
                NotificationCreate(
                    user_id=escalated_to,
                    title=f"[Assignment] Escalated — {title}",
                    message=f"Assignment '{title}' has been escalated to you (overdue).",
                    link=f"/assignments/{assignment_id}",
                    category="human_assignment",
                    source_type="human_assignment",
                    source_id=assignment_id,
                )
            )

        if notifs:
            await create_bulk_notifications(session, notifs)
            await session.commit()
            logger.info("Notified about assignment escalated %s", assignment_id[:8])


async def _handle_assignment_cancelled(payload: dict[str, Any]) -> None:
    """Handle human.assignment.cancelled events."""
    assignment_id = payload.get("assignment_id", "")
    title = payload.get("title", "Untitled")

    async with get_async_session_context() as session:
        from core.schemas.notification import NotificationCreate

        subscribers = await get_subscribers(session, "human_assignment", assignment_id)
        notifs = [
            NotificationCreate(
                user_id=sub.user_id,
                title=f"[Assignment] Cancelled — {title}",
                message=f"Assignment '{title}' has been cancelled.",
                link=f"/assignments/{assignment_id}",
                category="human_assignment",
                source_type="human_assignment",
                source_id=assignment_id,
            )
            for sub in subscribers
        ]
        if notifs:
            count = await create_bulk_notifications(session, notifs)
            await session.commit()
            logger.info("Notified %d users about assignment cancelled %s", count, assignment_id[:8])


async def _event_listener() -> None:
    """Background task that subscribes to EventBus channels.

    Reconnects with exponential backoff on connection errors.
    """
    import json as _json

    settings = get_settings()
    import valkey.asyncio as valkey_async
    from valkey.exceptions import ConnectionError as ValkeyConnectionError
    from valkey.exceptions import TimeoutError as ValkeyTimeoutError

    from core.events import EventBus

    # Map event types to their handlers
    channel_handlers: dict[str, Any] = {
        "tool.created": _handle_tool_created,
        "tool.version.active": _handle_tool_version_active,
        "dataset.created": _handle_dataset_created,
        "dataset.version.uploaded": _handle_dataset_version_uploaded,
        "agent.created": _handle_agent_created,
        "agent.updated": _handle_agent_updated,
        "pipeline.created": _handle_pipeline_created,
        "pipeline.updated": _handle_pipeline_updated,
        "pipeline.version.created": _handle_pipeline_version_created,
        "pipeline.run.completed": _handle_pipeline_run_completed,
        "pipeline.run.failed": _handle_pipeline_run_failed,
        "human.assignment.created": _handle_assignment_created,
        "human.assignment.accepted": _handle_assignment_accepted,
        "human.assignment.submitted": _handle_assignment_submitted,
        "human.assignment.declined": _handle_assignment_declined,
        "human.assignment.delegated": _handle_assignment_delegated,
        "human.assignment.escalated": _handle_assignment_escalated,
        "human.assignment.cancelled": _handle_assignment_cancelled,
    }

    backoff = 1.0
    max_backoff = 60.0

    while True:
        try:
            client = valkey_async.from_url(settings.valkey_url)
            bus = EventBus(client)
            channels = ", ".join(channel_handlers.keys())
            logger.info("EventBus listener started — subscribing to %s", channels)
            backoff = 1.0  # reset on successful connection

            # Subscribe to all channels on the same pubsub connection
            for channel in channel_handlers:
                await bus._pubsub.subscribe(bus._channel(channel))

            # Single listen loop dispatching to the right handler
            while True:
                try:
                    message = await bus._pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=30.0,
                    )
                    if message is not None and message["type"] == "message":
                        data = _json.loads(message["data"])
                        event_type = data.get("type", "")
                        handler = channel_handlers.get(event_type)
                        if handler:
                            await handler(data["payload"])
                        else:
                            logger.warning("No handler for event type: %s", event_type)
                except ValkeyTimeoutError:
                    continue
                except ValkeyConnectionError:
                    raise
        except asyncio.CancelledError:
            logger.info("EventBus listener cancelled")
            raise
        except Exception:
            logger.warning(
                "EventBus listener disconnected, retrying in %.0fs",
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown."""
    settings = get_settings()
    print(f"Notification service starting (env={settings.environment})")

    # Start EventBus listener as background task
    listener_task = asyncio.create_task(_event_listener())

    yield

    listener_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await listener_task
    await dispose_engine()
    print("Notification service stopped")


app = FastAPI(
    title="TechneOS — Notification Service",
    description="Subscriptions, notifications, and event-driven alerts",
    version="0.1.0",
    lifespan=lifespan,
)


# --- Exception handlers ---


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": exc.message})


@app.exception_handler(AlreadyExistsError)
async def already_exists_handler(request: Request, exc: AlreadyExistsError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": exc.message})


@app.exception_handler(InsufficientPermissionsError)
async def insufficient_permissions_handler(
    request: Request, exc: InsufficientPermissionsError
) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": exc.message})


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": exc.message})


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.message})


@app.exception_handler(PlatformError)
async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": exc.message})


# --- Routes ---

settings = get_settings()
prefix = settings.api_v1_prefix

app.include_router(subscriptions.router, prefix=f"{prefix}/subscriptions", tags=["subscriptions"])
app.include_router(notifications.router, prefix=f"{prefix}/notifications", tags=["notifications"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "notification"}
