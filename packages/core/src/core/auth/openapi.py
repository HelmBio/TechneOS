"""Document the RBAC permission each endpoint requires in the OpenAPI schema.

FastAPI treats the ``require_permission(...)`` dependency as an opaque callable,
so the authorization rule an endpoint enforces never reaches its schema — the docs
show only that a token is required, not *which* permission. ``require_permission``
tags its dependency with a ``required_permission`` string; this module walks an
app's routes, finds that tag, and writes it onto each operation as both a machine-
readable ``x-required-permission`` field and a human line appended to the
description (so it shows in Swagger).

Each service calls ``install_permission_annotations(app)`` on its own app; the
gateway then merges those already-annotated paths, so both a service's own /docs
and the aggregated gateway /docs surface the requirement.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI

from core.auth.dependencies import get_current_admin_user, get_current_superuser

try:
    # FastAPI's own flattener (the one get_openapi uses) — resolves nested routers
    # and prefixes into (full path, methods, route) contexts.
    from fastapi.routing import iter_route_contexts
except ImportError:  # pragma: no cover - older/newer FastAPI without this helper
    iter_route_contexts = None  # type: ignore[assignment]


def _route_requirement(route: Any) -> tuple[str, str] | None:
    """The access requirement of a route, as ``(kind, value)``:

    - ``("permission", "tool:read:team")`` for a ``require_permission`` gate,
    - ``("role", "platform_admin")`` for a superuser/admin gate,

    or ``None`` if the route only needs an authenticated user (or nothing).
    A specific permission wins over a role gate when both are present.
    """
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return None
    stack = list(getattr(dependant, "dependencies", []))
    role: str | None = None
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        perm = getattr(call, "required_permission", None)
        if isinstance(perm, str):
            return ("permission", perm)
        if call is get_current_superuser:
            role = "platform_admin"
        elif call is get_current_admin_user and role is None:
            role = "platform_admin or org_admin"
        stack.extend(getattr(dep, "dependencies", []))
    return ("role", role) if role else None


def _requirements_by_operation(app: FastAPI) -> Iterator[tuple[str, str, tuple[str, str]]]:
    """Yield (path, method, (kind, value)) for every access-gated operation."""
    if iter_route_contexts is None:
        return
    for ctx in iter_route_contexts(app.routes):
        req = _route_requirement(getattr(ctx, "route", None))
        path = getattr(ctx, "path", None)
        if not req or not path:
            continue
        for method in getattr(ctx, "methods", None) or set():
            yield path, method.lower(), req


def annotate_schema_requirements(schema: dict[str, Any], app: FastAPI) -> dict[str, Any]:
    """Write each of ``app``'s gated operations' requirement onto ``schema`` in
    place. Operations whose path/method aren't among ``app``'s own routes are
    left untouched — so the gateway can annotate its own routes without disturbing
    the already-annotated service paths it merged in."""
    reqs = {(p, m): req for p, m, req in _requirements_by_operation(app)}
    for path, item in schema.get("paths", {}).items():
        for method, operation in item.items():
            req = reqs.get((path, method.lower()))
            if not req or not isinstance(operation, dict):
                continue
            kind, value = req
            field = "x-required-permission" if kind == "permission" else "x-required-role"
            if operation.get(field) == value:
                continue  # already annotated (schema is cached & reused)
            operation[field] = value
            label = "permission" if kind == "permission" else "role"
            description = operation.get("description") or ""
            operation["description"] = f"{description}\n\n**Requires {label}:** `{value}`"
    return schema


def install_permission_annotations(app: FastAPI) -> None:
    """Override ``app.openapi`` so each gated operation documents its requirement."""
    base_openapi = app.openapi

    def _openapi() -> dict[str, Any]:
        return annotate_schema_requirements(base_openapi(), app)

    app.openapi = _openapi  # type: ignore[method-assign]
