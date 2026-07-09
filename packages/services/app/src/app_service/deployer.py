"""Background worker that deploys embedded Apps.

Subscribes to an in-process asyncio queue. Two job types: ``deploy`` and
``stop``. The Docker backend uses the local Docker daemon (good for dev);
a future Kubernetes backend would create per-app Deployment+Service.

The deployer updates the App row's ``runtime_status`` and
``runtime_endpoint`` so the reverse proxy and the UI can react.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from sqlalchemy import select

from core.config import get_settings
from core.database.postgres import get_async_session_context
from core.models.app import App

logger = logging.getLogger(__name__)

CONTAINER_NAME_PREFIX = "techneos-app-"
HEALTH_POLL_SECONDS = 1.0
HEALTH_POLL_MAX_ATTEMPTS = 60  # ~60s


@dataclass
class DeployJob:
    op: Literal["deploy", "stop"]
    app_id: str | None
    slug: str  # always set so stops work even after the row is deleted


_queue: asyncio.Queue[DeployJob] = asyncio.Queue()
_worker_task: asyncio.Task[Any] | None = None


async def enqueue_deploy(app_id: str, slug: str) -> None:
    await _queue.put(DeployJob(op="deploy", app_id=app_id, slug=slug))


async def enqueue_stop(app_id: str | None, slug: str) -> None:
    await _queue.put(DeployJob(op="stop", app_id=app_id, slug=slug))


# ---------- worker ----------


async def start_worker() -> None:
    """Start the background worker task. Idempotent."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_run_worker(), name="app-deployer")


async def stop_worker() -> None:
    global _worker_task
    if _worker_task is None:
        return
    _worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await _worker_task
    _worker_task = None


async def _run_worker() -> None:
    settings = get_settings()
    backend = _make_backend(settings.app_deployer_backend)
    logger.info("App deployer worker started (backend=%s)", settings.app_deployer_backend)
    while True:
        try:
            job = await _queue.get()
            try:
                if job.op == "deploy" and job.app_id is not None:
                    await _do_deploy(backend, job.app_id)
                elif job.op == "stop":
                    await _do_stop(backend, job.app_id, job.slug)
            except Exception:
                logger.exception("Deployer job failed: %s", job)
            finally:
                _queue.task_done()
        except asyncio.CancelledError:
            logger.info("App deployer worker cancelled")
            raise


# ---------- backends ----------


class DeployBackend:
    async def deploy(self, app: App) -> str:
        """Start the container; return ``host:port`` endpoint when healthy."""
        raise NotImplementedError

    async def stop(self, slug: str) -> None:
        raise NotImplementedError


class DockerDeployer(DeployBackend):
    """Uses the local Docker daemon via the `docker` SDK."""

    def __init__(self) -> None:
        # Lazy import so test envs without docker installed don't break.
        import docker

        self._client = docker.from_env()
        self._settings = get_settings()

    async def deploy(self, app: App) -> str:
        return await asyncio.to_thread(self._deploy_sync, app)

    def _deploy_sync(self, app: App) -> str:
        name = f"{CONTAINER_NAME_PREFIX}{app.slug}"
        image_ref = f"{app.docker_image}:{app.docker_tag or 'latest'}"

        # Stop+remove any existing container for this app
        try:
            existing = self._client.containers.get(name)
            existing.stop(timeout=5)
            existing.remove(force=True)
        except Exception:
            pass

        # Pull image (best-effort — image may be local)
        try:
            self._client.images.pull(image_ref)
        except Exception:
            logger.warning("docker pull failed for %s; falling back to local image", image_ref)

        container = self._client.containers.run(
            image_ref,
            name=name,
            detach=True,
            environment=app.env or {},
            # Publish on all interfaces so the app_service container can
            # reach the port via host.docker.internal (= docker bridge
            # gateway 172.17.0.1) when running on Linux/EC2. Binding to
            # 127.0.0.1 only would put the port on the host's loopback,
            # which IS reachable from app_service-on-host (local dev) but
            # NOT from app_service-in-a-container (prod), so the prod
            # health check times out. Off-box exposure is prevented by
            # the EC2 security group, not by the bind address.
            ports={f"{app.container_port}/tcp": None},
            restart_policy={"Name": "unless-stopped"},
            labels={"techneos.app.slug": app.slug, "techneos.app.id": app.id},
        )
        container.reload()
        port_info = container.attrs["NetworkSettings"]["Ports"].get(f"{app.container_port}/tcp")
        if not port_info:
            raise RuntimeError("container did not expose expected port")
        host_port = port_info[0]["HostPort"]
        return f"{self._settings.app_deployer_host}:{host_port}"

    async def stop(self, slug: str) -> None:
        await asyncio.to_thread(self._stop_sync, slug)

    def _stop_sync(self, slug: str) -> None:
        name = f"{CONTAINER_NAME_PREFIX}{slug}"
        try:
            container = self._client.containers.get(name)
            container.stop(timeout=5)
            container.remove(force=True)
        except Exception:
            pass


def _make_backend(name: str) -> DeployBackend:
    if name == "docker":
        return DockerDeployer()
    raise NotImplementedError(f"deployer backend not implemented: {name}")


# ---------- job execution ----------


async def _do_deploy(backend: DeployBackend, app_id: str) -> None:
    async with get_async_session_context() as session:
        app = (await session.execute(select(App).where(App.id == app_id))).scalar_one()
        app.runtime_status = "building"
        app.last_build_error = None
        await session.commit()

    try:
        async with get_async_session_context() as session:
            app = (await session.execute(select(App).where(App.id == app_id))).scalar_one()
            endpoint = await backend.deploy(app)
            app.runtime_endpoint = endpoint
            app.runtime_status = "deploying"
            await session.commit()
            health_path = app.health_check_path or "/"
            health_url = f"http://{endpoint}{health_path}"

        # Poll outside the session so we don't hold a transaction open.
        ok = await _poll_health(health_url)
        async with get_async_session_context() as session:
            app = (await session.execute(select(App).where(App.id == app_id))).scalar_one()
            if ok:
                app.runtime_status = "active"
                app.last_deployed_at = datetime.now(UTC)
            else:
                app.runtime_status = "failed"
                app.last_build_error = f"health check did not pass at {health_url}"
            await session.commit()
    except Exception as exc:
        logger.exception("deploy failed for %s", app_id)
        async with get_async_session_context() as session:
            app = (await session.execute(select(App).where(App.id == app_id))).scalar_one()
            app.runtime_status = "failed"
            app.last_build_error = str(exc)[:2000]
            await session.commit()


async def _do_stop(backend: DeployBackend, app_id: str | None, slug: str) -> None:
    try:
        await backend.stop(slug)
    except Exception:
        logger.exception("stop failed for slug=%s", slug)

    # Row may already be gone (e.g. when called from delete). Only update if present.
    if app_id is None:
        return
    async with get_async_session_context() as session:
        app = (await session.execute(select(App).where(App.id == app_id))).scalar_one_or_none()
        if app is None:
            return
        app.runtime_status = "stopped"
        app.runtime_endpoint = None
        await session.commit()


async def _poll_health(url: str) -> bool:
    async with httpx.AsyncClient(timeout=2.0) as client:
        for _ in range(HEALTH_POLL_MAX_ATTEMPTS):
            try:
                r = await client.get(url)
                if r.status_code < 500:
                    return True
            except Exception:
                pass
            await asyncio.sleep(HEALTH_POLL_SECONDS)
    return False
