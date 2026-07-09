"""Resource scoping — enforce data-level access based on user permissions.

Two main utilities:

* ``check_resource_access(user, resource, *, resource_name)`` — raises 403
  if the user cannot access a specific resource instance.
* ``build_scope_filters(user, model, resource)`` — returns SQLAlchemy filter
  conditions to restrict list queries to what the user may see.

Both functions derive the data scope from the user's permission strings
(``resource:action:scope``) rather than from the role name.  This keeps
the seed-data role definitions as the single source of truth for access
boundaries.

Scope hierarchy:  ``own < team < org < platform``
A granted scope implicitly includes all lower scopes.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import BooleanClauseList, ColumnElement, or_, select

from core.models.common import TokenPayload

_SCOPE_HIERARCHY = ["own", "team", "org", "platform"]


def _max_scope(user: TokenPayload, resource: str) -> str:
    """Return the highest scope the user has for *resource* across all actions."""
    max_level = 0
    for perm in user.permissions:
        parts = perm.split(":")
        if len(parts) != 3:
            continue
        p_resource, _p_action, p_scope = parts
        if p_resource in ("*", resource):
            try:
                level = _SCOPE_HIERARCHY.index(p_scope)
                max_level = max(max_level, level)
            except ValueError:
                pass
    return _SCOPE_HIERARCHY[max_level]


# ── Single-resource access check ────────────────────────────────────


def check_resource_access(
    user: TokenPayload,
    resource: Any,
    *,
    resource_name: str,
    write: bool = False,
) -> None:
    """Raise 403 if *user* may not access *resource*.

    Parameters
    ----------
    user:
        The authenticated user's token payload.
    resource:
        An ORM model instance.  Expected to have ``org_id`` and
        optionally ``created_by`` / ``submitted_by``, ``team_id``,
        ``is_public``.
    resource_name:
        The platform resource name used to look up the user's scope
        from their permission strings (e.g. ``"pipeline"``, ``"dataset"``).
    write:
        If True, public resources owned by another org are **not**
        accessible (read-only sharing).
    """
    scope = _max_scope(user, resource_name)

    if scope == "platform":
        return

    res_org_id: str | None = getattr(resource, "org_id", None)
    res_owner: str | None = getattr(resource, "created_by", None) or getattr(
        resource, "submitted_by", None
    )
    res_team_id: str | None = getattr(resource, "team_id", None)
    res_public: bool = getattr(resource, "is_public", False) or False

    if res_public and not write:
        return

    same_org = res_org_id is not None and res_org_id == user.org_id
    is_owner = res_owner is not None and res_owner == user.sub
    same_team = res_team_id is not None and user.team_id is not None and res_team_id == user.team_id

    if scope == "org":
        if same_org:
            return

    elif scope == "team":
        if res_team_id is None:
            if is_owner:
                return
        elif same_org and (same_team or is_owner):
            return

    elif scope == "own" and is_owner:
        return

    raise HTTPException(status_code=403, detail="Access denied")


# ── List-query scope filters ────────────────────────────────────────


def build_scope_filters(
    user: TokenPayload,
    model: Any,
    resource: str,
) -> list[ColumnElement[bool] | BooleanClauseList]:
    """Return SQLAlchemy ``where`` clauses that restrict a list query.

    The caller should apply them **all** via ``stmt.where(*filters)``.
    An empty list means "no restriction" (*platform* scope).
    """
    scope = _max_scope(user, resource)

    if scope == "platform":
        return []

    org_col = getattr(model, "org_id", None)
    owner_col = getattr(model, "created_by", None) or getattr(model, "submitted_by", None)
    team_col = getattr(model, "team_id", None)
    public_col = getattr(model, "is_public", None)

    conditions: list[ColumnElement[bool]] = []

    if scope == "org":
        if org_col is not None and user.org_id:
            base = org_col == user.org_id
            if public_col is not None:
                conditions.append(or_(base, public_col == True))  # noqa: E712
            else:
                conditions.append(base)
        elif public_col is not None:
            conditions.append(public_col == True)  # noqa: E712

    elif scope == "team":
        parts: list[ColumnElement[bool]] = []
        if org_col is not None and user.org_id:
            org_match = org_col == user.org_id
            if team_col is not None:
                team_or_own: list[ColumnElement[bool]] = []
                if user.team_id:
                    team_or_own.append(team_col == user.team_id)
                if owner_col is not None:
                    team_or_own.append(owner_col == user.sub)
                if team_or_own:
                    parts.append(org_match & or_(*team_or_own))
                else:
                    parts.append(org_match)
            elif owner_col is not None and user.team_id:
                from core.models.user import User

                team_member_ids = select(User.id).where(
                    User.team_id == user.team_id,
                    User.org_id == user.org_id,
                )
                parts.append(owner_col.in_(team_member_ids))
            else:
                parts.append(org_match)
        if public_col is not None:
            parts.append(public_col == True)  # noqa: E712
        if parts:
            conditions.append(or_(*parts))

    else:
        # own scope — own + public
        parts_v: list[ColumnElement[bool]] = []
        if owner_col is not None:
            parts_v.append(owner_col == user.sub)
        if public_col is not None:
            parts_v.append(public_col == True)  # noqa: E712
        if parts_v:
            conditions.append(or_(*parts_v))
        else:
            if org_col is not None:
                conditions.append(org_col == "__deny__")

    return conditions
