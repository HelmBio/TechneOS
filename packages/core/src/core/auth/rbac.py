"""RBAC — Role-Based Access Control utilities."""

from collections.abc import Callable
from typing import Any

from core.exceptions import InsufficientPermissionsError


def check_permission(
    user_permissions: list[str],
    required_resource: str,
    required_action: str,
    required_scope: str = "own",
) -> bool:
    """Check if a set of permissions grants access to a resource/action/scope.

    Permission format: 'resource:action:scope'
    Wildcards: '*' matches any value in that position.

    Returns True if allowed, raises InsufficientPermissionsError if not.
    """
    for perm in user_permissions:
        parts = perm.split(":")
        if len(parts) != 3:
            continue

        p_resource, p_action, p_scope = parts

        resource_match = p_resource == "*" or p_resource == required_resource
        action_match = p_action == "*" or p_action == required_action
        scope_match = _scope_includes(p_scope, required_scope)

        if resource_match and action_match and scope_match:
            return True

    raise InsufficientPermissionsError(required_action, required_resource)


def _scope_includes(granted_scope: str, required_scope: str) -> bool:
    """Check if a granted scope includes the required scope.

    Scope hierarchy: platform > org > team > own
    A higher scope includes all lower scopes.
    """
    hierarchy = ["own", "team", "org", "platform"]

    if granted_scope == "*" or required_scope == "*":
        return True

    try:
        granted_level = hierarchy.index(granted_scope)
        required_level = hierarchy.index(required_scope)
    except ValueError:
        return granted_scope == required_scope

    return granted_level >= required_level


def require_permission(resource: str, action: str, scope: str = "own") -> Callable[..., Any]:
    """FastAPI dependency factory for permission checking.

    Usage:
        @router.get("/datasets")
        async def list_datasets(
            user: TokenPayload = Depends(get_current_user),
            _: bool = Depends(require_permission("dataset", "read", "team")),
        ):
    """
    from fastapi import Depends

    from core.auth.dependencies import get_current_user
    from core.models.common import TokenPayload

    async def _check(user: TokenPayload = Depends(get_current_user)) -> bool:

        permissions = getattr(user, "permissions", []) or []
        check_permission(permissions, resource, action, scope)
        return True

    # Expose the requirement so the OpenAPI layer can document which permission
    # each endpoint needs (see core.auth.openapi.install_permission_annotations).
    _check.required_permission = f"{resource}:{action}:{scope}"  # type: ignore[attr-defined]
    return _check
