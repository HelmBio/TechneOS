"""Authentication routes — login, register, refresh, logout, me, OIDC config.

Sign-in methods and provider routing:
  - Email/password → LocalAuthProvider (always available)
  - Google / GitHub → KeycloakAuthProvider (social login via Keycloak brokering)
  - SSO (enterprise IdP) → OAuth2AuthProvider (e.g. PingFederate)

There is no global AUTH_PROVIDER setting.  Each request specifies or implies
which provider to use.  The ``/oidc/config`` endpoint tells the frontend
which providers are available so it can render the right buttons.
"""

import logging
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.crud.admin import write_audit_log
from core.audit import client_ip as _client_ip
from auth_service.crud.users import (
    change_password,
    create_user,
    get_or_create_from_keycloak,
    get_user_by_email,
    get_user_by_id,
)
from core.auth.dependencies import get_current_user
from core.auth.providers import (
    KeycloakAuthProvider,
    LocalAuthProvider,
    OAuth2AuthProvider,
    get_auth_provider,
    verify_password,
)
from core.config import get_settings
from core.database.postgres import get_async_session
from core.exceptions import (
    AlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
)
from core.models.common import (
    ChangePasswordRequest,
    LoginRequest,
    TokenPair,
    TokenPayload,
    UserCreate,
    UserResponse,
    UserWithRoleResponse,
)
from core.models.user import Org, Role, User

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────


async def _resolve_role_data(session: AsyncSession, user: User) -> tuple[str | None, list[str]]:
    """Return (role_name, permissions) for the user."""
    if user.role_id:
        result = await session.execute(select(Role).where(Role.id == user.role_id))
        role = result.scalar_one_or_none()
        if role:
            return role.name, role.permissions or []
    return None, []


async def _default_org_id(session: AsyncSession) -> str | None:
    """Return the default org ID for JIT-provisioned users.

    The org a first-seen SSO user is attached to, resolved by slug at runtime
    (``settings.default_org_slug`` <- ``DEFAULT_ORG_SLUG``) — the same value seed
    used to create it. The fallback slug lives only in core config, not here.
    """
    slug = get_settings().default_org_slug
    result = await session.execute(select(Org).where(Org.slug == slug))
    org = result.scalar_one_or_none()
    return org.id if org else None


# Cookie name for the HTTP-only session cookie used by browser iframe loads
# and other navigations where an Authorization header can't be set.
SESSION_COOKIE_NAME = "techneos_access_token"


def _set_session_cookie(response: Response, tokens: TokenPair) -> None:
    """Mirror the access token into an HTTP-only cookie.

    The Bearer token in the response body is still the source of truth for
    JS clients — the cookie exists so that browser-initiated requests
    (iframe ``src`` loads, same-origin navigations) can authenticate without
    JS having to inject a header.
    """
    settings = get_settings()
    cookie_kwargs: dict[str, object] = dict(
        key=SESSION_COOKIE_NAME,
        value=tokens.access_token,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
    )
    if settings.session_cookie_domain:
        cookie_kwargs["domain"] = settings.session_cookie_domain
    response.set_cookie(**cookie_kwargs)  # type: ignore[arg-type]


def _clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    if settings.session_cookie_domain:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/", domain=settings.session_cookie_domain)
    else:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")


# ── OIDC configuration (public) ─────────────────────────────────────────


class KeycloakConfig(BaseModel):
    """Keycloak-specific config for social login (Google, GitHub, etc.)."""

    authorization_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = ""
    end_session_endpoint: str = ""
    client_id: str = ""


class OAuth2Config(BaseModel):
    """Generic OAuth2 config for enterprise SSO (e.g. PingFederate)."""

    authorization_endpoint: str = ""
    token_endpoint: str = ""
    client_id: str = ""
    redirect_uri: str = ""
    scopes: str = ""


class OIDCConfig(BaseModel):
    """Discovery response telling the frontend which auth providers are available."""

    local: bool = True  # email/password is always available
    keycloak: KeycloakConfig | None = None  # present when Keycloak is configured
    oauth2: OAuth2Config | None = None  # present when OAuth2 (SSO) is configured


@router.get("/oidc/config", response_model=OIDCConfig)
async def oidc_config() -> OIDCConfig:
    """Expose auth provider discovery info for frontend and CLI.

    Returns which providers are available so the UI knows which login
    buttons to show.  There is no "primary" provider — the user picks.
    """
    settings = get_settings()
    result = OIDCConfig()

    if settings.keycloak_configured:
        base = settings.keycloak_openid_base
        if settings.keycloak_public_url:
            base = base.replace(
                settings.keycloak_url.rstrip("/"),
                settings.keycloak_public_url.rstrip("/"),
            )
        result.keycloak = KeycloakConfig(
            authorization_endpoint=f"{base}/auth",
            token_endpoint=f"{base}/token",
            userinfo_endpoint=f"{base}/userinfo",
            end_session_endpoint=f"{base}/logout",
            client_id=settings.keycloak_web_client_id,
        )

    if settings.oauth2_configured:
        result.oauth2 = OAuth2Config(
            authorization_endpoint=settings.oauth2_authorization_url,
            token_endpoint=settings.oauth2_token_url,
            client_id=settings.oauth2_client_id,
            redirect_uri=settings.oauth2_redirect_url,
            scopes=settings.oauth2_scopes,
        )

    return result


# ── Register ─────────────────────────────────────────────────────────────


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    data: UserCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """Register a new user account.

    Always creates the user in the local database with a password hash
    so email/password login works.  If Keycloak is configured, also
    creates the user in Keycloak so they can use social login flows.
    """
    existing = await get_user_by_email(session, data.email)
    if existing is not None:
        raise AlreadyExistsError("User", data.email)

    # Always create locally with password hash
    user = await create_user(session, data)

    # Audit log
    await write_audit_log(
        session,
        user_id=user.id,
        action="user_register",
        resource_type="user",
        resource_id=user.id,
        details={"email": data.email, "full_name": data.full_name},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    # Optionally sync to Keycloak (best-effort — don't fail registration
    # if Keycloak is unreachable)
    if get_settings().keycloak_configured:
        try:
            from core.auth.keycloak_admin import get_keycloak_admin

            kc = get_keycloak_admin()
            org_id = data.org_id or await _default_org_id(session)

            names = data.full_name.split(" ", 1)
            first_name = names[0]
            last_name = names[1] if len(names) > 1 else ""
            kc_user_id = await kc.create_user(
                email=data.email,
                password=data.password,
                first_name=first_name,
                last_name=last_name,
                attributes={"org_id": [org_id or ""], "team_id": [data.team_id or ""]},
                realm_roles=[data.role_name or "scientist"],
            )
            # Store the Keycloak external ID on the local user
            user.external_id = kc_user_id
            await session.commit()
        except Exception:
            logger.warning("Failed to sync user to Keycloak (registration still succeeded locally)")

    return user


# ── Login ────────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenPair)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_async_session),
) -> TokenPair:
    """Authenticate with email + password and receive tokens.

    This endpoint always authenticates against the local database.
    SSO and social logins go through /token-exchange instead.
    """
    user = await get_user_by_email(session, data.email)
    if user is None or user.hashed_password is None:
        await write_audit_log(
            session,
            user_id=None,
            action="user_login_failed",
            resource_type="auth",
            details={"email": data.email, "reason": "unknown_email"},
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        raise InvalidCredentialsError()

    if not verify_password(data.password, user.hashed_password):
        await write_audit_log(
            session,
            user_id=user.id,
            action="user_login_failed",
            resource_type="auth",
            resource_id=user.id,
            details={"email": data.email, "reason": "invalid_password"},
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        raise InvalidCredentialsError()

    if not user.is_active:
        await write_audit_log(
            session,
            user_id=user.id,
            action="user_login_failed",
            resource_type="auth",
            resource_id=user.id,
            details={"email": data.email, "reason": "inactive_account"},
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        raise InvalidCredentialsError()

    role_name, permissions = await _resolve_role_data(session, user)

    local_provider = LocalAuthProvider()
    tokens = await local_provider.create_tokens(
        user_id=user.id,
        claims={
            "email": user.email,
            "role": role_name or "viewer",
            "org_id": user.org_id,
            "team_id": user.team_id,
            "permissions": permissions,
        },
    )

    await write_audit_log(
        session,
        user_id=user.id,
        action="user_login",
        resource_type="auth",
        resource_id=user.id,
        details={"email": user.email},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    _set_session_cookie(response, tokens)
    return tokens


# ── Token exchange (Authorization Code → tokens) ────────────────────────


class TokenExchangeRequest(BaseModel):
    code: str
    redirect_uri: str
    code_verifier: str | None = None
    provider: str  # "keycloak" or "oauth2" — required, no default


@router.post("/token-exchange", response_model=TokenPair)
async def token_exchange(
    data: TokenExchangeRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_async_session),
) -> TokenPair:
    """Exchange an authorization code for tokens (OIDC / OAuth2 flow).

    The ``provider`` field is required — it tells us which IdP issued
    the authorization code so we can exchange it correctly.
    """
    if data.provider == "oauth2":
        tokens = await _token_exchange_oauth2(data, request, session)
    elif data.provider == "keycloak":
        tokens = await _token_exchange_keycloak(data, request, session)
    else:
        from core.exceptions import ValidationError

        raise ValidationError(f"Unknown provider: {data.provider}. Use 'keycloak' or 'oauth2'.")

    _set_session_cookie(response, tokens)
    return tokens


async def _token_exchange_keycloak(
    data: TokenExchangeRequest,
    request: Request,
    session: AsyncSession,
) -> TokenPair:
    """Handle token exchange for Keycloak (PKCE flow).

    Always re-issues locally-signed JWTs so the rest of the platform
    can validate them without needing Keycloak JWKS.
    """
    settings = get_settings()
    if not settings.keycloak_configured:
        from core.exceptions import ValidationError

        raise ValidationError("Keycloak is not configured")

    import httpx

    form_data: dict[str, str] = {
        "grant_type": "authorization_code",
        "client_id": settings.keycloak_web_client_id,
        "code": data.code,
        "redirect_uri": data.redirect_uri,
    }
    if data.code_verifier:
        form_data["code_verifier"] = data.code_verifier

    base = settings.keycloak_openid_base
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base}/token",
            data=form_data,
            timeout=10.0,
        )
        if resp.status_code != 200:
            raise InvalidCredentialsError()
        body = resp.json()

    kc_access_token = body["access_token"]

    # Validate the Keycloak token to extract user claims
    kc_provider = get_auth_provider("keycloak")
    assert isinstance(kc_provider, KeycloakAuthProvider)
    token_payload = await kc_provider.validate_token(kc_access_token)
    org_id = token_payload.org_id or await _default_org_id(session)

    full_name = token_payload.email.split("@")[0]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base}/userinfo",
                headers={"Authorization": f"Bearer {kc_access_token}"},
                timeout=5.0,
            )
            if resp.status_code == 200:
                info = resp.json()
                full_name = (
                    info.get("name")
                    or (f"{info.get('given_name', '')} {info.get('family_name', '')}".strip())
                    or full_name
                )
    except Exception:
        pass

    await get_or_create_from_keycloak(
        session,
        sub=token_payload.sub,
        email=token_payload.email,
        full_name=full_name,
        role_name=token_payload.role,
        org_id=cast(str, org_id),
        team_id=token_payload.team_id,
    )

    # Re-issue as locally-signed JWTs so the gateway validates them
    # uniformly via HS256.
    user = await get_user_by_email(session, token_payload.email)
    if user is None:
        raise InvalidCredentialsError()
    role_name, permissions = await _resolve_role_data(session, user)
    local_provider = LocalAuthProvider()
    tokens = await local_provider.create_tokens(
        user_id=user.id,
        claims={
            "email": user.email,
            "role": role_name or "scientist",
            "org_id": user.org_id,
            "team_id": user.team_id,
            "permissions": permissions,
        },
    )

    await write_audit_log(
        session,
        user_id=user.id,
        action="user_login",
        resource_type="auth",
        resource_id=user.id,
        details={"email": user.email, "provider": "keycloak"},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return tokens


async def _token_exchange_oauth2(
    data: TokenExchangeRequest,
    request: Request,
    session: AsyncSession,
) -> TokenPair:
    """Handle token exchange for the generic OAuth2 provider.

    Flow:
    1. Exchange the authorization code for an IdP access token
    2. Introspect the IdP token to extract user claims
    3. JIT-provision the user in the local database
    4. Issue locally-signed JWT tokens for the platform
    """
    provider = get_auth_provider("oauth2")
    if not isinstance(provider, OAuth2AuthProvider):
        raise InvalidCredentialsError()

    # Step 1: Exchange code for IdP tokens
    idp_tokens = await provider.exchange_code(data.code, data.redirect_uri)
    idp_access_token = idp_tokens.get("access_token")
    if not idp_access_token:
        raise InvalidCredentialsError()

    # Step 2: Introspect to get user claims
    claims = await provider.introspect(idp_access_token)

    # Extract user info from introspection response.
    # PingFederate typically returns: sub, username, client_id, scope, email, etc.
    email = (
        claims.get("email")
        or claims.get("Email")
        or claims.get("username")
        or claims.get("sub", "")
    )
    sub = claims.get("sub") or claims.get("uid") or email
    full_name = (
        claims.get("name")
        or (f"{claims.get('given_name', '')} {claims.get('family_name', '')}".strip())
        or email.split("@")[0]
    )

    if not email:
        raise InvalidTokenError("OAuth2 introspection did not return an email or username")

    # Step 3: JIT-provision user
    org_id = await _default_org_id(session)
    await get_or_create_from_keycloak(
        session,
        sub=sub,
        email=email,
        full_name=full_name,
        role_name="scientist",  # default role for SSO users
        org_id=cast(str, org_id),
        team_id=None,
    )

    # Step 4: Look up the provisioned user to get their local ID
    user = await get_user_by_email(session, email)
    if user is None:
        raise InvalidCredentialsError()

    role_name, permissions = await _resolve_role_data(session, user)

    # Step 5: Issue locally-signed platform tokens
    tokens = await provider.create_tokens(
        user_id=user.id,
        claims={
            "email": user.email,
            "role": role_name or "scientist",
            "org_id": user.org_id,
            "team_id": user.team_id,
            "permissions": permissions,
        },
    )

    await write_audit_log(
        session,
        user_id=user.id,
        action="user_login",
        resource_type="auth",
        resource_id=user.id,
        details={"email": user.email, "provider": "oauth2"},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return tokens


# ── Refresh ──────────────────────────────────────────────────────────────


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    refresh_token: str,
    response: Response,
    session: AsyncSession = Depends(get_async_session),
) -> TokenPair:
    """Exchange a refresh token for a new token pair.

    All tokens issued by this platform are locally-signed HS256 JWTs
    (even SSO and social-login flows re-issue as local tokens), so
    we always use LocalAuthProvider for refresh.

    The refresh token only carries the user ID (``sub``).  We look up
    the user in the database so the new access token contains the
    latest role, org, and team claims.
    """
    provider = get_auth_provider("local")
    payload = await provider.validate_token(refresh_token)
    if payload.type != "refresh":
        raise InvalidTokenError("Not a refresh token")

    user = await get_user_by_id(session, payload.sub)
    if not user:
        raise InvalidTokenError("User not found")

    role_name, permissions = await _resolve_role_data(session, user)

    tokens = await provider.create_tokens(
        user_id=user.id,
        claims={
            "email": user.email,
            "role": role_name or "viewer",
            "org_id": user.org_id,
            "team_id": user.team_id,
            "permissions": permissions,
        },
    )
    _set_session_cookie(response, tokens)
    return tokens


# ── Logout ───────────────────────────────────────────────────────────────


class LogoutRequest(BaseModel):
    refresh_token: str
    provider: str | None = None  # "keycloak" to also revoke Keycloak session


@router.post("/logout", status_code=204)
async def logout(
    data: LogoutRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    """Log out — optionally revoke the external IdP session.

    The ``provider`` field lets the client specify which IdP session
    to revoke (e.g. "keycloak" for social-login sessions).
    """
    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="user_logout",
        resource_type="auth",
        resource_id=current_user.sub,
        details={"email": current_user.email, "provider": data.provider},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    if data.provider == "keycloak":
        settings = get_settings()
        if settings.keycloak_configured:
            kc_provider = get_auth_provider("keycloak")
            if isinstance(kc_provider, KeycloakAuthProvider):
                await kc_provider.logout(data.refresh_token)

    _clear_session_cookie(response)


# ── Me ───────────────────────────────────────────────────────────────────


@router.get("/me", response_model=UserWithRoleResponse)
async def get_me(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Get the current user's profile.

    JIT-provisions the user if they were authenticated via an external
    provider but don't yet exist in the local database.
    """
    if not current_user.email or "@" not in current_user.email:
        raise HTTPException(
            status_code=422,
            detail="Token does not contain a valid email address. "
            "Re-authenticate or contact your identity provider administrator.",
        )

    user = await get_user_by_email(session, current_user.email)

    if user is None:
        # JIT-provision: user authenticated via external IdP but not yet
        # in local DB.
        org_id = current_user.org_id or await _default_org_id(session)
        user = await get_or_create_from_keycloak(
            session,
            sub=current_user.sub,
            email=current_user.email,
            full_name=current_user.email.split("@")[0],
            role_name=current_user.role,
            org_id=cast(str, org_id),
            team_id=current_user.team_id,
        )

    if user is None:
        raise NotFoundError("User", current_user.email)

    role_name, _permissions = await _resolve_role_data(session, user)

    # Manually construct the response dictionary to match UserWithRoleResponse
    response_data = user.to_dict()
    response_data["role"] = role_name
    return response_data


# ── Change Password ──────────────────────────────────────────────────────


@router.post("/change-password", status_code=204)
async def change_password_route(
    data: ChangePasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    """Change the current user's password (local auth only).

    Requires the current password for verification.  SSO-only accounts
    will receive a 400 error — they must change their password through
    their identity provider.
    """
    await change_password(
        session,
        user_id=current_user.sub,
        current_password=data.current_password,
        new_password=data.new_password,
    )

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="change_password",
        resource_type="auth",
        resource_id=current_user.sub,
        details={"email": current_user.email},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
