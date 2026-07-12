"""The gateway/portal URLs come from ``PLATFORM_API_URL`` / ``PLATFORM_PORTAL_URL``
(set per environment in the sourced ``.env.<env>``), defaulting to the local
stack. ``--env`` only canonicalises the name used for the token-cache file.
"""

from __future__ import annotations

import pytest

from management.environment import resolve_environment


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.delenv("PLATFORM_API_URL", raising=False)
    monkeypatch.delenv("PLATFORM_PORTAL_URL", raising=False)


def test_defaults_to_local_stack():
    env = resolve_environment("prod")  # name canonicalises, but no URL is set
    assert env.api_url == "http://localhost:8000"
    assert env.portal_url == "http://localhost:3000"


def test_urls_from_env():
    # Simulates having sourced .env.prod.
    import os

    os.environ["PLATFORM_API_URL"] = "https://techneosapi.example.com/"
    os.environ["PLATFORM_PORTAL_URL"] = "https://techneos.example.com"
    try:
        env = resolve_environment("prod")
        assert env.api_url == "https://techneosapi.example.com"  # trailing slash stripped
        assert env.portal_url == "https://techneos.example.com"
    finally:
        del os.environ["PLATFORM_API_URL"], os.environ["PLATFORM_PORTAL_URL"]


def test_env_name_canonicalised():
    assert resolve_environment("local").name == "development"
    assert resolve_environment("prod").name == "production"
    assert resolve_environment("staging").name == "staging"
    assert resolve_environment(None).name == "development"
