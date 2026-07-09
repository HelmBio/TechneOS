"""Keycloak Admin API client for user and role management.

Used by the auth service when Keycloak is configured to sync users, assign
roles, and manage Keycloak resources programmatically.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


class KeycloakAdminClient:
    """Async client for Keycloak's Admin REST API.

    Authenticates using the master realm admin credentials and caches the
    admin access token until it expires.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._base = settings.keycloak_url.rstrip("/")
        self._realm = settings.keycloak_realm
        self._admin_user = settings.keycloak_admin_user
        self._admin_password = settings.keycloak_admin_password
        self._admin_token: str | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_admin_token(self) -> str:
        """Obtain an admin access token from the master realm."""
        if self._admin_token:
            return self._admin_token

        url = f"{self._base}/realms/master/protocol/openid-connect/token"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": self._admin_user,
                    "password": self._admin_password,
                },
            )
            resp.raise_for_status()
            self._admin_token = resp.json()["access_token"]
            return self._admin_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | list[Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make an authenticated request to the Keycloak Admin API."""
        token = await self._get_admin_token()
        url = f"{self._base}/admin/realms/{self._realm}{path}"
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                params=params,
                timeout=15.0,
            )
            # Retry once on 401 (token expired)
            if resp.status_code == 401:
                self._admin_token = None
                token = await self._get_admin_token()
                resp = await client.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json=json,
                    params=params,
                    timeout=15.0,
                )
            return resp

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """Look up a Keycloak user by email address."""
        resp = await self._request("GET", "/users", params={"email": email, "exact": "true"})
        resp.raise_for_status()
        users = resp.json()
        return users[0] if users else None

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Look up a Keycloak user by ID."""
        resp = await self._request("GET", f"/users/{user_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return cast(dict[str, Any] | None, resp.json())

    async def create_user(
        self,
        email: str,
        password: str,
        first_name: str = "",
        last_name: str = "",
        *,
        enabled: bool = True,
        attributes: dict[str, list[str]] | None = None,
        realm_roles: list[str] | None = None,
    ) -> str:
        """Create a user in Keycloak. Returns the Keycloak user ID."""
        user_repr: dict[str, Any] = {
            "username": email,
            "email": email,
            "emailVerified": True,
            "enabled": enabled,
            "firstName": first_name,
            "lastName": last_name,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        if attributes:
            user_repr["attributes"] = attributes

        resp = await self._request("POST", "/users", json=user_repr)
        if resp.status_code == 409:
            # User already exists — retrieve their ID
            existing = await self.get_user_by_email(email)
            if existing:
                return cast(str, existing["id"])
            raise RuntimeError(f"User {email} already exists but could not be retrieved")
        resp.raise_for_status()

        # Location header contains the new user's URL
        location = resp.headers.get("Location", "")
        kc_user_id = location.rsplit("/", 1)[-1]

        # Assign realm roles if specified
        if realm_roles:
            await self.assign_realm_roles(kc_user_id, realm_roles)

        return cast(str, kc_user_id)

    async def update_user(
        self,
        user_id: str,
        *,
        enabled: bool | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        attributes: dict[str, list[str]] | None = None,
    ) -> None:
        """Update a Keycloak user."""
        payload: dict[str, Any] = {}
        if enabled is not None:
            payload["enabled"] = enabled
        if first_name is not None:
            payload["firstName"] = first_name
        if last_name is not None:
            payload["lastName"] = last_name
        if attributes is not None:
            payload["attributes"] = attributes

        if payload:
            resp = await self._request("PUT", f"/users/{user_id}", json=payload)
            resp.raise_for_status()

    # ------------------------------------------------------------------
    # Role management
    # ------------------------------------------------------------------

    async def get_realm_roles(self) -> list[dict[str, Any]]:
        """List all realm-level roles."""
        resp = await self._request("GET", "/roles")
        resp.raise_for_status()
        return cast(list[dict[str, Any]], resp.json())

    async def get_realm_role_by_name(self, role_name: str) -> dict[str, Any] | None:
        """Get a specific realm role by name."""
        resp = await self._request("GET", f"/roles/{role_name}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return cast(dict[str, Any] | None, resp.json())

    async def get_user_realm_roles(self, user_id: str) -> list[dict[str, Any]]:
        """Get realm roles assigned to a user."""
        resp = await self._request("GET", f"/users/{user_id}/role-mappings/realm")
        resp.raise_for_status()
        return cast(list[dict[str, Any]], resp.json())

    async def assign_realm_roles(self, user_id: str, role_names: list[str]) -> None:
        """Assign realm roles to a user."""
        roles = []
        for name in role_names:
            role = await self.get_realm_role_by_name(name)
            if role:
                roles.append({"id": role["id"], "name": role["name"]})
        if roles:
            resp = await self._request("POST", f"/users/{user_id}/role-mappings/realm", json=roles)
            resp.raise_for_status()

    # ------------------------------------------------------------------
    # Session / logout
    # ------------------------------------------------------------------

    async def logout_user(self, user_id: str) -> None:
        """Terminate all sessions for a user."""
        resp = await self._request("POST", f"/users/{user_id}/logout")
        if resp.status_code not in (200, 204):
            logger.warning("Failed to logout user %s: %s", user_id, resp.status_code)

    async def revoke_token(self, refresh_token: str) -> None:
        """Revoke a token via Keycloak's revocation endpoint."""
        settings = get_settings()
        url = f"{settings.keycloak_openid_base}/revoke"
        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                data={
                    "client_id": settings.keycloak_client_id,
                    "client_secret": settings.keycloak_client_secret,
                    "token": refresh_token,
                    "token_type_hint": "refresh_token",
                },
            )


# Singleton
_admin_client: KeycloakAdminClient | None = None


def get_keycloak_admin() -> KeycloakAdminClient:
    """Return the Keycloak admin client singleton."""
    global _admin_client
    if _admin_client is None:
        _admin_client = KeycloakAdminClient()
    return _admin_client
