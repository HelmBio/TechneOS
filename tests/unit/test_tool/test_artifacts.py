"""Tests for the compute artifact inventory and tool-version hard validation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ValidationError


def _session_where_find_returns(artifact):
    """Mock AsyncSession whose ``find_artifact`` lookup yields ``artifact``.

    ``find_artifact`` reads ``result.scalars().first()``; ``next_version_number``
    reads ``result.scalar_one_or_none()``. A single shared result object serves
    both — validation runs first, so its outcome is what these tests pin.
    """
    result = MagicMock()
    result.scalars.return_value.first.return_value = artifact
    result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


class TestToolVersionArtifactValidation:
    async def test_create_rejects_unpublished_image(self):
        from core.schemas.tool import ToolVersionCreate
        from tool_service.crud.versions import create_tool_version

        session = _session_where_find_returns(None)  # nothing in inventory
        data = ToolVersionCreate(docker_image="ghcr.io/x/missing", docker_tag="v9")

        with pytest.raises(ValidationError, match="No published image"):
            await create_tool_version(session, "tool-1", data, user_id="u1")

    async def test_create_rejects_unpublished_wheel(self):
        from core.schemas.tool import ToolVersionCreate
        from tool_service.crud.versions import create_tool_version

        session = _session_where_find_returns(None)
        data = ToolVersionCreate(
            package_name="techneos-tools-missing",
            package_version="0.0.0",
            entry_point="pkg.mod:run",
        )

        with pytest.raises(ValidationError, match="No published wheel"):
            await create_tool_version(session, "tool-1", data, user_id="u1")

    async def test_create_stamps_artifact_lineage_when_present(self):
        from core.schemas.tool import ToolVersionCreate
        from tool_service.crud.versions import create_tool_version

        artifact = MagicMock()
        artifact.id = "art-123"
        session = _session_where_find_returns(artifact)
        data = ToolVersionCreate(docker_image="ghcr.io/x/present", docker_tag="v1")

        v = await create_tool_version(session, "tool-1", data, user_id="u1")

        assert v.container_config.artifact_id == "art-123"


class TestArtifactCrud:
    async def test_register_upsert_refreshes_existing(self):
        from core.models.artifact import ComputeArtifact
        from core.schemas.artifact import ArtifactRegister
        from tool_service.crud.artifacts import register_artifact

        existing = ComputeArtifact(
            id="a1",
            kind="docker_image",
            origin="catalog",
            name="techneos/foo",
            version="latest",
            digest="sha256:old",
            status="available",
            metadata_={},
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock(return_value=result)

        data = ArtifactRegister(
            kind="docker_image",
            origin="catalog",
            name="techneos/foo",
            version="latest",
            digest="sha256:new",
        )
        out = await register_artifact(session, data, user_id="u1")

        assert out is existing
        assert out.digest == "sha256:new"  # mutable tag re-push refreshes digest
        session.add.assert_not_called()  # no duplicate row
