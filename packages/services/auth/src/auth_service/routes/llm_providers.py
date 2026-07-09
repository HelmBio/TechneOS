"""Org-scoped LLM provider routes — same pattern as teams.

Mounted at /api/v1/orgs/{org_id}/llm-providers.
Uses RBAC require_permission (not superuser-only).
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.crud.admin import write_audit_log
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.database.postgres import get_async_session
from core.exceptions import NotFoundError
from core.models.common import (
    LLMProviderCreate,
    LLMProviderResponse,
    LLMProviderUpdate,
    PaginatedResponse,
    TokenPayload,
)
from core.models.llm_provider import LLMProvider

router = APIRouter()


def _response(p: LLMProvider) -> LLMProviderResponse:
    """Build response with org_name from eagerly-loaded relationship."""
    data = LLMProviderResponse.model_validate(p)
    org = getattr(p, "org", None)
    if org is not None:
        data.org_name = getattr(org, "name", None)
    data.has_api_key = getattr(p, "encrypted_api_key", None) is not None
    return data


@router.get("", response_model=PaginatedResponse)
async def list_org_llm_providers(
    org_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> PaginatedResponse:
    """List LLM providers within an organization."""
    total = (
        await session.execute(
            select(func.count(LLMProvider.id)).where(LLMProvider.org_id == org_id)
        )
    ).scalar_one()
    result = await session.execute(
        select(LLMProvider)
        .where(LLMProvider.org_id == org_id)
        .order_by(LLMProvider.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = list(result.scalars().all())
    return PaginatedResponse(
        items=[_response(p) for p in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=LLMProviderResponse, status_code=201)
async def create_org_llm_provider(
    org_id: str,
    data: LLMProviderCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("llm_provider", "create", "org")),
) -> LLMProviderResponse:
    """Create a new LLM provider within an organization."""
    import uuid

    from core.exceptions import AlreadyExistsError
    from core.security.fernet import encrypt_value

    # Check slug uniqueness
    existing = await session.execute(select(LLMProvider).where(LLMProvider.slug == data.slug))
    if existing.scalar_one_or_none() is not None:
        raise AlreadyExistsError("LLMProvider", data.slug)

    # Clear existing defaults if setting as default
    if data.is_default:
        await session.execute(
            update(LLMProvider)
            .where(LLMProvider.org_id == org_id, LLMProvider.is_default.is_(True))
            .values(is_default=False)
        )

    encrypted_api_key = encrypt_value(data.api_key) if data.api_key else None

    p = LLMProvider(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=data.slug,
        description=data.description,
        provider_type=data.provider_type,
        base_url=data.base_url.strip() if data.base_url else None,
        encrypted_api_key=encrypted_api_key,
        default_model=data.default_model,
        supported_models=data.supported_models,
        max_tokens=data.max_tokens,
        is_default=data.is_default,
        org_id=org_id,
        created_by=current_user.sub,
    )
    session.add(p)
    await session.flush()
    await session.refresh(p, ["org", "creator"])

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="create_llm_provider",
        resource_type="llm_provider",
        resource_id=p.id,
        details={"name": data.name, "slug": data.slug, "org_id": org_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return _response(p)


@router.put("/{provider_id}", response_model=LLMProviderResponse)
async def update_org_llm_provider(
    org_id: str,
    provider_id: str,
    data: LLMProviderUpdate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("llm_provider", "update", "org")),
) -> LLMProviderResponse:
    """Update an LLM provider within an organization."""
    result = await session.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    p = result.scalar_one_or_none()
    if p is None or p.org_id != org_id:
        raise NotFoundError("LLMProvider", provider_id)

    from core.security.fernet import encrypt_value

    update_data = data.model_dump(exclude_unset=True)

    # Strip whitespace from base_url
    if "base_url" in update_data and update_data["base_url"] is not None:
        update_data["base_url"] = update_data["base_url"].strip()

    # Encrypt api_key if provided, then store in encrypted_api_key
    api_key = update_data.pop("api_key", None)
    if api_key is not None:
        update_data["encrypted_api_key"] = encrypt_value(api_key)

    if update_data.get("is_default"):
        await session.execute(
            update(LLMProvider)
            .where(LLMProvider.org_id == org_id, LLMProvider.is_default.is_(True))
            .values(is_default=False)
        )

    for field, value in update_data.items():
        setattr(p, field, value)
    await session.flush()
    await session.refresh(p, ["org", "creator"])

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="update_llm_provider",
        resource_type="llm_provider",
        resource_id=provider_id,
        details=update_data,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return _response(p)


@router.delete("/{provider_id}", status_code=204)
async def delete_org_llm_provider(
    org_id: str,
    provider_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("llm_provider", "delete", "org")),
) -> None:
    """Delete an LLM provider within an organization."""
    result = await session.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    p = result.scalar_one_or_none()
    if p is None or p.org_id != org_id:
        raise NotFoundError("LLMProvider", provider_id)

    await session.delete(p)
    await session.flush()

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="delete_llm_provider",
        resource_type="llm_provider",
        resource_id=provider_id,
        details={"name": p.name, "slug": p.slug, "org_id": org_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
