"""Tests for tool/task version status transitions and the definition-edit lock."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ConflictError
from core.schemas.tool import ToolVersionContentReplace, ToolVersionUpdate
from core.version_lifecycle import InvalidStatusTransitionError
from tool_service.crud import versions as crud


def _fake_version(status: str):
    return SimpleNamespace(
        id="ver-1",
        version=1,
        tool_id="tool-1",
        status=status,
        input_schema={},
        output_schema={},
        parameters_schema={},
        resource_requirements={},
        changelog=None,
        updated_by=None,
    )


def _session(*, has_runs: bool = False):
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    # tool_version_has_runs uses session.scalar; None => no run found.
    session.scalar = AsyncMock(return_value="run-1" if has_runs else None)
    # replace_tool_version_content's config lookups + active-event lookup.
    session.get = AsyncMock(return_value=None)
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=exec_result)
    return session


class TestStatusTransitions:
    async def test_legal_transition_applies(self, monkeypatch):
        v = _fake_version("testing")
        monkeypatch.setattr(crud, "get_tool_version", AsyncMock(return_value=v))
        session = _session()

        result = await crud.update_tool_version(
            session, "ver-1", ToolVersionUpdate(status="active"), user_id="u1"
        )

        assert result.status == "active"

    async def test_illegal_transition_rejected(self, monkeypatch):
        v = _fake_version("active")
        monkeypatch.setattr(crud, "get_tool_version", AsyncMock(return_value=v))
        session = _session()

        with pytest.raises(InvalidStatusTransitionError):
            await crud.update_tool_version(
                session, "ver-1", ToolVersionUpdate(status="draft"), user_id="u1"
            )
        # The illegal value must not have been written.
        assert v.status == "active"


class TestDefinitionEditLock:
    async def test_content_replace_allowed_for_draft_without_runs(self, monkeypatch):
        v = _fake_version("draft")
        monkeypatch.setattr(crud, "get_tool_version", AsyncMock(return_value=v))
        session = _session(has_runs=False)

        result = await crud.replace_tool_version_content(
            session, "ver-1", ToolVersionContentReplace(), user_id="u1"
        )

        assert result.status == "draft"

    async def test_content_replace_rejected_for_active(self, monkeypatch):
        v = _fake_version("active")
        monkeypatch.setattr(crud, "get_tool_version", AsyncMock(return_value=v))
        session = _session(has_runs=False)

        with pytest.raises(ConflictError):
            await crud.replace_tool_version_content(
                session, "ver-1", ToolVersionContentReplace(), user_id="u1"
            )

    async def test_content_replace_rejected_when_has_runs(self, monkeypatch):
        v = _fake_version("draft")
        monkeypatch.setattr(crud, "get_tool_version", AsyncMock(return_value=v))
        session = _session(has_runs=True)

        with pytest.raises(ConflictError):
            await crud.replace_tool_version_content(
                session, "ver-1", ToolVersionContentReplace(), user_id="u1"
            )
