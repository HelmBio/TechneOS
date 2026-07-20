"""Bridge a platform LLM provider into a PydanticAI model.

Look up a provider in the registry (populated by the platform at startup) and
return a PydanticAI ``OpenAIChatModel`` ready to drive an ``Agent``. The heavier
agent-assembly path (`build_agent_from_definition`, platform tools) lives in
``core.agent.bridge``; the provider registry is in ``core.agent.providers``.
"""

from __future__ import annotations

import logging

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from core.agent.providers import get_registry

logger = logging.getLogger(__name__)


def build_model_from_provider(
    provider_slug: str | None = None,
    model_name: str | None = None,
) -> Model:
    """Bridge a platform LLM provider into a PydanticAI model.

    Looks up the provider in the registry (or uses the default) and builds the
    matching PydanticAI model:

    - ``google`` → the native ``GoogleModel`` (google-genai SDK). Gemini's
      thinking models (2.5+/3.x) require a ``thought_signature`` to be round-
      tripped on multi-step tool calls; the native model handles that, whereas
      the OpenAI-compatibility shim drops it (Gemini then rejects tool follow-ups
      with a 400). Use this provider type for Gemini.
    - anything else (``openai_compatible``) → ``OpenAIChatModel`` over the
      provider's OpenAI-compatible endpoint (OpenAI, Azure, vLLM, Ollama, and
      Gemini's non-thinking models).
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

    resolved_model = model_name or provider.default_model

    if provider.provider_type == "google":
        # Import lazily so non-Gemini deployments don't pull in google-genai.
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        logger.info(
            "Built native Google model: provider=%s model=%s", provider.slug, resolved_model
        )
        return GoogleModel(resolved_model, provider=GoogleProvider(api_key=provider.api_key))

    client = provider.build_client()
    logger.info(
        "Built OpenAI-compatible model: provider=%s model=%s base_url=%s",
        provider.slug,
        resolved_model,
        provider.base_url or "(default)",
    )
    return OpenAIChatModel(resolved_model, provider=OpenAIProvider(openai_client=client))
