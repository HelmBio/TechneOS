"""FastAPI dependencies for authentication."""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.auth.providers import validate_any_token
from core.config import get_settings
from core.exceptions import AuthError
from core.models.common import TokenPayload

# Support both Bearer token and API key
security = HTTPBearer(auto_error=False)


async def _validate_token(token: str) -> TokenPayload:
    """Validate a JWT by inspecting its header to pick the right provider.

    HS256 → LocalAuthProvider (email/password and OAuth2-issued tokens)
    RS256 → KeycloakAuthProvider (Keycloak SSO and social-login tokens)
    """
    return await validate_any_token(token)


def _check_internal_token(request: Request) -> TokenPayload | None:
    """If X-Internal-Token matches the configured service secret, return a
    synthetic superuser payload so Airflow workers can call internal endpoints."""
    token = request.headers.get("X-Internal-Token")
    if not token:
        return None
    settings = get_settings()
    if not settings.internal_service_token:
        return None
    if token != settings.internal_service_token:
        return None
    return TokenPayload(
        sub="internal-service",
        email="internal@system",
        role="platform_admin",
        # Service-to-service callers bypass RBAC. ``role=platform_admin``
        # alone isn't enough because require_permission() reads from the
        # ``permissions`` list, not the role string.
        permissions=["*:*:platform"],
        org_id=None,
        team_id=None,
        exp=None,
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> TokenPayload:
    """Extract and validate the current user from the request.

    Supports four authentication methods:
    1. Internal service token in X-Internal-Token header
    2. Bearer token (JWT) in Authorization header
    3. ``techneos_access_token`` cookie (for browser iframe loads where headers
       can't be injected — set on login/refresh)
    4. API key in X-API-Key header (resolved in gateway, forwarded as JWT)

    This dependency is used by all protected endpoints.
    """
    # Try internal service token first (Airflow callbacks)
    internal = _check_internal_token(request)
    if internal is not None:
        return internal

    # Try Bearer token
    if credentials is not None:
        try:
            return await _validate_token(credentials.credentials)
        except AuthError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=e.message,
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    # Try cookie (browser iframe loads / same-origin navigations)
    cookie_token = request.cookies.get("techneos_access_token")
    if cookie_token:
        try:
            return await _validate_token(cookie_token)
        except AuthError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=e.message,
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    # Try X-API-Key header (gateway will have already validated and
    # attached user info — but for direct service access, we check here too)
    api_key = request.headers.get("X-API-Key")
    if api_key is not None:
        # API key validation is handled by the gateway middleware
        # If we reach here in direct service mode, the key needs validation
        # This will be implemented when API key resolution is added
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key validation requires the API gateway",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_active_user(
    current_user: TokenPayload = Depends(get_current_user),
) -> TokenPayload:
    """Ensure the current user is active. Extends get_current_user."""
    # In a full implementation, this would check user.is_active in the DB.
    # For now, if the token is valid, we assume the user is active.
    return current_user


async def get_current_superuser(
    current_user: TokenPayload = Depends(get_current_user),
) -> TokenPayload:
    """Require the current user to be a platform admin."""
    if current_user.role != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser access required",
        )
    return current_user


async def get_current_admin_user(
    current_user: TokenPayload = Depends(get_current_user),
) -> TokenPayload:
    """Require the current user to be a platform admin or org admin."""
    if current_user.role not in ("platform_admin", "org_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required — platform_admin or org_admin role needed",
        )
    return current_user
