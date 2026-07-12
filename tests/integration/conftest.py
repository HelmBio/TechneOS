"""Shared fixtures for integration tests.

Automatically creates the ``techneos_test`` database if it does not
exist and resets the SQLAlchemy engine/session so every test file gets a
clean connection pointing at the test DB.

Prerequisites: Postgres must be running (``make up``).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Database bootstrap — runs once per test session
# ---------------------------------------------------------------------------

_DB_NAME = "techneos_test"


def _ensure_test_database() -> None:
    """(Re)create the test database fresh for this session (uses psycopg2 sync).

    Dropped and recreated every session rather than reused: the DB accumulates
    tables/rows across runs (models get renamed columns, features get removed
    and leave orphan tables), and ``Base.metadata.create_all``/``drop_all``
    only know about tables mapped by *current* models, so stale tables from a
    prior schema can't be cleaned up that way and end up blocking drops via
    dangling FKs. A drop+create of the whole DB sidesteps that entirely.
    """
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    user = os.environ.get("POSTGRES_USER", "techneos")
    password = os.environ.get("POSTGRES_PASSWORD", "techneos_dev_password")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")

    conn = psycopg2.connect(
        dbname="postgres",
        user=user,
        password=password,
        host=host,
        port=port,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    # Terminate any lingering connections (e.g. a prior interrupted run) so
    # DROP DATABASE doesn't fail with "database is being accessed by other users".
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (_DB_NAME,),
    )
    cur.execute(f'DROP DATABASE IF EXISTS "{_DB_NAME}"')
    cur.execute(f'CREATE DATABASE "{_DB_NAME}" OWNER "{user}"')
    cur.close()
    conn.close()


def _reset_engine() -> None:
    """Point the core engine/session at the test database."""
    os.environ["POSTGRES_DB"] = _DB_NAME

    from core.config import get_settings

    get_settings.cache_clear()

    from core.database import postgres as pg_module

    pg_module._engine = None
    pg_module._session_factory = None


# ---------------------------------------------------------------------------
# Session-scoped setup: create DB + tables + seed once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_test_db():
    """Ensure the test database, tables, and seed data exist."""
    import asyncio

    try:
        _ensure_test_database()
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")

    _reset_engine()

    # Import every model module so Base.metadata knows about every table —
    # relying on other test files to import a module as a side effect breaks
    # whenever this file (or a subset of tests) runs on its own, since a
    # module never imported never registers its tables/FKs on Base.metadata.
    import core.models.agent
    import core.models.app
    import core.models.artifact
    import core.models.bucket
    import core.models.compute_backend
    import core.models.dataset
    import core.models.llm_provider
    import core.models.notification
    import core.models.pipeline
    import core.models.platform
    import core.models.task_run
    import core.models.tool
    import core.models.tool_run
    import core.models.user  # noqa: F401
    from core.database.postgres import get_async_engine
    from core.database.seed import seed
    from core.models import Base

    async def _setup():
        engine = get_async_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await seed()

    asyncio.get_event_loop().run_until_complete(_setup())

    yield

    # Leave the database intact for debugging; the next session drops and
    # recreates it fresh (see _ensure_test_database).


# ---------------------------------------------------------------------------
# Per-test engine reset (in case a test mutated env vars)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_db_env():
    """Ensure every test points at the test database."""
    _reset_engine()


# ---------------------------------------------------------------------------
# Reusable helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_token() -> str:
    """Return a platform_admin JWT valid for 1 hour."""
    from jose import jwt as jose_jwt

    from core.config import get_settings

    settings = get_settings()
    payload = {
        "sub": "test-admin-integration",
        "email": "admin-integ@test.com",
        "role": "platform_admin",
        "org_id": "org-1",
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jose_jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


@pytest.fixture
def admin_headers(admin_token: str) -> dict[str, str]:
    """Authorization headers with a platform_admin token."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def scientist_token() -> str:
    """Return a scientist JWT valid for 1 hour."""
    from jose import jwt as jose_jwt

    from core.config import get_settings

    settings = get_settings()
    payload = {
        "sub": "test-scientist-integration",
        "email": "sci-integ@test.com",
        "role": "scientist",
        "org_id": "org-1",
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jose_jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


@pytest.fixture
def scientist_headers(scientist_token: str) -> dict[str, str]:
    """Authorization headers with a scientist token."""
    return {"Authorization": f"Bearer {scientist_token}"}


# ---------------------------------------------------------------------------
# Service client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def auth_client():
    """Async test client for the auth service."""
    from auth_service.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def dataset_client():
    """Async test client for the dataset service."""
    from dataset_service.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def tool_client():
    """Async test client for the tool service."""
    from tool_service.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def pipeline_client():
    """Async test client for the pipeline service."""
    from pipeline_service.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
