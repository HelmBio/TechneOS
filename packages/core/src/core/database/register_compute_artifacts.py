"""Ingest a build-artifacts manifest into the compute_artifacts inventory.

Runs *inside the gateway container* during the deploy stage (alongside
``core.database.seed``), so it writes straight to the DB — no gateway HTTP call,
no admin token. Platform-service and tool-runtime images are built in the
CodePipeline build stage where the gateway isn't reachable; ``build-and-push.sh``
emits a manifest that this script ingests once the stack is up.

The manifest is a JSON array of objects::

    [{"kind": "docker_image", "origin": "platform",
      "name": "techneos/gateway", "version": "abc123def456",
      "registry_url": "…dkr.ecr…", "digest": "sha256:…"}, …]

Read from a path argument or stdin::

    uv run python -m core.database.register_compute_artifacts deploy/build-artifacts.json
    uv run python -m core.database.register_compute_artifacts < manifest.json

Idempotent: upserts on (kind, name, version, registry_url), matching the
``register_artifact`` CRUD used by the HTTP path.
"""
import asyncio
import json
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.postgres import get_async_engine, get_session_factory
from core.models.artifact import ComputeArtifact
from core.models.user import User  # noqa: F401  resolves the published_by FK target


async def _upsert(session: AsyncSession, entry: dict[str, Any]) -> str:
    """Upsert one manifest entry; returns 'created' or 'updated'."""
    kind = entry["kind"]
    name = entry["name"]
    version = entry["version"]
    registry_url = entry.get("registry_url")

    registry_match = (
        ComputeArtifact.registry_url.is_(None)
        if registry_url is None
        else ComputeArtifact.registry_url == registry_url
    )
    existing = (
        await session.execute(
            select(ComputeArtifact).where(
                ComputeArtifact.kind == kind,
                ComputeArtifact.name == name,
                ComputeArtifact.version == version,
                registry_match,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if existing is not None:
        existing.origin = entry.get("origin", existing.origin)
        if entry.get("digest"):
            existing.digest = entry["digest"]
        if entry.get("source_commit_sha"):
            existing.source_commit_sha = entry["source_commit_sha"]
        if existing.status == "deleted":
            existing.status = "available"  # type: ignore[assignment]
        existing.published_at = now  # type: ignore[assignment]
        return "updated"

    session.add(
        ComputeArtifact(
            kind=kind,
            origin=entry.get("origin", "other"),
            name=name,
            version=version,
            registry_url=registry_url,
            digest=entry.get("digest"),
            source_commit_sha=entry.get("source_commit_sha"),
            status="available",
            metadata_=entry.get("metadata", {}),
            published_at=now,
        )
    )
    return "created"


async def register_artifacts(manifest: list[dict[str, Any]]) -> None:
    engine = get_async_engine()
    factory = get_session_factory()
    created = updated = 0
    async with factory() as session:
        for entry in manifest:
            result = await _upsert(session, entry)
            created += result == "created"
            updated += result == "updated"
        await session.commit()
    await engine.dispose()
    print(f"Artifact inventory: {created} created, {updated} updated.")


def main() -> None:
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()
    raw = raw.strip()
    if not raw:
        print("No manifest content — nothing to ingest.")
        return
    manifest = json.loads(raw)
    if not isinstance(manifest, list):
        print("Error: manifest must be a JSON array.", file=sys.stderr)
        sys.exit(1)
    asyncio.run(register_artifacts(manifest))


if __name__ == "__main__":
    main()
