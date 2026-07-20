"""LLM provider registry.

The provider config + registry + client-building logic lives in
``core.agent.providers`` (crypto-free, DB-free). This module re-exports that
surface and keeps the **database-loading** path here — it decrypts each stored key
at this boundary and hands ``providers`` a plaintext ``ProviderConfig``, so the
registry layer stays free of the database and the encryption layer.
"""

from __future__ import annotations

import logging
from typing import Any

from core.agent.providers import (
    LLMProviderRegistry,
    ProviderConfig,
    get_registry,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LLMProviderRegistry",
    "ProviderConfig",
    "get_registry",
    "load_providers_from_db",
    "register_provider_from_db_row",
]


def register_provider_from_db_row(row: Any) -> None:
    """Decrypt the row's API key and register a ProviderConfig in the SDK registry."""
    from core.security.fernet import decrypt_value

    key: str | None = None
    if getattr(row, "encrypted_api_key", None):
        try:
            key = decrypt_value(row.encrypted_api_key)
        except Exception:
            logger.exception("Failed to decrypt API key for provider %s", row.slug)
    config = ProviderConfig(
        slug=row.slug,
        base_url=row.base_url,
        default_model=row.default_model,
        supported_models=row.supported_models or [],
        max_tokens=row.max_tokens,
        fallback_key=key,
        provider_type=getattr(row, "provider_type", "openai_compatible"),
    )
    get_registry().register(config, is_default=bool(row.is_default))


async def load_providers_from_db() -> None:
    """Load all LLM provider rows from the database into the registry.

    Call this once at service startup (inside the lifespan handler).
    """
    from sqlalchemy import select

    from core.database.postgres import get_async_session_context
    from core.models.llm_provider import LLMProvider

    async with get_async_session_context() as session:
        result = await session.execute(select(LLMProvider))
        for row in result.scalars().all():
            register_provider_from_db_row(row)
    logger.info("Loaded %d LLM providers into registry", len(get_registry().list_providers()))
