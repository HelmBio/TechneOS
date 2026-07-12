"""Tests for pipeline type <-> tool-kind validation (create path)."""

from unittest.mock import AsyncMock

import pytest

from core.exceptions import ValidationError
from pipeline_service.crud import pipelines as crud


class _Rows:
    """Stand-in for a SQLAlchemy Result of (slug, tool_type) rows (.all())."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _session(rows):
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Rows(rows))
    return session


def test_implied_pipeline_type_rules():
    assert crud._implied_pipeline_type([]) is None
    assert crud._implied_pipeline_type(["container", "pypi"]) == "compute"
    assert crud._implied_pipeline_type(["human", "human"]) == "interactive"
    assert crud._implied_pipeline_type(["container", "human"]) == "hybrid"
    assert crud._implied_pipeline_type(["api"]) == "hybrid"  # not pypi/container -> hybrid


async def test_compute_passes():
    steps = [{"tool_slug": "a"}, {"tool_slug": "b"}]
    await crud.validate_pipeline_type(
        _session([("a", "container"), ("b", "pypi")]), "compute", steps
    )


async def test_interactive_passes():
    steps = [{"tool_slug": "h1"}, {"tool_slug": "h2"}]
    await crud.validate_pipeline_type(
        _session([("h1", "human"), ("h2", "human")]), "interactive", steps
    )


async def test_mismatch_raises_with_expected_type():
    steps = [{"tool_slug": "a"}, {"tool_slug": "h"}]
    with pytest.raises(ValidationError, match="hybrid"):
        await crud.validate_pipeline_type(
            _session([("a", "container"), ("h", "human")]), "compute", steps
        )


async def test_no_tools_skips_query():
    session = AsyncMock()
    session.execute = AsyncMock()
    await crud.validate_pipeline_type(session, "compute", [{"name": "x"}])
    session.execute.assert_not_called()


# ── Enforcement on update (the metadata-edit modal path) ──────────────────────

from types import SimpleNamespace  # noqa: E402

from core.schemas.pipeline import PipelineUpdate  # noqa: E402


def _pipeline():
    return SimpleNamespace(
        id="p1",
        pipeline_type="compute",
        steps=[{"tool_slug": "autodock-vina"}],
        edges=[],
        parameters_schema={},
        updated_by=None,
    )


async def test_update_rejects_mismatched_type(monkeypatch):
    p = _pipeline()
    monkeypatch.setattr(crud, "get_pipeline", AsyncMock(return_value=p))
    session = _session([("autodock-vina", "container")])  # implies "compute"
    session.flush = AsyncMock()
    with pytest.raises(ValidationError, match="expected 'compute'"):
        await crud.update_pipeline(session, "p1", PipelineUpdate(pipeline_type="interactive"))


async def test_update_allows_matching_type(monkeypatch):
    p = _pipeline()
    monkeypatch.setattr(crud, "get_pipeline", AsyncMock(return_value=p))
    session = _session([("autodock-vina", "container")])
    session.flush = AsyncMock()
    # Same type → validates and passes (get_pipeline mocked for the return).
    await crud.update_pipeline(session, "p1", PipelineUpdate(pipeline_type="compute"))


async def test_update_metadata_only_skips_type_check(monkeypatch):
    p = _pipeline()
    monkeypatch.setattr(crud, "get_pipeline", AsyncMock(return_value=p))
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    await crud.update_pipeline(session, "p1", PipelineUpdate(description="just docs"))
    session.execute.assert_not_called()  # no type resolution query
