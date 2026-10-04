"""Authentication middleware for the API Gateway.

Validates JWT tokens and API keys on incoming requests,
attaching user information to the request state.
"""

import json
import logging
import time
from datetime import UTC, datetime

from fastapi import Request, Response
from sqlalchemy import or_, select, update
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from core.auth.providers import validate_any_token, verify_password
from core.config import get_settings
from core.exceptions import AccountInactiveError, AuthError
from core.models.common import TokenPayload

logger = logging.getLogger(__name__)

# How long an account's active flag is cached per token subject, so the gateway
# doesn't hit the database on every request. Activating or deactivating a user
# takes effect within this window.
ACCOUNT_STATUS_TTL_SECONDS = 30.0
_ACCOUNT_STATUS_CACHE_MAX = 10_000
_account_status_cache: dict[str, tuple[float, bool]] = {}

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}

# Path prefixes that don't require authentication. The PyPI Simple API proxy
# (/simple/*) must be reachable unauthenticated so uv/pip can resolve packages
# directly from the gateway URL — the gateway forwards these to app-service,
# which injects the index credentials (see routes/simple_proxy.py). Matched by
# prefix because the index has per-package and per-file subpaths.
PUBLIC_PREFIXES = (
    "/simple/",
)

# Auth paths that handle their own authentication
AUTH_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/token-exchange",
    "/api/v1/auth/oidc/config",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates authentication on incoming requests.

    Supports:
    1. Bearer JWT tokens (Authorization header)
    2. API keys (X-API-Key header)
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip auth for public and auth-specific paths
        if (
            request.url.path in PUBLIC_PATHS
            or request.url.path in AUTH_PATHS
            or request.url.path.startswith(PUBLIC_PREFIXES)
        ):
            return await call_next(request)

        # Skip auth for OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Try Bearer token
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                user_claims = await self._validate_bearer(token)
            except AuthError:
                return Response(
                    content='{"detail": "Invalid or expired token"}',
                    status_code=401,
                    media_type="application/json",
                )
            denied = await self._inactive_account_response(user_claims)
            if denied is not None:
                return denied
            request.state.user = user_claims
            return await call_next(request)

        # Try session cookie (browser iframe loads / same-origin navigations
        # where an Authorization header can't be injected — set on /login).
        cookie_token = request.cookies.get("techneos_access_token")
        if cookie_token:
            try:
                user_claims = await self._validate_bearer(cookie_token)
            except AuthError:
                return Response(
                    content='{"detail": "Invalid or expired session"}',
                    status_code=401,
                    media_type="application/json",
                )
            denied = await self._inactive_account_response(user_claims)
            if denied is not None:
                return denied
            request.state.user = user_claims
            return await call_next(request)

        # Try API key
        api_key = request.headers.get("X-API-Key")
        if api_key:
            user_claims = await self._validate_api_key(api_key)
            if user_claims is not None:
                request.state.user = user_claims
                return await call_next(request)
            return Response(
                content='{"detail": "Invalid API key"}',
                status_code=401,
                media_type="application/json",
            )

        # Try internal service token (Airflow→platform callbacks)
        internal_token = request.headers.get("X-Internal-Token")
        if internal_token:
            from core.config import get_settings

            settings = get_settings()
            if (
                settings.internal_service_token
                and internal_token == settings.internal_service_token
            ):
                request.state.user = TokenPayload(
                    sub="internal-service",
                    email="internal@system",
                    role="platform_admin",
                    org_id=None,
                    team_id=None,
                    exp=None,
                )
                return await call_next(request)
            return Response(
                content='{"detail": "Invalid internal token"}',
                status_code=401,
                media_type="application/json",
            )

        # No authentication provided
        return Response(
            content='{"detail": "Not authenticated"}',
            status_code=401,
            media_type="application/json",
        )

    async def _inactive_account_response(self, claims: TokenPayload) -> Response | None:
        """Return a 403 response if the token's account is inactive, else None.

        A valid token alone isn't enough: an admin may have deactivated the
        account since it was issued, or (with ``SSO_NEW_USERS_ACTIVE=false``) a
        new SSO account may still be awaiting approval. Keycloak-issued tokens
        are also accepted here directly, so this is the one place every bearer
        request passes through.
        """
        try:
            active = await self._is_account_active(claims)
        except Exception:
            logger.exception("Account status lookup failed for %s", claims.sub)
            return Response(
                content='{"detail": "Account status unavailable"}',
                status_code=503,
                media_type="application/json",
            )
        if active:
            return None
        return Response(
            content=json.dumps({"detail": AccountInactiveError().message}),
            status_code=403,
            media_type="application/json",
        )

    async def _is_account_active(self, claims: TokenPayload) -> bool:
        """Cached check of the account's ``is_active`` flag (see the TTL above)."""
        now = time.monotonic()
        cached = _account_status_cache.get(claims.sub)
        if cached is not None and now - cached[0] < ACCOUNT_STATUS_TTL_SECONDS:
            return cached[1]
        active = await self._lookup_account_active(claims)
        if len(_account_status_cache) >= _ACCOUNT_STATUS_CACHE_MAX:
            _account_status_cache.clear()
        _account_status_cache[claims.sub] = (now, active)
        return active

    async def _lookup_account_active(self, claims: TokenPayload) -> bool:
        """Read the account's active flag from the database.

        Matches the token subject the same ways auth-service JIT provisioning
        does (local id, Keycloak/OAuth2 ``sub``, email). A token for an account
        that doesn't exist yet only gets through when new SSO users start
        active; otherwise it must first go through ``/auth/token-exchange``,
        which provisions the account (inactive) for an admin to approve.
        """
        from core.database.postgres import get_session_factory
        from core.models.user import User

        conditions = [User.id == claims.sub, User.external_id == claims.sub]
        if claims.email:
            conditions.append(User.email == claims.email)
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(select(User.is_active).where(or_(*conditions)))
            flags = list(result.scalars())
        if not flags:
            return get_settings().sso_new_users_active
        return all(flags)

    async def _validate_bearer(self, token: str):  # type: ignore[no-untyped-def]
        """Validate a JWT by inspecting its header to pick the right provider.

        HS256 → LocalAuthProvider (email/password and OAuth2-issued tokens)
        RS256 → KeycloakAuthProvider (Keycloak SSO and social-login tokens)
        """
        return await validate_any_token(token)

    async def _validate_api_key(self, key: str):  # type: ignore[no-untyped-def]
        """Validate an API key and return user claims if valid.

        API key format: techneos_{prefix}_{secret}
        """
        if not key.startswith("techneos_"):
            return None

        parts = key.split("_", 2)
        if len(parts) != 3:
            return None

        prefix = parts[1]

        try:
            from core.database.postgres import get_session_factory
            from core.models.user import ApiKey, Role, User

            factory = get_session_factory()
            async with factory() as session:
                # Find key by prefix
                result = await session.execute(
                    select(ApiKey).where(
                        ApiKey.prefix == prefix,
                        ApiKey.is_active == True,  # noqa: E712
                    )
                )
                api_key_record = result.scalar_one_or_none()

                if api_key_record is None:
                    return None

                # Check expiration
                if api_key_record.expires_at and api_key_record.expires_at < datetime.now(UTC):
                    return None

                # Verify key hash
                if not verify_password(key, api_key_record.key_hash):
                    return None

                # Update last_used_at
                await session.execute(
                    update(ApiKey)
                    .where(ApiKey.id == api_key_record.id)
                    .values(last_used_at=datetime.now(UTC))
                )

                # Get user and role
                user_result = await session.execute(
                    select(User).where(User.id == api_key_record.user_id)
                )
                user = user_result.scalar_one_or_none()
                if user is None or not user.is_active:
                    return None

                role_name = None
                if user.role_id:
                    role_result = await session.execute(select(Role).where(Role.id == user.role_id))
                    role = role_result.scalar_one_or_none()
                    if role:
                        role_name = role.name

                await session.commit()

                return TokenPayload(
                    sub=user.id,
                    email=user.email,
                    role=role_name,
                    org_id=user.org_id,
                    team_id=user.team_id,
                )

        except Exception:
            logger.exception("API key validation failed")
            return None
