"""Tests for attach_step_tool_schemas — resolving the pinned tool-version schema
onto effective steps (PR1 of step-param-schema)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.exceptions import ConflictError
from pipeline_service.crud import versions as crud


class _Result:
    """Minimal stand-in for a SQLAlchemy Result (.scalars().all())."""

    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


def _session(tools, tool_versions):
    session = AsyncMock()
    # Two queries: tools by slug, then their versions.
    session.execute = AsyncMock(side_effect=[_Result(tools), _Result(tool_versions)])
    return session


_TOOL = SimpleNamespace(id="t1", slug="autodock-vina")
_V1 = SimpleNamespace(
    tool_id="t1", version=1, status="deprecated",
    parameters_schema={"properties": {"exhaustiveness": {"type": "integer", "default": 8}}},
)
_V2 = SimpleNamespace(
    tool_id="t1", version=2, status="active",
    parameters_schema={"properties": {"exhaustiveness": {"type": "integer", "default": 16}}},
)


async def test_pinned_version_schema_is_resolved():
    steps = [[{"name": "dock", "tool_slug": "autodock-vina", "tool_version": 1, "parameters": {}}]]
    await crud.attach_step_tool_schemas(_session([_TOOL], [_V1, _V2]), steps)
    schema = steps[0][0]["parameters_schema"]
    assert schema["properties"]["exhaustiveness"]["default"] == 8  # v1, not latest


async def test_null_pin_resolves_latest_active():
    steps = [[{"name": "dock", "tool_slug": "autodock-vina", "tool_version": None, "parameters": {}}]]
    await crud.attach_step_tool_schemas(_session([_TOOL], [_V1, _V2]), steps)
    schema = steps[0][0]["parameters_schema"]
    assert schema["properties"]["exhaustiveness"]["default"] == 16  # active v2


async def test_unknown_tool_yields_empty_schema():
    steps = [[{"name": "x", "tool_slug": "ghost", "tool_version": 1, "parameters": {}}]]
    await crud.attach_step_tool_schemas(_session([], []), steps)
    assert steps[0][0]["parameters_schema"] == {}


async def test_no_tool_slug_is_skipped_without_queries():
    session = AsyncMock()
    session.execute = AsyncMock()
    steps = [[{"name": "x", "parameters": {}}]]
    await crud.attach_step_tool_schemas(session, steps)
    session.execute.assert_not_called()
    assert "parameters_schema" not in steps[0][0]


# ── Subset validation: bindings may only set params the tool schema declares ──


def _step(params):
    return [{"name": "dock", "tool_slug": "autodock-vina", "tool_version": 2, "parameters": params}]


async def test_binding_with_known_params_passes():
    eff = _step({"exhaustiveness": 8})
    bindings = {"dock": {"tool_version": 2, "parameters": {"exhaustiveness": 8}}}
    # _V2 schema declares "exhaustiveness".
    await crud._validate_binding_param_keys(_session([_TOOL], [_V1, _V2]), eff, bindings)


async def test_binding_with_unknown_param_raises():
    eff = _step({"exhaustiveness": 8, "bogus": 1})
    bindings = {"dock": {"tool_version": 2, "parameters": {"exhaustiveness": 8, "bogus": 1}}}
    with pytest.raises(ConflictError, match="bogus"):
        await crud._validate_binding_param_keys(_session([_TOOL], [_V1, _V2]), eff, bindings)


async def test_binding_against_empty_schema_is_not_enforced():
    # Tool version with no declared properties → cannot validate, so allow.
    tv = SimpleNamespace(tool_id="t1", version=2, status="active", parameters_schema={})
    eff = _step({"anything": 1})
    bindings = {"dock": {"tool_version": 2, "parameters": {"anything": 1}}}
    await crud._validate_binding_param_keys(_session([_TOOL], [tv]), eff, bindings)
