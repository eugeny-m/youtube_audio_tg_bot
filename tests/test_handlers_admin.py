import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Message, CallbackQuery, User

from core.config import Settings
from storage.database import init_db
from storage.repository import UserRepository
from bot.handlers.start import cmd_start
from bot.handlers.admin import (
    cmd_admin,
    on_stats,
    on_top_users,
    on_weekly,
    create_admin_router,
)
from bot.filters import AdminFilter


@pytest.fixture
def settings(test_env):
    return Settings()


@pytest_asyncio.fixture
async def repo(settings):
    await init_db(settings.db_path)
    return UserRepository(settings.db_path)


def make_user(user_id: int = 123, username: str = "testuser") -> User:
    return User(id=user_id, is_bot=False, first_name="Test", username=username)


def make_message(user: User | None = None, text: str = "/start") -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = user or make_user()
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def make_callback(user: User | None = None, data: str = "admin:stats") -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = user or make_user()
    cb.data = data
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


# --- Start handler tests ---


class TestStartHandler:
    @pytest.mark.asyncio
    async def test_start_adds_user_to_db(self, repo):
        user = make_user(user_id=42, username="alice")
        msg = make_message(user=user)

        await cmd_start(msg, repo)

        count = await repo.get_users_count()
        assert count == 1

    @pytest.mark.asyncio
    async def test_start_sends_welcome(self, repo):
        msg = make_message()

        await cmd_start(msg, repo)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "YouTube" in text or "audio" in text

    @pytest.mark.asyncio
    async def test_start_no_user_does_nothing(self, repo):
        msg = make_message()
        msg.from_user = None

        await cmd_start(msg, repo)

        msg.answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_duplicate_user_no_error(self, repo):
        user = make_user(user_id=42)
        msg = make_message(user=user)

        await cmd_start(msg, repo)
        await cmd_start(msg, repo)

        count = await repo.get_users_count()
        assert count == 1


# --- Admin handler tests ---


class TestAdminCmd:
    @pytest.mark.asyncio
    async def test_admin_shows_keyboard(self):
        msg = make_message(text="/admin")

        await cmd_admin(msg)

        msg.answer.assert_called_once()
        call_kwargs = msg.answer.call_args
        assert "Admin Panel" in call_kwargs[0][0]
        assert call_kwargs[1]["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_admin_keyboard_has_three_buttons(self):
        msg = make_message(text="/admin")

        await cmd_admin(msg)

        markup = msg.answer.call_args[1]["reply_markup"]
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert len(buttons) == 3
        callback_datas = {btn.callback_data for btn in buttons}
        assert callback_datas == {"admin:stats", "admin:top_users", "admin:weekly"}


class TestAdminStats:
    @pytest.mark.asyncio
    async def test_stats_shows_counts(self, repo):
        await repo.add_user(1, "alice")
        await repo.add_user(2, "bob")
        await repo.log_usage(1, "vid1")
        await repo.log_usage(1, "vid2")

        cb = make_callback(data="admin:stats")
        await on_stats(cb, repo)

        text = cb.message.edit_text.call_args[0][0]
        assert "Total users: 2" in text
        assert "Active users: 1" in text
        assert "Total downloads: 2" in text
        cb.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_stats_empty_db(self, repo):
        cb = make_callback(data="admin:stats")
        await on_stats(cb, repo)

        text = cb.message.edit_text.call_args[0][0]
        assert "Total users: 0" in text
        assert "Total downloads: 0" in text


class TestAdminTopUsers:
    @pytest.mark.asyncio
    async def test_top_users_ranked(self, repo):
        await repo.add_user(1, "alice")
        await repo.add_user(2, "bob")
        await repo.log_usage(1, "vid1")
        await repo.log_usage(1, "vid2")
        await repo.log_usage(2, "vid1")

        cb = make_callback(data="admin:top_users")
        await on_top_users(cb, repo)

        text = cb.message.edit_text.call_args[0][0]
        assert "1. alice - 2 downloads" in text
        assert "2. bob - 1 downloads" in text

    @pytest.mark.asyncio
    async def test_top_users_empty(self, repo):
        cb = make_callback(data="admin:top_users")
        await on_top_users(cb, repo)

        text = cb.message.edit_text.call_args[0][0]
        assert "No users yet" in text

    @pytest.mark.asyncio
    async def test_top_users_no_username_shows_id(self, repo):
        await repo.add_user(42, None)
        await repo.log_usage(42, "vid1")

        cb = make_callback(data="admin:top_users")
        await on_top_users(cb, repo)

        text = cb.message.edit_text.call_args[0][0]
        assert "42" in text


class TestAdminWeekly:
    @pytest.mark.asyncio
    async def test_weekly_stats(self, repo):
        await repo.add_user(1, "user1")
        await repo.log_usage(1, "vid1")

        cb = make_callback(data="admin:weekly")
        await on_weekly(cb, repo)

        text = cb.message.edit_text.call_args[0][0]
        assert "Downloads: 1" in text
        assert "Active users: 1" in text
        assert "New users: 1" in text
        cb.answer.assert_called_once()


class TestAdminFilter:
    @pytest.mark.asyncio
    async def test_filter_blocks_non_admin(self, settings):
        filt = AdminFilter(settings)
        msg = make_message(user=make_user(user_id=111))
        assert await filt(msg) is False

    @pytest.mark.asyncio
    async def test_filter_passes_admin(self, settings):
        filt = AdminFilter(settings)
        msg = make_message(user=make_user(user_id=999))
        assert await filt(msg) is True

    @pytest.mark.asyncio
    async def test_filter_no_user(self, settings):
        filt = AdminFilter(settings)
        msg = make_message()
        msg.from_user = None
        assert await filt(msg) is False


class TestAdminRouterCreation:
    def test_router_created(self, settings):
        router = create_admin_router(settings)
        assert router.name == "admin"

    def test_router_has_handlers(self, settings):
        router = create_admin_router(settings)
        assert len(router.message.handlers) > 0
        assert len(router.callback_query.handlers) > 0
