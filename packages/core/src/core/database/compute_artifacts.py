"""Read helpers for the compute-artifact inventory.

Shared by the services that gate a definition on a published artifact: tool-service
(tool versions, via ``_resolve_artifacts``) and agent-service (agent
``package_config``). The write/ingest path lives in
the top-level ``setup/register_compute_artifacts.py`` script.
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
