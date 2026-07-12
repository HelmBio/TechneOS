"""CRUD-layer tests for the auth service's org / team / user data access.

These are the security- and data-integrity-sensitive write paths (user
creation, password change, org/team uniqueness). The DB session is an
AsyncMock — each ``session.execute`` call is fed a canned result object.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from auth_service.crud import orgs as orgs_crud
from auth_service.crud import teams as teams_crud
from auth_service.crud import users as users_crud
from core.exceptions import (
    AlreadyExistsError,
    InvalidCredentialsError,
    NotFoundError,
)
from core.models.common import (
    OrgCreate,
    OrgUpdate,
    TeamCreate,
    TeamUpdate,
    UserCreate,
    UserUpdate,
)

# ── result-object helpers ──────────────────────────────────────────────────────


def _one_or_none(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalar_one(value):
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalars_all(items):
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


@pytest.fixture
def session():
    s = AsyncMock()
    s.execute = AsyncMock()
    s.flush = AsyncMock()
    s.refresh = AsyncMock()
    s.rollback = AsyncMock()
    s.add = MagicMock()
    return s


# ── orgs ────────────────────────────────────────────────────────────────────────


class TestOrgCrud:
    async def test_create_org_success(self, session):
        session.execute.return_value = _one_or_none(None)  # slug not taken
        org = await orgs_crud.create_org(session, OrgCreate(name="Acme", slug="acme"))
        assert org.slug == "acme"
        session.add.assert_called_once()
        session.flush.assert_awaited()

    async def test_create_org_duplicate_slug(self, session):
        session.execute.return_value = _one_or_none(object())  # slug exists
        with pytest.raises(AlreadyExistsError):
            await orgs_crud.create_org(session, OrgCreate(name="Acme", slug="acme"))

    async def test_update_org_success(self, session):
        from core.models.user import Org

        org = Org(id="o1", name="Old", slug="acme")
        session.execute.return_value = _one_or_none(org)
        updated = await orgs_crud.update_org(session, "o1", OrgUpdate(name="New"))
        assert updated.name == "New"

    async def test_update_org_not_found(self, session):
        session.execute.return_value = _one_or_none(None)
        with pytest.raises(NotFoundError):
            await orgs_crud.update_org(session, "missing", OrgUpdate(name="X"))

    async def test_get_org_by_slug(self, session):
        marker = object()
        session.execute.return_value = _one_or_none(marker)
        assert await orgs_crud.get_org_by_slug(session, "acme") is marker


# ── teams ─────────────────────────────────────────────────────────────────────


class TestTeamCrud:
    @pytest.mark.parametrize(
        "name, expected",
        [("Research Team", "research-team"), ("  ", "team"), ("A/B  C", "a-b-c")],
    )
    def test_slugify(self, name, expected):
        assert teams_crud._slugify(name) == expected

    async def test_create_team_success(self, session):
        from core.models.user import Org

        session.execute.return_value = _one_or_none(Org(id="o1", name="Acme", slug="acme"))
        team = await teams_crud.create_team(session, "o1", TeamCreate(name="Research Team"))
        assert team.slug == "research-team"
        assert team.org_id == "o1"

    async def test_create_team_org_missing(self, session):
        session.execute.return_value = _one_or_none(None)
        with pytest.raises(NotFoundError):
            await teams_crud.create_team(session, "missing", TeamCreate(name="R"))

    async def test_create_team_duplicate_slug_raises_already_exists(self, session):
        from sqlalchemy.exc import IntegrityError

        from core.models.user import Org

        session.execute.return_value = _one_or_none(Org(id="o1", name="Acme", slug="acme"))
        session.flush.side_effect = IntegrityError(
            "stmt", {}, Exception("uq_teams_org_slug violation")
        )
        with pytest.raises(AlreadyExistsError):
            await teams_crud.create_team(session, "o1", TeamCreate(name="Research"))
        session.rollback.assert_awaited()

    async def test_update_team_not_found(self, session):
        session.execute.return_value = _one_or_none(None)
        with pytest.raises(NotFoundError):
            await teams_crud.update_team(session, "missing", TeamUpdate(name="X"))

    async def test_list_and_count_teams(self, session):
        from core.models.user import Team

        session.execute.side_effect = [
            _scalars_all([Team(id="t1", name="A", slug="a", org_id="o1")]),
            _scalar_one(1),
        ]
        teams = await teams_crud.list_teams(session, "o1")
        count = await teams_crud.count_teams(session, "o1")
        assert len(teams) == 1 and count == 1


# ── users ─────────────────────────────────────────────────────────────────────


class TestUserCrud:
    async def test_create_user_resolves_role(self, session):
        from core.models.user import Role

        session.execute.return_value = _one_or_none(Role(id="r1", name="scientist"))
        user = await users_crud.create_user(
            session,
            UserCreate(
                email="a@b.com", password="pw12345678", full_name="A",
                role_name="scientist", org_id="o1",
            ),
        )
        assert user.email == "a@b.com"
        assert user.role_id == "r1"
        assert user.hashed_password  # a hash was set, not the plaintext
        assert user.hashed_password != "pw12345678"

    async def test_create_user_unknown_role_leaves_role_id_none(self, session):
        # Role lookup returns nothing → role_id stays None (user still created).
        session.execute.return_value = _one_or_none(None)
        user = await users_crud.create_user(
            session, UserCreate(email="a@b.com", password="pw12345678", full_name="A", org_id="o1")
        )
        assert user.role_id is None
        assert user.email == "a@b.com"

    async def test_update_user_not_found(self, session):
        session.execute.return_value = _one_or_none(None)
        with pytest.raises(NotFoundError):
            await users_crud.update_user(session, "missing", UserUpdate(full_name="X"))

    async def test_update_user_drops_org_id(self, session):
        from core.models.user import User

        user = User(id="u1", email="a@b", full_name="A", org_id="o1")
        session.execute.return_value = _one_or_none(user)
        # org_id must be ignored by the normal update path (immutable here).
        await users_crud.update_user(session, "u1", UserUpdate(full_name="New", org_id="o2"))
        assert user.full_name == "New"
        assert user.org_id == "o1"  # unchanged

    async def test_change_password_success(self, session):
        from core.auth.providers import hash_password, verify_password
        from core.models.user import User

        user = User(id="u1", email="a@b", full_name="A", hashed_password=hash_password("oldpw123"))
        session.execute.return_value = _one_or_none(user)
        await users_crud.change_password(session, "u1", "oldpw123", "newpw456")
        assert verify_password("newpw456", user.hashed_password)

    async def test_change_password_wrong_current(self, session):
        from core.auth.providers import hash_password
        from core.models.user import User

        user = User(id="u1", email="a@b", full_name="A", hashed_password=hash_password("oldpw123"))
        session.execute.return_value = _one_or_none(user)
        with pytest.raises(InvalidCredentialsError):
            await users_crud.change_password(session, "u1", "WRONG", "newpw456")

    async def test_change_password_sso_user_rejected(self, session):
        from fastapi import HTTPException

        from core.models.user import User

        user = User(id="u1", email="a@b", full_name="A", hashed_password=None)  # SSO-only
        session.execute.return_value = _one_or_none(user)
        with pytest.raises(HTTPException) as exc:
            await users_crud.change_password(session, "u1", "x", "y")
        assert exc.value.status_code == 400

    async def test_change_password_user_not_found(self, session):
        session.execute.return_value = _one_or_none(None)
        with pytest.raises(NotFoundError):
            await users_crud.change_password(session, "missing", "x", "y")

    async def test_list_and_count_users_with_org_filter(self, session):
        from core.models.user import User

        session.execute.side_effect = [
            _scalars_all([User(id="u1", email="a@b", full_name="A", org_id="o1")]),
            _scalar_one(1),
        ]
        users = await users_crud.list_users(session, org_id="o1")
        count = await users_crud.count_users(session, org_id="o1")
        assert len(users) == 1 and count == 1
