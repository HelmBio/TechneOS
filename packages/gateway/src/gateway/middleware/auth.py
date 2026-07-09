"""Authentication middleware for the API Gateway.

Validates JWT tokens and API keys on incoming requests,
attaching user information to the request state.
"""

import logging
from datetime import UTC, datetime

from fastapi import Request, Response
from sqlalchemy import select, update
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from core.auth.providers import validate_any_token, verify_password
from core.exceptions import AuthError

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}

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
        if request.url.path in PUBLIC_PATHS or request.url.path in AUTH_PATHS:
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
                request.state.user = user_claims
                return await call_next(request)
            except AuthError:
                return Response(
                    content='{"detail": "Invalid or expired token"}',
                    status_code=401,
                    media_type="application/json",
                )

        # Try session cookie (browser iframe loads / same-origin navigations
        # where an Authorization header can't be injected — set on /login).
        cookie_token = request.cookies.get("techneos_access_token")
        if cookie_token:
            try:
                user_claims = await self._validate_bearer(cookie_token)
                request.state.user = user_claims
                return await call_next(request)
            except AuthError:
                return Response(
                    content='{"detail": "Invalid or expired session"}',
                    status_code=401,
                    media_type="application/json",
                )

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
            from core.models.common import TokenPayload

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

                from core.models.common import TokenPayload

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
