"""Read helpers for the compute-artifact inventory.

Shared by the services that gate a definition on a published artifact: tool-service
(tool versions, via ``_resolve_artifacts``) and agent-service (agent
``package_config``). The write path is tool-service's ``register_artifact`` CRUD
behind ``POST /api/v1/compute-artifacts``, which the catalog build scripts call
on publish (``management.record_artifact``).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models.artifact import ComputeArtifact


async def find_artifact(
    session: AsyncSession,
    *,
    kind: str,
    name: str,
    version: str,
    available_only: bool = True,
) -> ComputeArtifact | None:
    """Look up an artifact by its coordinates (ignores registry_url).

    A wheel is pinned by package name+version, an image by repository+tag; the
    registry it lives in is resolved at runtime, so the lookup is registry-agnostic.
    Returns ``None`` when there is no match (or none with status ``available`` when
    ``available_only``).
    """
    stmt = select(ComputeArtifact).where(
        ComputeArtifact.kind == kind,
        ComputeArtifact.name == name,
        ComputeArtifact.version == version,
    )
    if available_only:
        stmt = stmt.where(ComputeArtifact.status == "available")
    result = await session.execute(stmt.limit(1))
    return result.scalars().first()


async def find_latest_artifact(
    session: AsyncSession,
    *,
    kind: str,
    name: str,
    available_only: bool = True,
) -> ComputeArtifact | None:
    """Return the most recently published artifact for (kind, name), or None.

    Used to pin the platform tool-runtime image: pypi tools run on the current
    published ``techneos/tool-runtime`` recorded in the inventory rather than a
    mutable ``:latest`` tag. Ordered by ``published_at`` so a runtime bump is
    picked up without touching config.
    """
    stmt = select(ComputeArtifact).where(
        ComputeArtifact.kind == kind,
        ComputeArtifact.name == name,
    )
    if available_only:
        stmt = stmt.where(ComputeArtifact.status == "available")
    stmt = stmt.order_by(ComputeArtifact.published_at.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalars().first()
