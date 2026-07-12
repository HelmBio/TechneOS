"""Tests for the idempotent Platform Assistant seed."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from platform_assistant.seed import ensure_platform_assistant


def _result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


class TestEnsurePlatformAssistant:
    async def test_skips_when_already_present(self):
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock(return_value=_result(MagicMock()))  # existing platform agent
        created = await ensure_platform_assistant(session)
        assert created is False
        session.add.assert_not_called()

    async def test_creates_when_missing(self):
        admin = MagicMock(id="admin-1", org_id="org-1")
        session = AsyncMock()
        session.add = MagicMock()
        # 1st execute: no existing platform agent; 2nd: the admin user
        session.execute = AsyncMock(side_effect=[_result(None), _result(admin)])
        created = await ensure_platform_assistant(session)
        assert created is True
        session.add.assert_called_once()
        agent = session.add.call_args[0][0]
        assert agent.slug == "platform-assistant"
        assert agent.is_platform is True
        assert agent.org_id == "org-1" and agent.created_by == "admin-1"

    async def test_skips_when_no_admin_yet(self):
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock(side_effect=[_result(None), _result(None)])  # no agent, no admin
        created = await ensure_platform_assistant(session)
        assert created is False
        session.add.assert_not_called()
