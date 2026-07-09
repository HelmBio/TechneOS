"""Auth provider abstraction — local JWT, Keycloak, or generic OAuth2.

Providers are instantiated on-demand via ``get_auth_provider(name)`` and
cached in a registry so each is a singleton.  The ``name`` parameter
selects which provider to return:
  - "local"    → LocalAuthProvider  (always available)
  - "keycloak" → KeycloakAuthProvider (requires KEYCLOAK_* env vars)
  - "oauth2"   → OAuth2AuthProvider (requires OAUTH2_* env vars)

Token validation helpers (``validate_any_token``) inspect the JWT header
to route to the correct validator without needing to know which provider
issued the token up-front.
"""

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast, runtime_checkable

import bcrypt
import httpx
from jose import JWTError, jwt

from core.config import get_settings
from core.exceptions import InvalidTokenError, TokenExpiredError
from core.models.common import TokenPair, TokenPayload

logger = logging.getLogger(__name__)

# Platform roles, ordered by priority (highest first).
# When a Keycloak user has multiple realm roles that match platform roles,
# we pick the one with the highest priority.
PLATFORM_ROLES = ["platform_admin", "org_admin", "project_lead", "scientist", "viewer"]


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


@runtime_checkable
class AuthProvider(Protocol):
    """Abstract auth provider interface.

    LocalAuthProvider — self-signed JWTs
    KeycloakAuthProvider — validate against Keycloak JWKS
    """

    async def create_tokens(self, user_id: str, claims: dict[str, Any]) -> TokenPair: ...

    async def validate_token(self, token: str) -> TokenPayload: ...

    async def refresh_tokens(self, refresh_token: str) -> TokenPair: ...


class LocalAuthProvider:
    """JWT auth provider using local secret key.

    Tokens are signed with HS256 and a shared secret. This is suitable for
    development and single-instance deployments.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._secret = settings.jwt_secret_key
        self._algorithm = settings.jwt_algorithm
        self._access_expire = timedelta(minutes=settings.jwt_access_token_expire_minutes)
        self._refresh_expire = timedelta(days=settings.jwt_refresh_token_expire_days)

    async def create_tokens(self, user_id: str, claims: dict[str, Any]) -> TokenPair:
        """Create an access + refresh token pair."""
        now = datetime.now(UTC)

        access_payload = {
            "sub": user_id,
            "type": "access",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + self._access_expire,
            **claims,
        }
        access_token = jwt.encode(access_payload, self._secret, algorithm=self._algorithm)

        refresh_payload = {
            "sub": user_id,
            "type": "refresh",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + self._refresh_expire,
        }
        refresh_token = jwt.encode(refresh_payload, self._secret, algorithm=self._algorithm)

        return TokenPair(access_token=access_token, refresh_token=refresh_token)

    async def validate_token(self, token: str) -> TokenPayload:
        """Validate and decode a JWT token."""
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except JWTError as e:
            if "expired" in str(e).lower():
                raise TokenExpiredError() from e
            raise InvalidTokenError(str(e)) from e

        return TokenPayload(
            sub=payload["sub"],
            email=payload.get("email", ""),
            role=payload.get("role"),
            org_id=payload.get("org_id"),
            team_id=payload.get("team_id"),
            permissions=payload.get("permissions", []),
            exp=datetime.fromtimestamp(payload["exp"], tz=UTC) if "exp" in payload else None,
            type=payload.get("type", "access"),
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Validate a refresh token and issue new token pair."""
        payload = await self.validate_token(refresh_token)
        if payload.type != "refresh":
            raise InvalidTokenError("Not a refresh token")

        return await self.create_tokens(
            user_id=payload.sub,
            claims={
                "email": payload.email,
                "role": payload.role,
                "org_id": payload.org_id,
                "team_id": payload.team_id,
                "permissions": payload.permissions,
            },
        )


def _pick_platform_role(realm_roles: list[str]) -> str | None:
    """Pick the highest-priority platform role from a list of Keycloak realm roles."""
    role_set = set(realm_roles)
    for role in PLATFORM_ROLES:
        if role in role_set:
            return role
    return None


class KeycloakAuthProvider:
    """Auth provider that delegates to a Keycloak instance.

    Tokens are issued by Keycloak's token endpoint and validated against
    its JWKS (JSON Web Key Set).  The public keys are cached with a TTL.
    """

    JWKS_TTL_SECONDS = 3600  # Re-fetch JWKS keys every hour

    def __init__(self) -> None:
        settings = get_settings()
        self._keycloak_url = settings.keycloak_url.rstrip("/")
        self._realm = settings.keycloak_realm
        self._client_id = settings.keycloak_client_id
        self._client_secret = settings.keycloak_client_secret

        base = f"{self._keycloak_url}/realms/{self._realm}/protocol/openid-connect"
        self._token_url = f"{base}/token"
        self._jwks_url = f"{base}/certs"
        self._revoke_url = f"{base}/revoke"
        self._logout_url = f"{base}/logout"

        # Cached JWKS public keys with TTL
        self._jwks_keys: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_jwks(self) -> dict[str, Any]:
        """Fetch the JWKS key set from Keycloak."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(self._jwks_url, timeout=10.0)
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json())

    async def _get_jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Return cached JWKS keys, refreshing if TTL expired or forced."""
        now = time.monotonic()
        ttl_expired = (now - self._jwks_fetched_at) > self.JWKS_TTL_SECONDS
        if self._jwks_keys is None or ttl_expired or force_refresh:
            self._jwks_keys = await self._fetch_jwks()
            self._jwks_fetched_at = now
        return self._jwks_keys

    # ------------------------------------------------------------------
    # AuthProvider interface
    # ------------------------------------------------------------------

    async def create_tokens(self, user_id: str, claims: dict[str, Any]) -> TokenPair:
        """Request tokens from Keycloak.

        ``claims`` must include ``"password"`` for the ROPC flow.
        If no password is present, the client-credentials grant is used.
        """
        data: dict[str, str] = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": "openid profile email",
        }

        password = claims.pop("password", None)
        if password is not None:
            data.update(
                {
                    "grant_type": "password",
                    "username": claims.get("email", user_id),
                    "password": password,
                }
            )
        else:
            data["grant_type"] = "client_credentials"

        async with httpx.AsyncClient() as client:
            resp = await client.post(self._token_url, data=data, timeout=10.0)
            if resp.status_code != 200:
                raise InvalidTokenError(
                    f"Keycloak token request failed ({resp.status_code}): {resp.text}"
                )
            body = resp.json()

        return TokenPair(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", ""),
        )

    async def validate_token(self, token: str) -> TokenPayload:
        """Validate a JWT against Keycloak's JWKS public keys.

        Extracts the platform role from realm_access.roles and resolves
        org_id/team_id from token claims (set via Keycloak protocol mappers)
        or falls back to a DB lookup.
        """
        jwks = await self._get_jwks()

        try:
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                audience=self._client_id,
                options={"verify_aud": True},
            )
        except JWTError as first_err:
            if "expired" in str(first_err).lower():
                raise TokenExpiredError() from first_err
            # Key may have been rotated — refresh once and retry
            try:
                jwks = await self._get_jwks(force_refresh=True)
                payload = jwt.decode(
                    token,
                    jwks,
                    algorithms=["RS256"],
                    audience=self._client_id,
                    options={"verify_aud": True},
                )
            except JWTError as second_err:
                if "expired" in str(second_err).lower():
                    raise TokenExpiredError() from second_err
                raise InvalidTokenError(str(second_err)) from second_err

        # Extract platform role from realm_access.roles
        realm_roles = payload.get("realm_access", {}).get("roles", [])
        role = _pick_platform_role(realm_roles)

        # org_id and team_id come from custom protocol mappers on the token.
        # If absent, they'll be None and the auth service fills them via DB lookup.
        org_id = payload.get("org_id") or None
        team_id = payload.get("team_id") or None

        return TokenPayload(
            sub=payload.get("sub", ""),
            email=payload.get("email", ""),
            role=role,
            org_id=org_id,
            team_id=team_id,
            permissions=[],
            exp=datetime.fromtimestamp(payload["exp"], tz=UTC) if "exp" in payload else None,
            type="access",
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Exchange a refresh token for a new token pair via Keycloak."""
        data = {
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": refresh_token,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(self._token_url, data=data, timeout=10.0)
            if resp.status_code != 200:
                raise InvalidTokenError(
                    f"Keycloak refresh failed ({resp.status_code}): {resp.text}"
                )
            body = resp.json()

        return TokenPair(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", ""),
        )

    async def logout(self, refresh_token: str) -> None:
        """End the Keycloak session by revoking the refresh token."""
        async with httpx.AsyncClient() as client:
            await client.post(
                self._logout_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": refresh_token,
                },
                timeout=10.0,
            )


class OAuth2AuthProvider:
    """Auth provider for generic OAuth2/OIDC servers (e.g. PingFederate).

    Unlike Keycloak, which issues JWTs we can validate locally via JWKS, a
    generic OAuth2 server may issue opaque tokens.  This provider:
    - exchanges authorization codes for tokens via the token endpoint
    - introspects tokens via the introspection endpoint to extract user info
    - issues locally-signed JWTs (like LocalAuthProvider) so that the
      rest of the platform can validate them without calling the IdP
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client_id = settings.oauth2_client_id
        self._client_secret = settings.oauth2_client_secret
        self._token_url = settings.oauth2_token_url
        self._redirect_url = settings.oauth2_redirect_url
        self._scopes = settings.oauth2_scopes
        self._introspect_url = settings.oauth2_introspect_url
        self._introspect_client_id = settings.oauth2_introspect_client_id or self._client_id
        self._introspect_client_secret = (
            settings.oauth2_introspect_client_secret or self._client_secret
        )

        # Delegate local JWT creation/validation to LocalAuthProvider
        self._local = LocalAuthProvider()

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict[str, Any]:
        """Exchange an authorization code for tokens from the OAuth2 server.

        Returns the raw token response dict from the IdP (contains
        access_token, possibly refresh_token, etc.).
        """
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "redirect_uri": redirect_uri or self._redirect_url,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(self._token_url, data=data, timeout=15.0)
            if resp.status_code != 200:
                raise InvalidTokenError(
                    f"OAuth2 token exchange failed ({resp.status_code}): {resp.text}"
                )
            return cast(dict[str, Any], resp.json())

    async def introspect(self, access_token: str) -> dict[str, Any]:
        """Introspect an access token to get user claims.

        Returns the introspection response dict.  The ``active`` field
        indicates whether the token is valid.
        """
        if not self._introspect_url:
            raise InvalidTokenError("OAuth2 introspection URL not configured")

        data: dict[str, str] = {
            "token": access_token,
            "client_id": self._introspect_client_id,
            "client_secret": self._introspect_client_secret,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(self._introspect_url, data=data, timeout=10.0)
            if resp.status_code != 200:
                raise InvalidTokenError(
                    f"OAuth2 introspection failed ({resp.status_code}): {resp.text}"
                )
            result = resp.json()

        if not result.get("active", False):
            raise InvalidTokenError("OAuth2 token is not active")

        return cast(dict[str, Any], result)

    # ------------------------------------------------------------------
    # AuthProvider interface — delegates to LocalAuthProvider
    # ------------------------------------------------------------------

    async def create_tokens(self, user_id: str, claims: dict[str, Any]) -> TokenPair:
        """Create locally-signed JWT tokens for a user.

        Called after we have verified the user through the OAuth2 IdP
        and provisioned them locally.
        """
        return await self._local.create_tokens(user_id, claims)

    async def validate_token(self, token: str) -> TokenPayload:
        """Validate a locally-signed JWT token.

        Tokens returned to the client are always locally-signed, so
        validation uses the local secret key.
        """
        return await self._local.validate_token(token)

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Refresh locally-signed JWT tokens."""
        return await self._local.refresh_tokens(refresh_token)


_registry: dict[str, AuthProvider] = {}


def get_auth_provider(name: str = "local") -> AuthProvider:
    """Return a cached auth provider by name.

    Supported names: "local", "keycloak", "oauth2".
    Raises ``ValueError`` if the requested provider's config is incomplete.
    """
    if name in _registry:
        return _registry[name]

    settings = get_settings()
    if name == "local":
        _registry[name] = LocalAuthProvider()
    elif name == "keycloak":
        if not settings.keycloak_configured:
            raise ValueError(
                "Keycloak provider requested but KEYCLOAK_* env vars are not configured"
            )
        _registry[name] = KeycloakAuthProvider()
    elif name == "oauth2":
        if not settings.oauth2_configured:
            raise ValueError("OAuth2 provider requested but OAUTH2_* env vars are not configured")
        _registry[name] = OAuth2AuthProvider()
    else:
        raise ValueError(f"Unknown auth provider: {name}")

    return _registry[name]


async def validate_any_token(token: str) -> TokenPayload:
    """Validate a JWT by inspecting its header to pick the right provider.

    - HS256 tokens → LocalAuthProvider  (local + OAuth2-issued tokens)
    - RS256 tokens → KeycloakAuthProvider (if configured), else local fallback
    """
    from jose import jwt as jose_jwt

    try:
        header = jose_jwt.get_unverified_header(token)
    except Exception:
        # Can't parse header — try local as last resort
        return await get_auth_provider("local").validate_token(token)

    alg = header.get("alg", "HS256")

    if alg == "RS256":
        settings = get_settings()
        if settings.keycloak_configured:
            return await get_auth_provider("keycloak").validate_token(token)
        # RS256 but no Keycloak — try local anyway (will likely fail with
        # a clear error message)
        return await get_auth_provider("local").validate_token(token)

    # HS256 or other symmetric algorithms → local provider
    return await get_auth_provider("local").validate_token(token)
