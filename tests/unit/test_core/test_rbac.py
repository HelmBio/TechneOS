"""Tests for the RBAC system."""

import pytest

from core.auth.rbac import _scope_includes, check_permission
from core.exceptions import InsufficientPermissionsError


class TestScopeIncludes:
    """Test scope hierarchy checking."""

    def test_platform_includes_all(self):
        assert _scope_includes("platform", "own") is True
        assert _scope_includes("platform", "team") is True
        assert _scope_includes("platform", "org") is True
        assert _scope_includes("platform", "platform") is True

    def test_org_includes_lower(self):
        assert _scope_includes("org", "own") is True
        assert _scope_includes("org", "team") is True
        assert _scope_includes("org", "org") is True
        assert _scope_includes("org", "platform") is False

    def test_team_includes_lower(self):
        assert _scope_includes("team", "own") is True
        assert _scope_includes("team", "team") is True
        assert _scope_includes("team", "org") is False

    def test_own_only_includes_own(self):
        assert _scope_includes("own", "own") is True
        assert _scope_includes("own", "team") is False

    def test_wildcard_includes_all(self):
        assert _scope_includes("*", "own") is True
        assert _scope_includes("*", "platform") is True

    def test_wildcard_required_scope(self):
        assert _scope_includes("own", "*") is True
        assert _scope_includes("team", "*") is True
        assert _scope_includes("org", "*") is True
        assert _scope_includes("platform", "*") is True
        assert _scope_includes("*", "*") is True


class TestCheckPermission:
    """Test permission checking logic."""

    def test_wildcard_all(self):
        """platform_admin with *:*:platform can do anything."""
        assert check_permission(["*:*:platform"], "dataset", "create", "org") is True
        assert check_permission(["*:*:platform"], "user", "delete", "platform") is True

    def test_specific_permission(self):
        """Exact match on resource:action:scope."""
        assert check_permission(["dataset:read:team"], "dataset", "read", "own") is True
        assert check_permission(["dataset:read:team"], "dataset", "read", "team") is True

    def test_insufficient_scope(self):
        """Permission at lower scope should not grant higher scope access."""
        with pytest.raises(InsufficientPermissionsError):
            check_permission(["dataset:read:own"], "dataset", "read", "team")

    def test_wrong_resource(self):
        """Permission for different resource should not grant access."""
        with pytest.raises(InsufficientPermissionsError):
            check_permission(["dataset:read:team"], "pipeline", "read", "team")

    def test_wrong_action(self):
        """Permission for different action should not grant access."""
        with pytest.raises(InsufficientPermissionsError):
            check_permission(["dataset:read:team"], "dataset", "delete", "team")

    def test_wildcard_action(self):
        """Wildcard action should match any action."""
        assert check_permission(["dataset:*:team"], "dataset", "read", "team") is True
        assert check_permission(["dataset:*:team"], "dataset", "delete", "team") is True

    def test_wildcard_resource(self):
        """Wildcard resource should match any resource."""
        assert check_permission(["*:read:own"], "dataset", "read", "own") is True
        assert check_permission(["*:read:own"], "pipeline", "read", "own") is True

    def test_multiple_permissions(self):
        """Should check all permissions, pass if any matches."""
        perms = ["dataset:read:team", "pipeline:execute:own"]
        assert check_permission(perms, "dataset", "read", "own") is True
        assert check_permission(perms, "pipeline", "execute", "own") is True
        with pytest.raises(InsufficientPermissionsError):
            check_permission(perms, "user", "delete", "org")

    def test_scientist_role_permissions(self):
        """Test the default scientist role permissions."""
        scientist_perms = [
            "dataset:create:own",
            "dataset:read:team",
            "pipeline:create:own",
            "pipeline:execute:own",
            "pipeline:read:team",
            "tool:create:own",
            "tool:read:team",
            "result:read:team",
        ]
        # Can read datasets at team level
        assert check_permission(scientist_perms, "dataset", "read", "team") is True
        # Can create own datasets
        assert check_permission(scientist_perms, "dataset", "create", "own") is True
        # Can create own datasets with wildcard required scope
        assert check_permission(scientist_perms, "dataset", "create", "*") is True
        # Cannot create datasets at team scope
        with pytest.raises(InsufficientPermissionsError):
            check_permission(scientist_perms, "dataset", "create", "team")
        # Can execute own pipelines
        assert check_permission(scientist_perms, "pipeline", "execute", "own") is True
        # Cannot delete pipelines
        with pytest.raises(InsufficientPermissionsError):
            check_permission(scientist_perms, "pipeline", "delete", "team")
