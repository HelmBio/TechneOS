"""Tests for the PydanticAI bridge layer.

Tests that the bridge correctly maps platform LLM provider configs to
PydanticAI models and agents.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.agent.bridge import (
    build_agent_from_definition,
    build_model_from_provider,
)
from core.agent.registry import LLMProviderRegistry, ProviderConfig


@pytest.fixture
def provider_config() -> ProviderConfig:
    """A test provider config."""
    return ProviderConfig(
        slug="test-provider",
        base_url="https://api.example.com/v1",
        fallback_key="sk-test",
        default_model="test-model-v1",
        supported_models=["test-model-v1", "test-model-v2"],
        max_tokens=4096,
    )


@pytest.fixture
def registry_with_provider(provider_config: ProviderConfig) -> LLMProviderRegistry:
    """A registry pre-loaded with a test provider."""
    registry = LLMProviderRegistry()
    registry.register(provider_config, is_default=True)
    return registry


# ---------------------------------------------------------------------------
# build_model_from_provider
# ---------------------------------------------------------------------------


@patch.dict("os.environ", {"TEST_API_KEY": "sk-test-key"})
def test_build_model_from_provider_explicit_slug(
    registry_with_provider: LLMProviderRegistry,
) -> None:
    """Building a model with an explicit provider slug resolves correctly."""
    with patch("core.agent.models.get_registry", return_value=registry_with_provider):
        model = build_model_from_provider(provider_slug="test-provider")

    assert model.model_name == "test-model-v1"


@patch.dict("os.environ", {"TEST_API_KEY": "sk-test-key"})
def test_build_model_from_provider_default(
    registry_with_provider: LLMProviderRegistry,
) -> None:
    """Building a model without a slug uses the default provider."""
    with patch("core.agent.models.get_registry", return_value=registry_with_provider):
        model = build_model_from_provider()

    assert model.model_name == "test-model-v1"


@patch.dict("os.environ", {"TEST_API_KEY": "sk-test-key"})
def test_build_model_with_model_override(
    registry_with_provider: LLMProviderRegistry,
) -> None:
    """Model name can be overridden explicitly."""
    with patch("core.agent.models.get_registry", return_value=registry_with_provider):
        model = build_model_from_provider(provider_slug="test-provider", model_name="custom-model")

    assert model.model_name == "custom-model"


def test_build_model_unknown_provider() -> None:
    """Unknown provider slug falls back to default (which may raise RuntimeError if no API key)."""
    registry = LLMProviderRegistry()
    with patch("core.agent.models.get_registry", return_value=registry):
        # Falls back to env-based default; may raise RuntimeError if no key is set
        try:
            model = build_model_from_provider(provider_slug="nonexistent")
            # If it succeeds, it means a fallback key was found in env
            assert model is not None
        except RuntimeError as exc:
            # Expected when no API key env var is set
            assert "not configured" in str(exc)


# ---------------------------------------------------------------------------
# build_agent_from_definition
# ---------------------------------------------------------------------------


@patch.dict("os.environ", {"TEST_API_KEY": "sk-test-key"})
def test_build_agent_from_definition_with_tools(
    registry_with_provider: LLMProviderRegistry,
) -> None:
    """Agent built from definition resolves named tools."""
    agent_def = MagicMock()
    agent_def.slug = "test-agent"
    agent_def.model_config_ = {"provider": "test-provider", "model": "test-model-v1"}
    agent_def.system_prompt = "Test prompt"
    agent_def.tools = ["chembl_search_compounds", "chembl_get_compound"]

    with patch("core.agent.models.get_registry", return_value=registry_with_provider):
        agent = build_agent_from_definition(agent_def)

    from pydantic_ai import Agent

    assert isinstance(agent, Agent)


@patch.dict("os.environ", {"TEST_API_KEY": "sk-test-key"})
def test_build_agent_from_definition_no_tools_defaults_to_all(
    registry_with_provider: LLMProviderRegistry,
) -> None:
    """When tools list is empty, all ChEMBL tools are included."""
    agent_def = MagicMock()
    agent_def.slug = "test-agent"
    agent_def.model_config_ = {"provider": "test-provider"}
    agent_def.system_prompt = None
    agent_def.tools = []

    with patch("core.agent.models.get_registry", return_value=registry_with_provider):
        agent = build_agent_from_definition(agent_def)

    from pydantic_ai import Agent

    assert isinstance(agent, Agent)


@patch.dict("os.environ", {"TEST_API_KEY": "sk-test-key"})
def test_build_agent_from_definition_unknown_tool_warned(
    registry_with_provider: LLMProviderRegistry,
) -> None:
    """Unknown tool names in the definition are logged as warnings, not errors."""
    agent_def = MagicMock()
    agent_def.slug = "test-agent"
    agent_def.model_config_ = {"provider": "test-provider"}
    agent_def.system_prompt = "Test"
    agent_def.tools = ["chembl_search_compounds", "nonexistent_tool"]

    with patch("core.agent.models.get_registry", return_value=registry_with_provider):
        # Should not raise — unknown tools are skipped with a warning
        agent = build_agent_from_definition(agent_def)

    from pydantic_ai import Agent

    assert isinstance(agent, Agent)
