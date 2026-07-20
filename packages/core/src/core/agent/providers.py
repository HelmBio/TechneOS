"""LLM provider registry — resolves provider configs and builds OpenAI clients.

The crypto-free, DB-free core of the platform's provider registry. The platform
populates the singleton from the database at service startup
(``core.agent.registry.load_providers_from_db``), decrypting each key at that
boundary and handing this layer a plaintext ``ProviderConfig``; this module never
touches the database or the encryption layer.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class ProviderConfig:
    """Resolved provider configuration with a plaintext API key."""

    def __init__(
        self,
        slug: str,
        base_url: str | None,
        default_model: str,
        supported_models: list[str] | None = None,
        max_tokens: int | None = None,
        fallback_key: str | None = None,
        provider_type: str = "openai_compatible",
    ) -> None:
        self.slug = slug
        self.base_url = base_url
        self.default_model = default_model
        self.supported_models = supported_models or []
        self.max_tokens = max_tokens
        self._fallback_key = fallback_key
        self.provider_type = provider_type

    @property
    def api_key(self) -> str:
        """The provider's API key (already decrypted by the platform at load time)."""
        if self._fallback_key:
            return self._fallback_key
        logger.warning("No API key available for provider %s", self.slug)
        return ""

    def build_client(self) -> AsyncOpenAI:
        """Build an AsyncOpenAI client for this provider."""
        api_key = self.api_key
        if not api_key:
            raise RuntimeError(
                f"API key is not configured for LLM provider '{self.slug}'. "
                f"Provide it through the admin UI or via the API."
            )
        kwargs: dict[str, Any] = {"api_key": api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url.strip()
        return AsyncOpenAI(**kwargs)


class LLMProviderRegistry:
    """Registry that maps provider slugs to configs.

    Populated from DB rows at startup by the platform, with an env-var-based
    fallback for single-tenant / dev setups.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ProviderConfig] = {}
        self._default_slug: str | None = None

    def register(self, config: ProviderConfig, *, is_default: bool = False) -> None:
        self._providers[config.slug] = config
        if is_default:
            self._default_slug = config.slug

    def get(self, slug: str) -> ProviderConfig:
        if slug in self._providers:
            return self._providers[slug]
        raise KeyError(f"LLM provider '{slug}' not found in registry")

    def get_default(self) -> ProviderConfig:
        if self._default_slug and self._default_slug in self._providers:
            return self._providers[self._default_slug]
        return self._build_fallback()

    def list_providers(self) -> list[ProviderConfig]:
        return list(self._providers.values())

    def has(self, slug: str) -> bool:
        return slug in self._providers

    @staticmethod
    def _build_fallback() -> ProviderConfig:
        """Build a config from env vars as a last resort.

        The primary path is the platform's DB load at startup. This fallback exists
        for when no providers are registered. It checks, in
        order: ``OPENAI_API_KEY``, then ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``
        (Gemini via the OpenAI-compatible endpoint). If none are set it returns a
        config that raises a clear error when ``build_client()`` is called.
        """
        base_url = os.environ.get("OPENAI_BASE_URL", "")
        default_model = os.environ.get("DEFAULT_LLM_MODEL", "gpt-4o")

        if key := os.environ.get("OPENAI_API_KEY"):
            return ProviderConfig(
                slug="_env_fallback",
                base_url=base_url or None,
                default_model=default_model,
                fallback_key=key,
            )

        for env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if key := os.environ.get(env_var):
                logger.info("Using env fallback with %s (Gemini OpenAI-compat)", env_var)
                return ProviderConfig(
                    slug="_env_fallback_gemini",
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    default_model="gemini-2.0-flash",
                    fallback_key=key,
                )

        return ProviderConfig(
            slug="_env_fallback",
            base_url=base_url or None,
            default_model=default_model,
        )


_registry: LLMProviderRegistry | None = None


def get_registry() -> LLMProviderRegistry:
    """Return the global registry singleton (lazy-initialised)."""
    global _registry
    if _registry is None:
        _registry = LLMProviderRegistry()
    return _registry
