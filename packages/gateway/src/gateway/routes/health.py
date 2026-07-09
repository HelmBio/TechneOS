"""Health and readiness check routes."""

from fastapi import APIRouter

from core.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness check — is the gateway process running?"""
    return {"status": "healthy", "service": "gateway"}


@router.get("/ready")
async def readiness() -> dict[str, object]:
    """Readiness check — are all dependencies reachable?

    Checks PostgreSQL, Valkey, and MinIO connectivity.
    """
    checks: dict[str, object] = {}

    # Check PostgreSQL
    try:
        from core.database.postgres import get_async_engine

        engine = get_async_engine()
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # Check Valkey
    try:
        from core.cache import get_valkey_client

        client = await get_valkey_client()
        await client.ping()
        checks["valkey"] = "ok"
    except Exception as e:
        checks["valkey"] = f"error: {e}"

    # Check MinIO
    try:
        from core.storage import get_object_store

        store = get_object_store()
        settings = get_settings()
        store.ensure_bucket(settings.minio_bucket)
        checks["minio"] = "ok"
    except Exception as e:
        checks["minio"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
    }
