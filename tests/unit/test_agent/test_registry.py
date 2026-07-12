"""Tests for the LLM provider registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.agent.registry import LLMProviderRegistry, ProviderConfig

# ---------------------------------------------------------------------------
# ProviderConfig
# ---------------------------------------------------------------------------


class TestProviderConfig:
    def test_api_key_from_fallback(self) -> None:
        config = ProviderConfig(
            slug="test", base_url=None, fallback_key="sk-secret", default_model="m1"
        )
        assert config.api_key == "sk-secret"

    def test_api_key_missing_returns_empty(self) -> None:
        config = ProviderConfig(slug="test", base_url=None, default_model="m1")
        assert config.api_key == ""

    def test_build_client_with_base_url(self) -> None:
        config = ProviderConfig(
            slug="test",
            base_url="https://api.example.com/v1",
            fallback_key="sk-secret",
            default_model="m1",
        )
        client = config.build_client()
        assert client.api_key == "sk-secret"
        assert str(client.base_url).rstrip("/").endswith("/v1")

    def test_build_client_without_base_url(self) -> None:
        config = ProviderConfig(
            slug="test", base_url=None, fallback_key="sk-secret", default_model="m1"
        )
        client = config.build_client()
        assert client.api_key == "sk-secret"


# ---------------------------------------------------------------------------
# LLMProviderRegistry
# ---------------------------------------------------------------------------


class TestLLMProviderRegistry:
    def test_register_and_get(self) -> None:
        registry = LLMProviderRegistry()
        config = ProviderConfig(
            slug="my-provider", base_url=None, fallback_key="sk-test", default_model="m"
        )
        registry.register(config)
        assert registry.get("my-provider") is config

    def test_get_unknown_raises(self) -> None:
        registry = LLMProviderRegistry()
        with pytest.raises(KeyError, match="unknown"):
            registry.get("unknown")

    def test_has(self) -> None:
        registry = LLMProviderRegistry()
        config = ProviderConfig(slug="p", base_url=None, fallback_key="sk-test", default_model="m")
        registry.register(config)
        assert registry.has("p")
        assert not registry.has("nope")

    def test_default_provider(self) -> None:
        registry = LLMProviderRegistry()
        c1 = ProviderConfig(slug="a", base_url=None, fallback_key="sk-test", default_model="m1")
        c2 = ProviderConfig(slug="b", base_url=None, fallback_key="sk-test", default_model="m2")
        registry.register(c1)
        registry.register(c2, is_default=True)
        assert registry.get_default() is c2

    def test_list_providers(self) -> None:
        registry = LLMProviderRegistry()
        c1 = ProviderConfig(slug="a", base_url=None, fallback_key="sk-test", default_model="m1")
        c2 = ProviderConfig(slug="b", base_url=None, fallback_key="sk-test", default_model="m2")
        registry.register(c1)
        registry.register(c2)
        assert len(registry.list_providers()) == 2

    def test_register_provider_from_db_row(self) -> None:
        # DB-row registration moved to core's loader (it decrypts the key at this
        # boundary and hands the SDK a plaintext config); the SDK registry stays
        # crypto/DB-free.
        from unittest.mock import patch

        from core.agent.registry import register_provider_from_db_row

        row = MagicMock()
        row.slug = "db-provider"
        row.base_url = "https://example.com/v1"
        row.encrypted_api_key = None  # key decryption is covered by fernet tests
        row.default_model = "db-model"
        row.supported_models = ["db-model", "db-model-2"]
        row.max_tokens = 8192
        row.is_default = True

        fresh = LLMProviderRegistry()
        with patch("core.agent.registry.get_registry", return_value=fresh):
            register_provider_from_db_row(row)

        config = fresh.get("db-provider")
        assert config.slug == "db-provider"
        assert config.default_model == "db-model"
        assert fresh.get_default() is config

    def test_overwrite_provider(self) -> None:
        registry = LLMProviderRegistry()
        c1 = ProviderConfig(slug="x", base_url=None, fallback_key="sk-test", default_model="m1")
        c2 = ProviderConfig(slug="x", base_url=None, fallback_key="sk-test", default_model="m2")
        registry.register(c1)
        registry.register(c2)
        assert registry.get("x").default_model == "m2"

    def test_default_fallback(self) -> None:
        """When no default is registered, fallback uses env vars."""
        registry = LLMProviderRegistry()
        # The fallback reads from settings, so we just verify it doesn't raise
        fallback = registry.get_default()
        assert fallback.slug.startswith("_env_fallback")
