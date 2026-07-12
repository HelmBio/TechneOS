"""Tests for notification service CRUD operations."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import AlreadyExistsError, NotFoundError


class TestNotificationCRUD:
    """Tests for notification_service.crud.notifications."""

    async def test_get_notification_found(self, mock_session):
        from notification_service.crud.notifications import get_notification

        mock_notif = MagicMock(id="n1", title="Test")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_notif
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await get_notification(mock_session, "n1")
        assert result.id == "n1"

    async def test_get_notification_not_found(self, mock_session):
        from notification_service.crud.notifications import get_notification

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await get_notification(mock_session, "missing")

    async def test_create_notification(self, mock_session):
        from core.schemas.notification import NotificationCreate
        from notification_service.crud.notifications import create_notification

        data = NotificationCreate(
            user_id="u1",
            title="New Tool",
            message="A new tool was created",
            category="tool",
            source_type="tool",
            source_id="t1",
        )
        result = await create_notification(mock_session, data)
        assert result.user_id == "u1"
        assert result.title == "New Tool"
        assert result.is_read is False
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    async def test_create_bulk_notifications(self, mock_session):
        from core.schemas.notification import NotificationCreate
        from notification_service.crud.notifications import create_bulk_notifications

        notifications = [
            NotificationCreate(
                user_id=f"u{i}",
                title="Bulk",
                message="msg",
                category="tool",
                source_type="tool",
                source_id="t1",
            )
            for i in range(3)
        ]
        count = await create_bulk_notifications(mock_session, notifications)
        assert count == 3
        assert mock_session.add.call_count == 3

    async def test_unread_count(self, mock_session):
        from notification_service.crud.notifications import unread_count

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 5
        mock_session.execute = AsyncMock(return_value=mock_result)

        count = await unread_count(mock_session, "u1")
        assert count == 5

    async def test_mark_read(self, mock_session):
        from notification_service.crud.notifications import mark_read

        mock_notif = MagicMock(id="n1", is_read=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_notif
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await mark_read(mock_session, "n1")
        assert result.is_read is True

    async def test_mark_all_read(self, mock_session):
        from notification_service.crud.notifications import mark_all_read

        mock_result = MagicMock()
        mock_result.rowcount = 7
        mock_session.execute = AsyncMock(return_value=mock_result)

        count = await mark_all_read(mock_session, "u1")
        assert count == 7

    async def test_list_notifications(self, mock_session):
        from notification_service.crud.notifications import list_notifications

        mock_notif = MagicMock()
        # First call: count query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        # Second call: items query
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = [mock_notif, mock_notif]

        mock_session.execute = AsyncMock(side_effect=[count_result, items_result])

        items, total = await list_notifications(mock_session, "u1")
        assert total == 2
        assert len(items) == 2


class TestSubscriptionCRUD:
    """Tests for notification_service.crud.subscriptions."""

    async def test_get_subscription_found(self, mock_session):
        from notification_service.crud.subscriptions import get_subscription

        mock_sub = MagicMock(id="s1")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sub
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await get_subscription(mock_session, "s1")
        assert result.id == "s1"

    async def test_get_subscription_not_found(self, mock_session):
        from notification_service.crud.subscriptions import get_subscription

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await get_subscription(mock_session, "missing")

    async def test_create_subscription_success(self, mock_session):
        from core.schemas.notification import SubscriptionCreate
        from notification_service.crud.subscriptions import create_subscription

        # check_subscription returns None (no existing)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = SubscriptionCreate(resource_type="tool", resource_id="t1")
        result = await create_subscription(mock_session, "u1", data)
        assert result.user_id == "u1"
        assert result.resource_type == "tool"
        mock_session.add.assert_called_once()

    async def test_create_subscription_duplicate_raises(self, mock_session):
        from core.schemas.notification import SubscriptionCreate
        from notification_service.crud.subscriptions import create_subscription

        existing = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = SubscriptionCreate(resource_type="tool", resource_id="t1")
        with pytest.raises(AlreadyExistsError):
            await create_subscription(mock_session, "u1", data)

    async def test_delete_subscription(self, mock_session):
        from notification_service.crud.subscriptions import delete_subscription

        mock_sub = MagicMock(id="s1")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sub
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.delete = AsyncMock()

        await delete_subscription(mock_session, "s1")
        mock_session.delete.assert_called_once_with(mock_sub)

    async def test_get_subscribers_deduplicates(self, mock_session):
        from notification_service.crud.subscriptions import get_subscribers

        # Two subs: one specific, one wildcard, same user
        sub_specific = MagicMock(user_id="u1", resource_id="t1")
        sub_wildcard = MagicMock(user_id="u1", resource_id="*")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sub_specific, sub_wildcard]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await get_subscribers(mock_session, "tool", "t1")
        assert len(result) == 1
        # Prefer specific over wildcard
        assert result[0].resource_id == "t1"
