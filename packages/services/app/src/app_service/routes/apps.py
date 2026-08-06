"""App routes — CRUD, launch, deploy, stop, audit."""

from urllib.parse import urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app_service.crud.apps import (
    create_app,
    delete_app,
    get_app,
    get_app_by_slug,
    list_apps,
    update_app,
)
from app_service.crud.launches import list_launches, record_launch
from app_service.deployer import (
    enqueue_deploy,
    enqueue_stop,
)
from core.auth.dependencies import get_current_user
from core.auth.launch_tokens import mint_launch_token
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters, check_resource_access
from core.config import get_settings
from core.database.postgres import get_async_session
from core.exceptions import PlatformError, ValidationError
from core.models.app import App
from core.models.common import PaginatedResponse, TokenPayload
from core.schemas.app import (
    AppCreate,
    AppLaunchResponse,
    AppLaunchResult,
    AppResponse,
    AppUpdate,
)
from core.audit import client_ip as _client_ip
from core.utils import is_uuid

router = APIRouter()


def _require_org(user: TokenPayload) -> str:
    if not user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return user.org_id


def _append_query(url: str, **params: str) -> str:
    """Append query params to a URL, preserving existing query string."""
    parsed = urlparse(url)
    existing = parsed.query
    new = urlencode({k: v for k, v in params.items() if v is not None})
    combined = "&".join(filter(None, [existing, new]))
    return urlunparse(parsed._replace(query=combined))


@router.post("", response_model=AppResponse, status_code=201)
async def create_app_endpoint(
    data: AppCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "create", "*")),
) -> AppResponse:
    org_id = _require_org(current_user)
    a = await create_app(session, data, org_id=org_id, user_id=current_user.sub)
    if a.launch_mode == "embedded":
        await enqueue_deploy(a.id, a.slug)
    return AppResponse.model_validate(a)


@router.get("", response_model=PaginatedResponse)
async def list_apps_endpoint(
    q: str | None = None,
    category: str | None = None,
    launch_mode: str | None = None,
    is_public: bool | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "read", "own")),
) -> PaginatedResponse:
    scope_filters = build_scope_filters(current_user, App, "app")
    items, total = await list_apps(
        session,
        q=q,
        category=category,
        launch_mode=launch_mode,
        is_public=is_public,
        skip=skip,
        limit=limit,
        extra_filters=scope_filters,
    )
    return PaginatedResponse(
        items=[AppResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{identifier}", response_model=AppResponse)
async def get_app_endpoint(
    identifier: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "read", "own")),
) -> AppResponse:
    """Get an app. Accepts UUID or slug."""
    if is_uuid(identifier):
        a = await get_app(session, identifier)
    else:
        _obj = await get_app_by_slug(session, identifier)
        if _obj is None:
            raise HTTPException(status_code=404, detail=f"App '{identifier}' not found")
        a = _obj
    check_resource_access(current_user, a, resource_name="app")
    return AppResponse.model_validate(a)


@router.patch("/{app_id}", response_model=AppResponse)
async def update_app_endpoint(
    app_id: str,
    data: AppUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "update", "own")),
) -> AppResponse:
    a = await get_app(session, app_id)
    check_resource_access(current_user, a, resource_name="app", write=True)

    image_changed = (
        "docker_image" in data.model_fields_set and data.docker_image != a.docker_image
    ) or ("docker_tag" in data.model_fields_set and data.docker_tag != a.docker_tag)

    a = await update_app(session, app_id, data, user_id=current_user.sub)

    if a.launch_mode == "embedded" and image_changed:
        await enqueue_deploy(a.id, a.slug)

    return AppResponse.model_validate(a)


@router.delete("/{app_id}", status_code=204)
async def delete_app_endpoint(
    app_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "delete", "own")),
) -> None:
    a = await get_app(session, app_id)
    check_resource_access(current_user, a, resource_name="app", write=True)
    if a.launch_mode == "embedded":
        # Pass slug because the row will be gone by the time the worker runs.
        await enqueue_stop(a.id, a.slug)
    await delete_app(session, app_id)


@router.post("/{app_id}/deploy", response_model=AppResponse)
async def deploy_app_endpoint(
    app_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "update", "own")),
) -> AppResponse:
    a = await get_app(session, app_id)
    check_resource_access(current_user, a, resource_name="app", write=True)
    if a.launch_mode != "embedded":
        raise ValidationError("Only embedded apps can be deployed")
    await enqueue_deploy(a.id, a.slug)
    a = await get_app(session, app_id)
    return AppResponse.model_validate(a)


@router.post("/{app_id}/stop", response_model=AppResponse)
async def stop_app_endpoint(
    app_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "update", "own")),
) -> AppResponse:
    a = await get_app(session, app_id)
    check_resource_access(current_user, a, resource_name="app", write=True)
    if a.launch_mode != "embedded":
        raise ValidationError("Only embedded apps can be stopped")
    await enqueue_stop(a.id, a.slug)
    a = await get_app(session, app_id)
    return AppResponse.model_validate(a)


@router.post("/{app_id}/launch", response_model=AppLaunchResult)
async def launch_app_endpoint(
    app_id: str,
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "read", "own")),
) -> AppLaunchResult:
    a = await get_app(session, app_id)
    check_resource_access(current_user, a, resource_name="app")

    settings = get_settings()

    # Decide the URL the user will be sent to.
    if a.launch_mode == "external":
        if not a.external_url:
            raise ValidationError("App has no external_url configured")
        launch_url = a.external_url
    else:  # embedded
        if a.runtime_status != "active":
            raise HTTPException(
                status_code=409,
                detail=f"App is not running (runtime_status={a.runtime_status})",
            )
        # Platform-owned launch URL. Frontend will render this in an iframe;
        # the path goes through the gateway's standard /api/v1 prefix so it
        # picks up auth middleware before being proxied to the container.
        launch_url = f"{settings.api_v1_prefix}/apps/runtime/{a.slug}/"

    token: str | None = None
    expires_at = None
    if a.auth_mode == "signed_jwt":
        if not a.launch_token_audience:
            raise PlatformError("App is misconfigured: signed_jwt requires launch_token_audience")
        token, expires_at = mint_launch_token(
            user_id=current_user.sub,
            org_id=current_user.org_id,
            email=current_user.email,
            audience=a.launch_token_audience,
            ttl_seconds=a.launch_token_ttl_seconds or 300,
        )
        # For external launches we append the token to the URL up front.
        # For embedded, the frontend forwards it via postMessage / query string.
        if a.launch_mode == "external":
            launch_url = _append_query(launch_url, launch_token=token)

    # Audit
    org_id = _require_org(current_user)
    await record_launch(
        session,
        app_id=a.id,
        org_id=org_id,
        user_id=current_user.sub,
        launch_mode=a.launch_mode,
        auth_mode=a.auth_mode,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return AppLaunchResult(
        launch_mode=a.launch_mode,
        launch_url=launch_url,
        auth_mode=a.auth_mode,
        token=token,
        expires_at=expires_at,
    )


@router.get("/{app_id}/launches", response_model=PaginatedResponse)
async def list_app_launches_endpoint(
    app_id: str,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("app", "read", "own")),
) -> PaginatedResponse:
    a = await get_app(session, app_id)
    check_resource_access(current_user, a, resource_name="app")
    items, total = await list_launches(session, app_id=app_id, skip=skip, limit=limit)
    return PaginatedResponse(
        items=[AppLaunchResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )
