import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from bot.filters import AdminFilter
from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
from bot.middlewares.logging import LoggingMiddleware
from core.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message_event(user_id=123, chat_id=456):
    """Create a minimal mock Message for middleware testing."""
    from aiogram.types import Message

    user = MagicMock()
    user.id = user_id

    chat = MagicMock()
    chat.id = chat_id

    message = MagicMock(spec=Message)
    message.from_user = user
    message.chat = chat
    message.__class__ = Message

    return message


def _make_callback_event(user_id=789, chat_id=456):
    """Create a mock CallbackQuery for middleware testing."""
    from aiogram.types import CallbackQuery

    user = MagicMock()
    user.id = user_id

    chat = MagicMock()
    chat.id = chat_id

    inner_message = MagicMock()
    inner_message.chat = chat

    callback_query = MagicMock(spec=CallbackQuery)
    callback_query.from_user = user
    callback_query.message = inner_message
    callback_query.__class__ = CallbackQuery

    return callback_query


def _make_message(user_id=123):
    """Create a minimal mock Message for filter testing."""
    user = MagicMock()
    user.id = user_id

    message = MagicMock()
    message.from_user = user
    return message


# ---------------------------------------------------------------------------
# LoggingMiddleware
# ---------------------------------------------------------------------------

class TestLoggingMiddleware:

    @pytest.mark.asyncio
    async def test_logs_user_and_chat_id_from_message(self, caplog):
        middleware = LoggingMiddleware()
        handler = AsyncMock(return_value="ok")
        message = _make_message_event(user_id=111, chat_id=222)

        with caplog.at_level(logging.INFO, logger="bot.middlewares.logging"):
            result = await middleware(handler, message, {})

        assert result == "ok"
        handler.assert_awaited_once_with(message, {})
        assert any("update_received" in r.message for r in caplog.records)
        log_record = next(r for r in caplog.records if "update_received" in r.message)
        assert log_record.user_id == 111
        assert log_record.chat_id == 222

    @pytest.mark.asyncio
    async def test_callback_query_extracts_user_id(self, caplog):
        middleware = LoggingMiddleware()
        handler = AsyncMock(return_value="ok")
        callback = _make_callback_event(user_id=789, chat_id=456)

        with caplog.at_level(logging.INFO, logger="bot.middlewares.logging"):
            result = await middleware(handler, callback, {})

        assert result == "ok"
        log_record = next(r for r in caplog.records if "update_received" in r.message)
        assert log_record.user_id == 789
        assert log_record.chat_id == 456

    @pytest.mark.asyncio
    async def test_handler_still_called_without_user(self):
        middleware = LoggingMiddleware()
        handler = AsyncMock(return_value="ok")

        # An event that is neither Message nor CallbackQuery
        event = MagicMock()

        result = await middleware(handler, event, {})
        assert result == "ok"
        handler.assert_awaited_once()


# ---------------------------------------------------------------------------
# FSMTimeoutMiddleware
# ---------------------------------------------------------------------------

class TestFSMTimeoutMiddleware:

    @pytest.mark.asyncio
    async def test_expired_state_cleared(self):
        middleware = FSMTimeoutMiddleware(timeout_minutes=10)
        handler = AsyncMock(return_value="ok")

        state = AsyncMock()
        state.get_state = AsyncMock(return_value="DownloadStates:choosing_track")
        # created_at 15 minutes ago
        old_ts = datetime.now(timezone.utc).timestamp() - 15 * 60
        state.get_data = AsyncMock(return_value={"created_at": old_ts})

        event = AsyncMock()
        data = {"state": state}

        result = await middleware(handler, event, data)

        assert result is None
        state.clear.assert_awaited_once()
        handler.assert_not_awaited()
        event.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_expired_callback_query_edits_message(self):
        """When a CallbackQuery expires, it should edit the message text instead of showing a popup."""
        from aiogram.types import CallbackQuery, Message

        middleware = FSMTimeoutMiddleware(timeout_minutes=10)
        handler = AsyncMock(return_value="ok")

        state = AsyncMock()
        state.get_state = AsyncMock(return_value="DownloadStates:choosing_bitrate")
        old_ts = datetime.now(timezone.utc).timestamp() - 15 * 60
        state.get_data = AsyncMock(return_value={"created_at": old_ts})

        # Create a mock CallbackQuery that passes isinstance checks
        mock_message = MagicMock(spec=Message)
        mock_message.edit_text = AsyncMock()
        event = MagicMock(spec=CallbackQuery)
        event.answer = AsyncMock()
        event.message = mock_message

        data = {"state": state}

        result = await middleware(handler, event, data)

        assert result is None
        state.clear.assert_awaited_once()
        handler.assert_not_awaited()
        # Should dismiss the callback popup
        event.answer.assert_awaited_once_with()
        # Should edit the message text (persistent, not a popup)
        mock_message.edit_text.assert_awaited_once_with(
            "Session expired. Please send the link again."
        )

    @pytest.mark.asyncio
    async def test_fresh_state_kept(self):
        middleware = FSMTimeoutMiddleware(timeout_minutes=10)
        handler = AsyncMock(return_value="ok")

        state = AsyncMock()
        state.get_state = AsyncMock(return_value="DownloadStates:choosing_track")
        # created_at 2 minutes ago
        recent_ts = datetime.now(timezone.utc).timestamp() - 2 * 60
        state.get_data = AsyncMock(return_value={"created_at": recent_ts})

        event = MagicMock()
        data = {"state": state}

        result = await middleware(handler, event, data)

        assert result == "ok"
        state.clear.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_state_is_noop(self):
        middleware = FSMTimeoutMiddleware(timeout_minutes=10)
        handler = AsyncMock(return_value="ok")

        state = AsyncMock()
        state.get_state = AsyncMock(return_value=None)

        event = MagicMock()
        data = {"state": state}

        result = await middleware(handler, event, data)

        assert result == "ok"
        state.clear.assert_not_awaited()
        state.get_data.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_state_in_data(self):
        middleware = FSMTimeoutMiddleware(timeout_minutes=10)
        handler = AsyncMock(return_value="ok")

        event = MagicMock()
        data = {}

        result = await middleware(handler, event, data)

        assert result == "ok"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_state_without_created_at_kept(self):
        middleware = FSMTimeoutMiddleware(timeout_minutes=10)
        handler = AsyncMock(return_value="ok")

        state = AsyncMock()
        state.get_state = AsyncMock(return_value="DownloadStates:choosing_track")
        state.get_data = AsyncMock(return_value={"video_id": "abc"})

        event = MagicMock()
        data = {"state": state}

        result = await middleware(handler, event, data)

        assert result == "ok"
        state.clear.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        middleware = FSMTimeoutMiddleware(timeout_minutes=5)
        handler = AsyncMock(return_value="ok")

        state = AsyncMock()
        state.get_state = AsyncMock(return_value="DownloadStates:choosing_track")
        # created_at 6 minutes ago - should expire with 5min timeout
        old_ts = datetime.now(timezone.utc).timestamp() - 6 * 60
        state.get_data = AsyncMock(return_value={"created_at": old_ts})

        event = AsyncMock()
        data = {"state": state}

        result = await middleware(handler, event, data)
        assert result is None
        state.clear.assert_awaited_once()
        handler.assert_not_awaited()


# ---------------------------------------------------------------------------
# AdminFilter
# ---------------------------------------------------------------------------

class TestAdminFilter:

    @pytest.mark.asyncio
    async def test_superuser_passes(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("TG_SUPERUSER", "999")
        settings = Settings()
        filt = AdminFilter(settings)

        message = _make_message(user_id=999)
        assert await filt(message) is True

    @pytest.mark.asyncio
    async def test_non_superuser_rejected(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("TG_SUPERUSER", "999")
        settings = Settings()
        filt = AdminFilter(settings)

        message = _make_message(user_id=123)
        assert await filt(message) is False

    @pytest.mark.asyncio
    async def test_no_user_rejected(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("TG_SUPERUSER", "999")
        settings = Settings()
        filt = AdminFilter(settings)

        message = MagicMock()
        message.from_user = None
        assert await filt(message) is False
