"""Unit tests for platform tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from platform_assistant.tools import (
    PLATFORM_TOOLS,
    PLATFORM_TOOLS_BUILTIN,
    PlatformDeps,
    get_agent_info,
    get_dataset_info,
    get_pipeline_info,
    get_platform_overview,
    get_tool_info,
    list_agents,
    list_datasets,
    list_pipelines,
    list_tools,
    platform_deps_for,
)


class TestPlatformDepsFor:
    """The single source deciding whether an agent needs PlatformDeps."""

    def test_platform_slug_needs_deps(self):
        assert platform_deps_for(MagicMock(slug="platform-assistant", tools=[])) is PlatformDeps
        assert platform_deps_for(MagicMock(slug="my-assistant", tools=[])) is PlatformDeps

    def test_named_platform_tool_needs_deps(self):
        agent = MagicMock(slug="chembl", tools=["list_datasets"])
        assert platform_deps_for(agent) is PlatformDeps

    def test_plain_agent_needs_no_deps(self):
        assert platform_deps_for(MagicMock(slug="chembl", tools=["search_chembl"])) is None
        assert platform_deps_for(MagicMock(slug="chembl", tools=[])) is None


class FakeCtx:
    """Fake PydanticAI RunContext for testing."""

    def __init__(self, deps: PlatformDeps):
        self.deps = deps


@pytest.fixture
def ctx():
    return FakeCtx(PlatformDeps(jwt_token="test-jwt-token", gateway_url="http://test-gateway:8000"))


@pytest.fixture
def mock_response():
    """Create a mock httpx.Response."""
    resp = AsyncMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# list_datasets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_datasets_success(ctx, mock_response):
    mock_response.json.return_value = {"items": [{"id": "ds-1", "name": "ZINC"}], "total": 1}
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await list_datasets(ctx, limit=5)

    assert result["total"] == 1
    assert result["items"][0]["name"] == "ZINC"
    client_instance.get.assert_called_once()
    call_args = client_instance.get.call_args
    assert "/api/v1/datasets" in call_args[0][0]
    assert call_args[1]["params"]["limit"] == "5"


@pytest.mark.asyncio
async def test_list_datasets_http_error(ctx):
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        error_resp = AsyncMock(spec=httpx.Response)
        error_resp.status_code = 403
        client_instance.get.return_value = error_resp
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=AsyncMock(), response=error_resp
        )
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await list_datasets(ctx, limit=5)

    assert "error" in result
    assert "403" in result["error"]


# ---------------------------------------------------------------------------
# get_dataset_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dataset_info_success(ctx, mock_response):
    mock_response.json.return_value = {"id": "ds-1", "name": "ZINC", "data_type": "molecules"}
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_dataset_info(ctx, "ds-1")

    assert result["id"] == "ds-1"


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_success(ctx, mock_response):
    mock_response.json.return_value = {"items": [{"id": "t-1", "name": "AutoDock"}], "total": 1}
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await list_tools(ctx, limit=5)

    assert result["total"] == 1


# ---------------------------------------------------------------------------
# get_tool_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tool_info_success(ctx, mock_response):
    mock_response.json.return_value = {"id": "t-1", "name": "AutoDock", "category": "docking"}
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_tool_info(ctx, "t-1")

    assert result["category"] == "docking"


# ---------------------------------------------------------------------------
# list_pipelines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pipelines_success(ctx, mock_response):
    mock_response.json.return_value = {"items": [{"id": "p-1", "name": "ADMET"}], "total": 1}
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await list_pipelines(ctx, limit=5)

    assert result["items"][0]["name"] == "ADMET"


# ---------------------------------------------------------------------------
# get_pipeline_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pipeline_info_success(ctx, mock_response):
    mock_response.json.return_value = {"id": "p-1", "name": "ADMET", "steps": []}
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_pipeline_info(ctx, "p-1")

    assert result["name"] == "ADMET"


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agents_success(ctx, mock_response):
    mock_response.json.return_value = {"items": [{"id": "a-1", "name": "ChEMBL"}], "total": 1}
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await list_agents(ctx)

    assert result["total"] == 1


# ---------------------------------------------------------------------------
# get_agent_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_info_success(ctx, mock_response):
    mock_response.json.return_value = {"id": "a-1", "name": "ChEMBL", "tools": ["chembl_search"]}
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_agent_info(ctx, "a-1")

    assert result["tools"] == ["chembl_search"]


# ---------------------------------------------------------------------------
# get_platform_overview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_platform_overview_success(ctx):
    responses = {
        "/api/v1/datasets": {"total": 10, "items": []},
        "/api/v1/tools": {"total": 5, "items": []},
        "/api/v1/pipelines": {"total": 3, "items": []},
        "/api/v1/agents": {"items": [{"id": "a-1"}, {"id": "a-2"}]},
        "/api/v1/apps": {"total": 1, "items": [{"id": "app-1"}]},
    }

    async def fake_get(url, **kwargs):
        resp = AsyncMock(spec=httpx.Response)
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        for path, data in responses.items():
            if path in url:
                resp.json.return_value = data
                return resp
        resp.json.return_value = {}
        return resp

    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.side_effect = fake_get
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_platform_overview(ctx)

    assert result["datasets"]["total"] == 10
    assert result["datasets"]["available"] is True
    assert result["tools"]["total"] == 5
    assert result["pipelines"]["total"] == 3
    assert result["agents"]["total"] == 2
    assert result["apps"]["total"] == 1


@pytest.mark.asyncio
async def test_get_platform_overview_partial_failure(ctx):
    """Overview should return available=False for failed services."""

    async def failing_get(url, **kwargs):
        raise httpx.RequestError("Connection refused")

    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.side_effect = failing_get
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_platform_overview(ctx)

    assert result["datasets"]["available"] is False
    assert result["datasets"]["total"] == 0
    assert result["tools"]["available"] is False


# ---------------------------------------------------------------------------
# Auth header verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_header_sent(ctx, mock_response):
    """Verify JWT is sent in Authorization header."""
    mock_response.json.return_value = {"items": [], "total": 0}
    with patch("platform_assistant.tools.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        await list_datasets(ctx, limit=5)

    call_args = client_instance.get.call_args
    headers = call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer test-jwt-token"


# ---------------------------------------------------------------------------
# PLATFORM_TOOLS list
# ---------------------------------------------------------------------------


def test_platform_tools_list_complete():
    """The 12 gateway-talking tools are always present as built-ins."""
    assert len(PLATFORM_TOOLS_BUILTIN) == 12
    names = {fn.__name__ for fn in PLATFORM_TOOLS_BUILTIN}
    expected = {
        "list_datasets",
        "get_dataset_info",
        "list_tools",
        "get_tool_info",
        "list_pipelines",
        "get_pipeline_info",
        "list_apps",
        "get_app_info",
        "list_agents",
        "get_agent_info",
        "get_platform_overview",
        "delegate_to_agent",
    }
    assert names == expected
    # The runtime PLATFORM_TOOLS list is built-ins plus entry-point contributions
    # from catalog packages (e.g., molecule-property-calculator contributes
    # `calculate_molecule_properties`). It must always be a superset of the
    # built-ins; the exact extra count depends on what's installed.
    assert set(PLATFORM_TOOLS).issuperset(set(PLATFORM_TOOLS_BUILTIN))
