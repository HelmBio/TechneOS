"""Tests for pipeline version status transitions and the definition-edit lock."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ConflictError
from core.schemas.pipeline import PipelineVersionUpdate
from core.version_lifecycle import InvalidStatusTransitionError
from pipeline_service.crud import versions as crud


def _fake_version(status: str):
    return SimpleNamespace(
        id="pv-1",
        version=1,
        pipeline_id="def-1",
        status=status,
        bindings={},
        changelog=None,
        updated_by=None,
    )


# A parent pipeline whose shape contains the "prep" step the binding targets.
_FAKE_PIPELINE = SimpleNamespace(
    id="def-1",
    steps=[{"name": "prep", "tool_slug": "rdkit-prep", "depends_on": []}],
)

# The binding payload used by the definition-edit-lock tests.
_EDIT_BINDINGS = {"prep": {"tool_version": None, "parameters": {"x": 1}}}


def _session(*, has_runs: bool = False):
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    # pipeline_version_has_runs uses session.scalar.
    session.scalar = AsyncMock(return_value="run-1" if has_runs else None)
    # update_pipeline_version loads the parent shape via session.get(Pipeline, id).
    session.get = AsyncMock(return_value=_FAKE_PIPELINE)
    return session


@pytest.fixture(autouse=True)
def _no_tool_validation(monkeypatch):
    """Bindings edits re-validate tool versions + param keys; stub both here so
    these lifecycle/lock unit tests don't need a real tool schema in the DB."""
    monkeypatch.setattr(crud, "validate_tool_versions", AsyncMock(return_value=None))
    monkeypatch.setattr(crud, "_validate_binding_param_keys", AsyncMock(return_value=None))


class TestStatusTransitions:
    async def test_legal_status_only_transition_applies(self, monkeypatch):
        v = _fake_version("testing")
        monkeypatch.setattr(crud, "get_pipeline_version", AsyncMock(return_value=v))
        session = _session()

        result = await crud.update_pipeline_version(
            session, "pv-1", PipelineVersionUpdate(status="active")
        )

        assert result.status == "active"

    async def test_illegal_transition_rejected(self, monkeypatch):
        v = _fake_version("active")
        monkeypatch.setattr(crud, "get_pipeline_version", AsyncMock(return_value=v))
        session = _session()

        with pytest.raises(InvalidStatusTransitionError):
            await crud.update_pipeline_version(
                session, "pv-1", PipelineVersionUpdate(status="draft")
            )
        assert v.status == "active"


class TestDefinitionEditLock:
    async def test_definition_edit_allowed_for_draft_without_runs(self, monkeypatch):
        v = _fake_version("draft")
        monkeypatch.setattr(crud, "get_pipeline_version", AsyncMock(return_value=v))
        session = _session(has_runs=False)

        result = await crud.update_pipeline_version(
            session, "pv-1", PipelineVersionUpdate(bindings=_EDIT_BINDINGS)
        )

        assert result.bindings == _EDIT_BINDINGS

    async def test_definition_edit_rejected_for_active(self, monkeypatch):
        v = _fake_version("active")
        monkeypatch.setattr(crud, "get_pipeline_version", AsyncMock(return_value=v))
        session = _session(has_runs=False)

        with pytest.raises(ConflictError):
            await crud.update_pipeline_version(
                session, "pv-1", PipelineVersionUpdate(bindings=_EDIT_BINDINGS)
            )

    async def test_definition_edit_rejected_when_has_runs(self, monkeypatch):
        v = _fake_version("draft")
        monkeypatch.setattr(crud, "get_pipeline_version", AsyncMock(return_value=v))
        session = _session(has_runs=True)

        with pytest.raises(ConflictError):
            await crud.update_pipeline_version(
                session, "pv-1", PipelineVersionUpdate(bindings=_EDIT_BINDINGS)
            )

    async def test_status_only_change_allowed_when_has_runs(self, monkeypatch):
        # A run-backed version can still move through its lifecycle; only its
        # definition is frozen.
        v = _fake_version("testing")
        monkeypatch.setattr(crud, "get_pipeline_version", AsyncMock(return_value=v))
        session = _session(has_runs=True)

        result = await crud.update_pipeline_version(
            session, "pv-1", PipelineVersionUpdate(status="active")
        )

        assert result.status == "active"
