"""API key management routes."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.providers import hash_password
from core.database.postgres import get_async_session
from core.exceptions import NotFoundError
from core.models.common import ApiKeyCreate, ApiKeyCreated, ApiKeyResponse, TokenPayload
from core.models.user import ApiKey

router = APIRouter()


def _generate_api_key() -> tuple[str, str, str]:
    """Generate an API key.

    Returns (full_key, prefix, secret) where:
    - full_key = "techneos_{prefix}_{secret}" (shown to user once)
    - prefix = first 8 chars (stored in DB for identification)
    - key_hash = bcrypt hash of the full key (stored in DB)
    """
    prefix = secrets.token_hex(4)  # 8 hex chars
    secret = secrets.token_urlsafe(32)
    full_key = f"techneos_{prefix}_{secret}"
    return full_key, prefix, hash_password(full_key)


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    data: ApiKeyCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> ApiKeyCreated:
    """Create a new API key for the current user.

    The full key is returned ONCE in the response. Store it securely.
    """
    full_key, prefix, key_hash = _generate_api_key()

    expires_at = None
    if data.expires_in_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=data.expires_in_days)

    api_key = ApiKey(
        id=str(uuid.uuid4()),
        name=data.name,
        prefix=prefix,
        key_hash=key_hash,
        user_id=current_user.sub,
        scopes=data.scopes,
        expires_at=expires_at,
    )
    session.add(api_key)
    await session.flush()

    return ApiKeyCreated(
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        key=full_key,
        scopes=api_key.scopes,
        is_active=api_key.is_active,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
        created_at=api_key.created_at,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ApiKeyResponse]:
    """List all API keys for the current user."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.user_id == current_user.sub).order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Revoke (deactivate) an API key."""
    result = await session.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == current_user.sub,
        )
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise NotFoundError("API Key", key_id)

    key.is_active = False
    await session.flush()
