import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.filters import AdminFilter
from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
from bot.middlewares.logging import LoggingMiddleware
from core.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_update(user_id=123, chat_id=456):
    """Create a minimal mock Update with message containing user and chat."""
    from aiogram.types import Update

    user = MagicMock()
    user.id = user_id

    chat = MagicMock()
    chat.id = chat_id

    message = MagicMock()
    message.from_user = user
    message.chat = chat

    update = MagicMock(spec=Update)
    update.message = message
    update.callback_query = None
    update.edited_message = None
    update.inline_query = None
    # Make isinstance check work
    update.__class__ = Update

    return update


def _make_callback_update(user_id=789):
    """Create a mock Update with callback_query (no message)."""
    from aiogram.types import Update

    user = MagicMock()
    user.id = user_id

    callback_query = MagicMock()
    callback_query.from_user = user
    callback_query.chat = None

    update = MagicMock(spec=Update)
    update.message = None
    update.callback_query = callback_query
    update.edited_message = None
    update.inline_query = None
    update.__class__ = Update

    return update


def _make_message(user_id=123):
    """Create a minimal mock Message."""
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
    async def test_logs_user_and_chat_id(self, caplog):
        middleware = LoggingMiddleware()
        handler = AsyncMock(return_value="ok")
        update = _make_update(user_id=111, chat_id=222)

        with caplog.at_level(logging.INFO, logger="bot.middlewares.logging"):
            result = await middleware(handler, update, {})

        assert result == "ok"
        handler.assert_awaited_once_with(update, {})
        assert any("update_received" in r.message for r in caplog.records)
        log_record = next(r for r in caplog.records if "update_received" in r.message)
        assert log_record.user_id == 111
        assert log_record.chat_id == 222

    @pytest.mark.asyncio
    async def test_callback_query_extracts_user_id(self, caplog):
        middleware = LoggingMiddleware()
        handler = AsyncMock(return_value="ok")
        update = _make_callback_update(user_id=789)

        with caplog.at_level(logging.INFO, logger="bot.middlewares.logging"):
            result = await middleware(handler, update, {})

        assert result == "ok"
        log_record = next(r for r in caplog.records if "update_received" in r.message)
        assert log_record.user_id == 789

    @pytest.mark.asyncio
    async def test_handler_still_called_without_user(self):
        middleware = LoggingMiddleware()
        handler = AsyncMock(return_value="ok")

        from aiogram.types import Update
        update = MagicMock(spec=Update)
        update.message = None
        update.callback_query = None
        update.edited_message = None
        update.inline_query = None
        update.__class__ = Update

        result = await middleware(handler, update, {})
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

        event = MagicMock()
        data = {"state": state}

        result = await middleware(handler, event, data)

        assert result == "ok"
        state.clear.assert_awaited_once()
        handler.assert_awaited_once_with(event, data)

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

        event = MagicMock()
        data = {"state": state}

        await middleware(handler, event, data)
        state.clear.assert_awaited_once()


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
