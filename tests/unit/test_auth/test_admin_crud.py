"""Tests for auth admin CRUD operations."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions import AlreadyExistsError, NotFoundError


def _mock_scalar(result, attr="scalar_one"):
    m = MagicMock()
    getattr(m, attr).return_value = result
    return m


def _mock_scalars_list(results):
    m = MagicMock()
    m.scalars.return_value.all.return_value = results
    return m


def _mock_scalar_one_none():
    m = MagicMock()
    m.scalar_one_or_none.return_value = None
    return m


@pytest.fixture
def session():
    s = AsyncMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.delete = AsyncMock()
    s.execute = AsyncMock()
    return s


class TestPlatformStats:
    async def test_get_platform_stats(self, session):
        from auth_service.crud.admin import get_platform_stats

        # Order matches the queries in get_platform_stats: users(2), orgs(2),
        # teams, roles, llm_providers(2), buckets(2), compute_backends(2),
        # artifacts(1).
        counts = [100, 80, 10, 8, 15, 5, 3, 2, 7, 1, 4, 3, 9]
        session.execute.side_effect = [_mock_scalar(c) for c in counts]

        stats = await get_platform_stats(session)

        assert stats["total_users"] == 100
        assert stats["active_users"] == 80
        assert stats["total_orgs"] == 10
        assert stats["active_orgs"] == 8
        assert stats["total_teams"] == 15
        assert stats["total_roles"] == 5
        assert stats["total_llm_providers"] == 3
        assert stats["default_llm_providers"] == 2
        assert stats["total_buckets"] == 7
        assert stats["default_buckets"] == 1
        assert stats["total_compute_backends"] == 4
        assert stats["enabled_compute_backends"] == 3
        assert stats["total_artifacts"] == 9
        assert session.execute.call_count == 13


class TestAdminUpdateUser:
    async def test_updates_fields_and_resolves_role_name(self, session):
        from auth_service.crud.admin import admin_update_user
        from core.models.common import AdminUserUpdate

        mock_role = MagicMock()
        mock_role.id = "role-1"
        mock_user = MagicMock()
        mock_user.role = MagicMock()

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user
        role_result = MagicMock()
        role_result.scalar_one_or_none.return_value = mock_role
        session.execute.side_effect = [user_result, role_result]

        data = AdminUserUpdate(is_active=True, role_name="admin")

        user = await admin_update_user(session, "user-1", data)

        assert user.is_active is True
        assert user.role_id == "role-1"

    async def test_raises_not_found(self, session):
        from auth_service.crud.admin import admin_update_user
        from core.models.common import AdminUserUpdate

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        data = AdminUserUpdate(is_active=True)
        with pytest.raises(NotFoundError):
            await admin_update_user(session, "bad-id", data)


class TestAdminResetPassword:
    @patch("auth_service.crud.admin.hash_password")
    async def test_resets_password(self, mock_hash, session):
        from auth_service.crud.admin import admin_reset_password

        mock_hash.return_value = "$2b$hashed"

        mock_user = MagicMock()
        mock_user.hashed_password = None
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_user
        session.execute.return_value = result

        user = await admin_reset_password(session, "user-1", "new-secret")

        mock_hash.assert_called_once_with("new-secret")
        assert user.hashed_password == "$2b$hashed"
        session.flush.assert_called_once()

    async def test_raises_not_found(self, session):
        from auth_service.crud.admin import admin_reset_password

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        with pytest.raises(NotFoundError):
            await admin_reset_password(session, "bad-id", "new-pw")


class TestRoles:
    async def test_list_roles(self, session):
        from auth_service.crud.admin import list_roles

        mock_role = MagicMock()
        mock_role.name = "scientist"
        session.execute.return_value = _mock_scalars_list([mock_role])

        roles = await list_roles(session)
        assert len(roles) == 1
        assert roles[0].name == "scientist"

    async def test_create_role(self, session):
        from auth_service.crud.admin import create_role

        role = await create_role(
            session, name="viewer", description="Read-only", permissions=["dataset:read"]
        )
        assert role.name == "viewer"
        assert role.description == "Read-only"
        assert role.permissions == ["dataset:read"]
        session.add.assert_called_once()

    async def test_update_role(self, session):
        from auth_service.crud.admin import update_role
        from core.models.common import RoleUpdate

        mock_role = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_role
        session.execute.return_value = result

        data = RoleUpdate(description="Updated", permissions=["dataset:read", "pipeline:read"])
        role = await update_role(session, "role-1", data)

        assert role.description == "Updated"
        assert role.permissions == ["dataset:read", "pipeline:read"]
        session.flush.assert_called_once()

    async def test_update_role_not_found(self, session):
        from auth_service.crud.admin import update_role
        from core.models.common import RoleUpdate

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        with pytest.raises(NotFoundError):
            await update_role(session, "bad-id", RoleUpdate(description="x"))


class TestOrgs:
    async def test_create_org(self, session):
        from auth_service.crud.admin import create_org

        org = await create_org(session, name="TestOrg", slug="test-org", description="Testing")
        assert org.name == "TestOrg"
        assert org.slug == "test-org"
        assert org.description == "Testing"
        assert org.is_active is True
        session.add.assert_called_once()

    async def test_update_org(self, session):
        from auth_service.crud.admin import update_org
        from core.models.common import OrgUpdate

        mock_org = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_org
        session.execute.return_value = result

        data = OrgUpdate(name="Renamed", is_active=False)
        org = await update_org(session, "org-1", data)

        assert org.name == "Renamed"
        assert org.is_active is False

    async def test_update_org_not_found(self, session):
        from auth_service.crud.admin import update_org
        from core.models.common import OrgUpdate

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        with pytest.raises(NotFoundError):
            await update_org(session, "bad-id", OrgUpdate(name="x"))


class TestLLMProviders:
    async def test_list_llm_providers(self, session):
        from auth_service.crud.admin import list_llm_providers

        mock_provider = MagicMock()
        mock_provider.name = "OpenAI"
        session.execute.side_effect = [
            _mock_scalar(5),
            _mock_scalars_list([mock_provider]),
        ]

        providers, total = await list_llm_providers(session, skip=0, limit=10)
        assert total == 5
        assert len(providers) == 1
        assert providers[0].name == "OpenAI"

    async def test_create_llm_provider(self, session):
        from auth_service.crud.admin import create_llm_provider

        none_result = MagicMock()
        none_result.scalar_one_or_none.return_value = None
        session.execute.return_value = none_result

        provider = await create_llm_provider(
            session,
            name="OpenAI",
            slug="openai",
            api_key="sk-test",
            default_model="gpt-4",
            org_id="org-1",
            created_by="u-1",
        )
        assert provider.name == "OpenAI"
        assert provider.slug == "openai"
        assert provider.is_default is False
        session.add.assert_called_once()

    async def test_create_llm_provider_duplicate_slug(self, session):
        from auth_service.crud.admin import create_llm_provider

        existing = MagicMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing
        session.execute.return_value = existing_result

        with pytest.raises(AlreadyExistsError):
            await create_llm_provider(
                session,
                name="OpenAI",
                slug="openai",
                api_key="sk-test",
                default_model="gpt-4",
                org_id="org-1",
                created_by="u-1",
            )

    async def test_create_llm_provider_is_default_clears_others(self, session):
        from auth_service.crud.admin import create_llm_provider

        none_result = MagicMock()
        none_result.scalar_one_or_none.return_value = None
        session.execute.return_value = none_result

        provider = await create_llm_provider(
            session,
            name="OpenAI",
            slug="openai",
            api_key="sk-test",
            default_model="gpt-4",
            org_id="org-1",
            created_by="u-1",
            is_default=True,
        )
        assert provider.is_default is True
        # Should have called _clear_llm_defaults which issues an update
        update_call = [c for c in session.execute.call_args_list if "update" in str(c).lower()]
        assert len(update_call) > 0

    async def test_update_llm_provider(self, session):
        from auth_service.crud.admin import update_llm_provider

        mock_provider = MagicMock()
        mock_provider.org_id = "org-1"
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_provider
        session.execute.return_value = result

        provider = await update_llm_provider(
            session, "prov-1", {"name": "Azure OpenAI", "is_default": True}
        )
        assert provider.name == "Azure OpenAI"
        assert provider.is_default is True

    async def test_update_llm_provider_not_found(self, session):
        from auth_service.crud.admin import update_llm_provider

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        with pytest.raises(NotFoundError):
            await update_llm_provider(session, "bad-id", {"name": "x"})

    async def test_delete_llm_provider(self, session):
        from auth_service.crud.admin import delete_llm_provider

        mock_provider = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_provider
        session.execute.return_value = result

        await delete_llm_provider(session, "prov-1")
        session.delete.assert_called_once_with(mock_provider)
        session.flush.assert_called_once()

    async def test_delete_llm_provider_not_found(self, session):
        from auth_service.crud.admin import delete_llm_provider

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        with pytest.raises(NotFoundError):
            await delete_llm_provider(session, "bad-id")


class TestAuditLogs:
    async def test_list_audit_logs_with_filters(self, session):
        from auth_service.crud.admin import list_audit_logs

        mock_log = MagicMock()
        mock_log.action = "user.login"
        session.execute.return_value = _mock_scalars_list([mock_log])

        logs = await list_audit_logs(
            session, action="user.login", user_id="u-1", resource_type="user"
        )
        assert len(logs) == 1
        assert logs[0].action == "user.login"

    async def test_list_audit_logs_no_filters(self, session):
        from auth_service.crud.admin import list_audit_logs

        mock_logs = [MagicMock(), MagicMock()]
        session.execute.return_value = _mock_scalars_list(mock_logs)

        logs = await list_audit_logs(session)
        assert len(logs) == 2

    async def test_count_audit_logs_with_filters(self, session):
        from auth_service.crud.admin import count_audit_logs

        session.execute.return_value = _mock_scalar(42)
        count = await count_audit_logs(session, action="user.login")
        assert count == 42


class TestServiceHealth:
    @patch("auth_service.crud.admin.httpx.AsyncClient")
    async def test_all_healthy(self, mock_httpx):
        from auth_service.crud.admin import check_services_health

        mock_client = AsyncMock()
        healthy_resp = MagicMock()
        healthy_resp.status_code = 200
        mock_client.get.return_value = healthy_resp
        mock_client.__aenter__.return_value = mock_client
        mock_httpx.return_value = mock_client

        results = await check_services_health()
        assert len(results) == 8
        assert all(r["status"] == "healthy" for r in results)

    @patch("auth_service.crud.admin.httpx.AsyncClient")
    async def test_some_unhealthy(self, mock_httpx):
        from auth_service.crud.admin import check_services_health

        mock_client = AsyncMock()
        # We need the client.get to return different values for each call
        mock_client.get.side_effect = [
            MagicMock(status_code=200),  # auth
            MagicMock(status_code=503),  # dataset — unhealthy
            MagicMock(status_code=200),  # tool
            MagicMock(status_code=200),  # pipeline
            MagicMock(status_code=200),  # agent
            MagicMock(status_code=200),  # app
            MagicMock(status_code=200),  # task
            MagicMock(status_code=200),  # notification
        ]
        mock_client.__aenter__.return_value = mock_client
        mock_httpx.return_value = mock_client

        results = await check_services_health()
        assert results[0]["status"] == "healthy"
        assert results[1]["status"] == "unhealthy"

    @patch("auth_service.crud.admin.httpx.AsyncClient")
    async def test_some_unreachable(self, mock_httpx):
        from httpx import ConnectError

        from auth_service.crud.admin import check_services_health

        mock_client = AsyncMock()
        mock_client.get.side_effect = ConnectError("Connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_httpx.return_value = mock_client

        results = await check_services_health()
        assert all(r["status"] == "unreachable" for r in results)
        assert all(r["latency_ms"] is None for r in results)


class TestAdminDeleteUserGuards:
    """Security guards on admin_delete_user (the destructive cascade)."""

    def _user(self, **kw):
        from core.models.user import User

        defaults = dict(id="u1", email="a@b.com", full_name="A", org_id="o1")
        defaults.update(kw)
        return User(**defaults)

    async def test_not_found(self, session):
        from auth_service.crud.admin import admin_delete_user

        session.execute.return_value = _mock_scalar_one_none()
        with pytest.raises(NotFoundError):
            await admin_delete_user(session, "missing")

    async def test_sso_user_can_be_deleted(self, session):
        from auth_service.crud.admin import admin_delete_user

        # No hashed_password → auth_method == "sso".
        sso_user = self._user(hashed_password=None, role_id=None)
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = sso_user
        runs_result = MagicMock()
        runs_result.scalars.return_value.all.return_value = []
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        session.execute.side_effect = [user_result, runs_result] + [count_result] * 50

        summary = await admin_delete_user(session, "u1")

        assert summary["deleted"] is True
        assert summary["user"]["auth_method"] == "sso"

    async def test_platform_admin_protected(self, session):
        from fastapi import HTTPException

        from auth_service.crud.admin import admin_delete_user

        local_admin = self._user(hashed_password="hash", role_id="r-admin")
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = local_admin
        role_result = MagicMock()
        role_result.scalar_one_or_none.return_value = "platform_admin"
        session.execute.side_effect = [user_result, role_result]
        with pytest.raises(HTTPException) as exc:
            await admin_delete_user(session, "u1")
        assert exc.value.status_code == 422
        assert "platform_admin" in exc.value.detail

    async def test_org_admin_cannot_cross_org(self, session):
        from fastapi import HTTPException

        from auth_service.crud.admin import admin_delete_user

        # Local user in org "o1"; caller is an org_admin from "o2".
        local_user = self._user(hashed_password="hash", role_id=None, org_id="o1")
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = local_user
        session.execute.return_value = user_result
        with pytest.raises(HTTPException) as exc:
            await admin_delete_user(
                session, "u1", caller_role="org_admin", caller_org_id="o2"
            )
        assert exc.value.status_code == 403


    def test_every_user_reference_is_handled(self):
        """Each column pointing at users.id is deleted or cleared, so the
        final DELETE on users can't hit a foreign-key error (a 500)."""
        import importlib
        import pkgutil

        import core.models
        from auth_service.crud.admin import _USER_DEPENDENTS, _USER_NULLABLE_REFERENCES
        from core.models import Base

        for mod in pkgutil.iter_modules(core.models.__path__):
            importlib.import_module(f"core.models.{mod.name}")

        referencing = {
            (table.name, column.name)
            for table in Base.metadata.tables.values()
            for column in table.columns
            for fk in column.foreign_keys
            if fk.target_fullname == "users.id"
        }
        handled = {
            (model.__tablename__, column)
            for _label, model, column in _USER_DEPENDENTS
            if column != "run_id"
        } | {(model.__tablename__, column) for model, column in _USER_NULLABLE_REFERENCES}

        assert referencing - handled == set()


class TestDeleteKeycloakUser:
    """delete_keycloak_user removes the sign-in account after a platform delete."""

    @pytest.fixture
    def kc(self):
        kc = MagicMock()
        kc.get_user_by_id = AsyncMock(return_value={"id": "kc-1", "email": "a@b.com"})
        kc.get_user_by_email = AsyncMock(return_value=None)
        kc.delete_user = AsyncMock(return_value=True)
        return kc

    async def _run(self, kc, external_id, email, configured=True):
        from auth_service.crud.admin import delete_keycloak_user

        settings = MagicMock(keycloak_configured=configured)
        with (
            patch("auth_service.crud.admin.get_settings", return_value=settings),
            patch("core.auth.keycloak_admin.get_keycloak_admin", return_value=kc),
        ):
            return await delete_keycloak_user(external_id, email)

    async def test_skipped_without_keycloak(self, kc):
        assert await self._run(kc, "kc-1", "a@b.com", configured=False) == "skipped"
        kc.delete_user.assert_not_awaited()

    async def test_deletes_by_external_id(self, kc):
        assert await self._run(kc, "kc-1", "A@B.com") == "deleted"
        kc.delete_user.assert_awaited_once_with("kc-1")

    async def test_falls_back_to_email_when_id_email_differs(self, kc):
        # e.g. an enterprise OAuth2 subject that happens to match another account
        kc.get_user_by_id.return_value = {"id": "kc-other", "email": "other@b.com"}
        kc.get_user_by_email.return_value = {"id": "kc-2", "email": "a@b.com"}
        assert await self._run(kc, "kc-other", "a@b.com") == "deleted"
        kc.delete_user.assert_awaited_once_with("kc-2")

    async def test_not_found(self, kc):
        kc.get_user_by_id.return_value = None
        assert await self._run(kc, None, "a@b.com") == "not_found"
        kc.get_user_by_id.assert_not_awaited()
        kc.delete_user.assert_not_awaited()

    async def test_failure_is_reported_not_raised(self, kc):
        kc.delete_user.side_effect = RuntimeError("keycloak down")
        assert await self._run(kc, "kc-1", "a@b.com") == "failed"


class TestDeleteUserRoute:
    """DELETE /admin/users/by-email removes the Keycloak account after committing."""

    async def _call(self, session, *, dry_run):
        from auth_service.routes.admin import admin_delete_user_by_email
        from core.models.user import User

        user = User(id="u1", email="a@b.com", full_name="A", org_id="o1", external_id="kc-1")
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        session.execute.return_value = result
        session.commit = AsyncMock()
        caller = MagicMock(sub="admin-1", role="platform_admin", org_id="o1")
        request = MagicMock(headers={})

        with (
            patch(
                "auth_service.routes.admin.admin_delete_user",
                new=AsyncMock(return_value={"dry_run": dry_run}),
            ),
            patch("auth_service.routes.admin.write_audit_log", new=AsyncMock()),
            patch(
                "auth_service.routes.admin.delete_keycloak_user",
                new=AsyncMock(return_value="deleted"),
            ) as kc_delete,
        ):
            summary = await admin_delete_user_by_email(
                "a@b.com", request, dry_run=dry_run, session=session, current_user=caller
            )
        return summary, kc_delete

    async def test_deletes_keycloak_account(self, session):
        summary, kc_delete = await self._call(session, dry_run=False)
        session.commit.assert_awaited_once()
        kc_delete.assert_awaited_once_with("kc-1", "a@b.com")
        assert summary["keycloak"] == "deleted"

    async def test_dry_run_leaves_keycloak_alone(self, session):
        summary, kc_delete = await self._call(session, dry_run=True)
        kc_delete.assert_not_awaited()
        assert "keycloak" not in summary
