"""Bridge a platform LLM provider into a PydanticAI model.

Look up a provider in the registry (populated by the platform at startup) and
return a PydanticAI ``OpenAIChatModel`` ready to drive an ``Agent``. The heavier
agent-assembly path (`build_agent_from_definition`, platform tools) lives in
``core.agent.bridge``; the provider registry is in ``core.agent.providers``.
"""

from __future__ import annotations

import logging

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from core.agent.providers import get_registry

logger = logging.getLogger(__name__)


def build_model_from_provider(
    provider_slug: str | None = None,
    model_name: str | None = None,
) -> OpenAIChatModel:
    """Bridge a platform LLM provider into a PydanticAI OpenAIChatModel.

    Looks up the provider in the registry (or uses the default), builds the
    ``AsyncOpenAI`` client via ``ProviderConfig.build_client()``, and wraps it in a
    PydanticAI ``OpenAIModel``.
    """
    registry = get_registry()
    if provider_slug:
        if registry.has(provider_slug):
            provider = registry.get(provider_slug)
        else:
            logger.warning(
                "Provider '%s' not found in registry, falling back to default", provider_slug
            )
            provider = registry.get_default()
    else:
        provider = registry.get_default()

    client = provider.build_client()
    resolved_model = model_name or provider.default_model

    logger.info(
        "Built PydanticAI model: provider=%s model=%s base_url=%s",
        provider.slug,
        resolved_model,
        provider.base_url or "(default)",
    )
    return OpenAIChatModel(resolved_model, provider=OpenAIProvider(openai_client=client))
