"""Tests for agent CRUD lookup helpers — id-or-slug resolution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import NotFoundError


def _session_returning(obj):
    """Mock AsyncSession whose execute().scalar_one_or_none() yields obj."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _artifact_session(obj):
    """Mock AsyncSession whose execute().scalars().first() yields obj (find_artifact)."""
    result = MagicMock()
    result.scalars.return_value.first.return_value = obj
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


class TestValidatePackageConfig:
    """Agent package_config is gated on the compute-artifact inventory."""

    async def test_null_package_config_skips(self):
        from agent_service.crud.agents import _validate_package_config

        session = AsyncMock()
        await _validate_package_config(session, None)
        session.execute.assert_not_called()

    async def test_missing_coords_skips(self):
        from agent_service.crud.agents import _validate_package_config

        session = AsyncMock()
        await _validate_package_config(session, {"name": "chembl-agent"})  # no version
        session.execute.assert_not_called()

    async def test_unpublished_wheel_raises(self):
        from agent_service.crud.agents import _validate_package_config
        from core.exceptions import ValidationError

        session = _artifact_session(None)  # no matching artifact row
        with pytest.raises(ValidationError, match="No published wheel"):
            await _validate_package_config(
                session, {"name": "chembl-agent", "version": "0.1.0"}
            )

    async def test_published_wheel_passes(self):
        from agent_service.crud.agents import _validate_package_config

        session = _artifact_session(MagicMock())  # available wheel found
        await _validate_package_config(
            session, {"name": "chembl-agent", "version": "0.1.0"}
        )


def _agent_obj(**overrides):
    """Lightweight stand-in for AgentDefinition (only the snapshot fields)."""
    fields = dict(
        system_prompt="p",
        model_config_={"provider": "x"},
        tools=["t1"],
        parameters_schema={},
        default_parameters={},
        package_config=None,
        version_history=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


class TestVersionHistory:
    """version_history accumulates definition snapshots."""

    def test_seeds_version_1(self):
        from agent_service.crud.agents import _append_version_snapshot

        a = _agent_obj()
        _append_version_snapshot(a)
        assert len(a.version_history) == 1
        entry = a.version_history[0]
        assert entry["version"] == 1
        assert entry["system_prompt"] == "p"
        assert entry["model_config"] == {"provider": "x"}
        assert "captured_at" in entry

    def test_no_append_when_unchanged(self):
        from agent_service.crud.agents import _append_version_snapshot

        a = _agent_obj()
        _append_version_snapshot(a)
        _append_version_snapshot(a)  # nothing changed → no new entry
        assert len(a.version_history) == 1

    def test_metadata_only_change_does_not_append(self):
        from agent_service.crud.agents import _append_version_snapshot

        a = _agent_obj()
        _append_version_snapshot(a)
        a.tags = ["new-tag"]  # not a versioned field
        _append_version_snapshot(a)
        assert len(a.version_history) == 1

    def test_appends_on_versioned_change(self):
        from agent_service.crud.agents import _append_version_snapshot

        a = _agent_obj()
        _append_version_snapshot(a)
        a.package_config = {"name": "chembl-agent", "version": "0.2.0"}
        _append_version_snapshot(a)
        assert len(a.version_history) == 2
        assert a.version_history[-1]["version"] == 2
        assert a.version_history[-1]["package_config"]["version"] == "0.2.0"


class TestGetAgentByIdOrSlug:
    async def test_resolves_by_uuid(self):
        from agent_service.crud.agents import get_agent_by_id_or_slug

        agent = MagicMock(id="11111111-1111-1111-1111-111111111111", slug="chembl")
        session = _session_returning(agent)
        out = await get_agent_by_id_or_slug(session, agent.id)
        assert out is agent

    async def test_resolves_by_slug(self):
        from agent_service.crud.agents import get_agent_by_id_or_slug

        agent = MagicMock(id="22222222-2222-2222-2222-222222222222", slug="chembl-research-assistant")
        session = _session_returning(agent)
        # A non-UUID identifier takes the slug branch.
        out = await get_agent_by_id_or_slug(session, "chembl-research-assistant")
        assert out is agent

    async def test_unknown_slug_raises_not_found(self):
        from agent_service.crud.agents import get_agent_by_id_or_slug

        session = _session_returning(None)
        with pytest.raises(NotFoundError):
            await get_agent_by_id_or_slug(session, "does-not-exist")


class TestResolveAgentIdFilter:
    """List filters accept slug-or-id and never raise (missing -> empty result)."""

    async def test_none_passthrough(self):
        from agent_service.crud.agents import resolve_agent_id_filter

        session = AsyncMock()
        assert await resolve_agent_id_filter(session, None) is None
        session.execute.assert_not_called()  # no lookup for an empty filter

    async def test_uuid_passthrough_without_lookup(self):
        from agent_service.crud.agents import resolve_agent_id_filter

        uid = "33333333-3333-3333-3333-333333333333"
        session = AsyncMock()
        assert await resolve_agent_id_filter(session, uid) == uid
        session.execute.assert_not_called()

    async def test_slug_resolves_to_id(self):
        from agent_service.crud.agents import resolve_agent_id_filter

        agent = MagicMock(id="44444444-4444-4444-4444-444444444444")
        session = _session_returning(agent)
        out = await resolve_agent_id_filter(session, "chembl-research-assistant")
        assert out == agent.id

    async def test_unknown_slug_left_as_is(self):
        from agent_service.crud.agents import resolve_agent_id_filter

        session = _session_returning(None)
        # Unknown slug stays as-is so the downstream filter simply matches nothing.
        assert await resolve_agent_id_filter(session, "nope") == "nope"
