"""Shared test fixtures."""

import asyncio

# Override settings before any imports
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["POSTGRES_USER"] = "techneos"
# Secrets honor an externally provided env var (e.g. CI); fall back to a dev value.
os.environ.setdefault("POSTGRES_PASSWORD", "techneos_dev_password")
# POSTGRES_DB is force-set (not setdefault) so tests never touch a non-test DB.
os.environ["POSTGRES_DB"] = "techneos_test"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
# A throwaway Fernet key so secret-encrypting CRUD (e.g. LLM provider API keys)
# works in tests without depending on a developer's .env. Honors an external
# value if one is already set.
os.environ.setdefault("SECRETS_ENCRYPTION_KEY", "D4OVI7dJSt4dEsBDT7wa8VOWbZCk77WAT5_i7hdMP_g=")
os.environ["ENVIRONMENT"] = "development"
os.environ["DEBUG"] = "true"


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    return session
