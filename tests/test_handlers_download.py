import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.handlers.download import on_url, on_track_selected, on_bitrate_selected, unknown_command
from bot.states import DownloadStates
from core.config import Settings
from services.youtube import StreamInfo
from storage.database import init_db
from storage.repository import UserRepository


@pytest.fixture
def settings(test_env):
    return Settings()


@pytest_asyncio.fixture
async def repo(settings):
    await init_db(settings.db_path)
    return UserRepository(settings.db_path)


def make_user(user_id: int = 123, username: str = "testuser") -> User:
    return User(id=user_id, is_bot=False, first_name="Test", username=username)


def make_message(user: User | None = None, text: str = "https://youtube.com/watch?v=abc") -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = user or make_user()
    msg.text = text
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    # answer returns a message mock that supports edit_text
    resp_msg = MagicMock()
    resp_msg.edit_text = AsyncMock()
    msg.answer.return_value = resp_msg
    return msg


def make_callback(user: User | None = None, data: str = "track:Default") -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = user or make_user()
    cb.data = data
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.answer_audio = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def make_state(state_name=None, data=None) -> MagicMock:
    st = MagicMock(spec=FSMContext)
    st.get_data = AsyncMock(return_value=data or {})
    st.set_data = AsyncMock()
    st.set_state = AsyncMock()
    st.clear = AsyncMock()
    st.get_state = AsyncMock(return_value=state_name)
    return st


def make_bot() -> MagicMock:
    b = MagicMock()
    b.send_message = AsyncMock()
    return b


SAMPLE_STREAMS = [
    StreamInfo(itag=140, language=None, abr="128kbps", size_mb=5.0),
    StreamInfo(itag=251, language=None, abr="160kbps", size_mb=7.0),
]

MULTI_LANG_STREAMS = [
    StreamInfo(itag=140, language="English", abr="128kbps", size_mb=5.0),
    StreamInfo(itag=251, language="English", abr="160kbps", size_mb=7.0),
    StreamInfo(itag=300, language="Spanish", abr="128kbps", size_mb=5.0),
]


class TestUnknownCommand:
    @pytest.mark.asyncio
    async def test_unknown_command_replies(self):
        msg = make_message(text="/foobar")
        await unknown_command(msg)
        msg.answer.assert_called_once()
        assert "Unknown command" in msg.answer.call_args[0][0]


class TestOnUrl:
    @pytest.mark.asyncio
    async def test_invalid_url_replies_error(self, repo, settings):
        msg = make_message(text="not a url")
        state = make_state()
        bot = make_bot()

        with patch.object(
            YoutubeService := __import__("services.youtube", fromlist=["YoutubeService"]).YoutubeService,
            "validate_url",
            return_value=None,
        ):
            await on_url(msg, state, repo, settings, bot)

        msg.reply.assert_called_once()
        assert "valid YouTube" in msg.reply.call_args[0][0]

    @pytest.mark.asyncio
    async def test_valid_url_single_lang_shows_bitrate_keyboard(self, repo, settings):
        msg = make_message(text="https://youtube.com/watch?v=abc")
        state = make_state()
        bot = make_bot()

        with patch(
            "bot.handlers.download.YoutubeService"
        ) as mock_yt:
            mock_yt.validate_url.return_value = "abc"
            mock_yt.async_get_available_streams = AsyncMock(
                return_value=("Test Title", 120.0, SAMPLE_STREAMS)
            )
            await on_url(msg, state, repo, settings, bot)

        # Should show bitrate keyboard (single language)
        resp = msg.answer.return_value
        resp.edit_text.assert_called()
        last_call = resp.edit_text.call_args_list[-1]
        assert "bitrate" in last_call[0][0].lower() or "Choose bitrate" in last_call[0][0]
        assert last_call[1]["reply_markup"] is not None
        state.set_state.assert_called_with(DownloadStates.choosing_bitrate)

    @pytest.mark.asyncio
    async def test_valid_url_multi_lang_shows_track_keyboard(self, repo, settings):
        msg = make_message(text="https://youtube.com/watch?v=abc")
        state = make_state()
        bot = make_bot()

        with patch(
            "bot.handlers.download.YoutubeService"
        ) as mock_yt:
            mock_yt.validate_url.return_value = "abc"
            mock_yt.async_get_available_streams = AsyncMock(
                return_value=("Test Title", 120.0, MULTI_LANG_STREAMS)
            )
            await on_url(msg, state, repo, settings, bot)

        resp = msg.answer.return_value
        resp.edit_text.assert_called()
        last_call = resp.edit_text.call_args_list[-1]
        assert "Choose audio track" in last_call[0][0]
        state.set_state.assert_called_with(DownloadStates.choosing_track)

    @pytest.mark.asyncio
    async def test_stream_fetch_failure_notifies_user_and_admin(self, repo, settings):
        msg = make_message(text="https://youtube.com/watch?v=abc")
        state = make_state()
        bot = make_bot()

        with patch(
            "bot.handlers.download.YoutubeService"
        ) as mock_yt:
            mock_yt.validate_url.return_value = "abc"
            mock_yt.async_get_available_streams = AsyncMock(
                side_effect=Exception("network error")
            )
            await on_url(msg, state, repo, settings, bot)

        resp = msg.answer.return_value
        resp.edit_text.assert_called()
        assert "Failed" in resp.edit_text.call_args[0][0]
        bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_user_returns_early(self, repo, settings):
        msg = make_message()
        msg.from_user = None
        state = make_state()
        bot = make_bot()

        with patch("bot.handlers.download.YoutubeService"):
            await on_url(msg, state, repo, settings, bot)

        msg.answer.assert_not_called()
        msg.reply.assert_not_called()


class TestOnTrackSelected:
    @pytest.mark.asyncio
    async def test_track_selection_filters_streams(self):
        stream_dicts = [
            {"itag": 140, "language": "English", "abr": "128kbps", "size_mb": 5.0},
            {"itag": 251, "language": "English", "abr": "160kbps", "size_mb": 7.0},
            {"itag": 300, "language": "Spanish", "abr": "128kbps", "size_mb": 5.0},
        ]
        state = make_state(data={
            "url": "https://youtube.com/watch?v=abc",
            "video_id": "abc",
            "title": "Test",
            "duration_sec": 120.0,
            "streams": stream_dicts,
            "track_languages": ["English", "Spanish"],
            "created_at": 1000.0,
        })
        cb = make_callback(data="track:0")

        await on_track_selected(cb, state)

        # Should transition to choosing_bitrate
        state.set_state.assert_called_with(DownloadStates.choosing_bitrate)
        cb.message.edit_text.assert_called_once()
        assert "Choose bitrate" in cb.message.edit_text.call_args[0][0]
        cb.answer.assert_called_once()

        # Check that state was updated with filtered streams
        saved_data = state.set_data.call_args[0][0]
        saved_streams = saved_data["streams"]
        assert len(saved_streams) == 2
        assert all(s["language"] == "English" for s in saved_streams)

    @pytest.mark.asyncio
    async def test_track_default_filters_none_language(self):
        stream_dicts = [
            {"itag": 140, "language": None, "abr": "128kbps", "size_mb": 5.0},
            {"itag": 300, "language": "Spanish", "abr": "128kbps", "size_mb": 5.0},
        ]
        state = make_state(data={
            "url": "https://youtube.com/watch?v=abc",
            "video_id": "abc",
            "title": "Test",
            "duration_sec": 120.0,
            "streams": stream_dicts,
            "track_languages": [None, "Spanish"],
            "created_at": 1000.0,
        })
        cb = make_callback(data="track:0")

        await on_track_selected(cb, state)

        saved_data = state.set_data.call_args[0][0]
        assert len(saved_data["streams"]) == 1
        assert saved_data["streams"][0]["language"] is None


class TestOnBitrateSelected:
    @pytest.mark.asyncio
    async def test_bitrate_best_downloads_highest(self, repo, settings, tmp_path):
        stream_dicts = [
            {"itag": 140, "language": None, "abr": "128kbps", "size_mb": 5.0},
            {"itag": 251, "language": None, "abr": "160kbps", "size_mb": 7.0},
        ]
        state = make_state(data={
            "url": "https://youtube.com/watch?v=abc",
            "video_id": "abc",
            "title": "Test",
            "duration_sec": 120.0,
            "streams": stream_dicts,
            "created_at": 1000.0,
        })
        cb = make_callback(data="bitrate:best")
        bot = make_bot()

        # Create a fake downloaded file
        fake_file = tmp_path / "audio.m4a"
        fake_file.write_bytes(b"x" * 1000)

        with patch(
            "bot.handlers.download.YoutubeService"
        ) as mock_yt, patch(
            "bot.handlers.download.async_prepare_files_to_send",
            new_callable=AsyncMock,
            return_value=[fake_file],
        ):
            mock_yt.async_download_by_itag = AsyncMock(return_value=fake_file)
            await on_bitrate_selected(cb, state, repo, settings, bot)

        # Should download itag 251 (best = 160kbps)
        mock_yt.async_download_by_itag.assert_called_once()
        call_args = mock_yt.async_download_by_itag.call_args
        assert call_args[0][1] == 251  # itag

        # Should send audio
        cb.message.answer_audio.assert_called_once()
        # Should log usage
        stats = await repo.get_stats()
        assert stats["total_downloads"] == 1
        # Should clear state
        state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_bitrate_specific_itag(self, repo, settings, tmp_path):
        stream_dicts = [
            {"itag": 140, "language": None, "abr": "128kbps", "size_mb": 5.0},
        ]
        state = make_state(data={
            "url": "https://youtube.com/watch?v=abc",
            "video_id": "abc",
            "title": "Test",
            "duration_sec": 120.0,
            "streams": stream_dicts,
            "created_at": 1000.0,
        })
        cb = make_callback(data="bitrate:140")
        bot = make_bot()

        fake_file = tmp_path / "audio.m4a"
        fake_file.write_bytes(b"x" * 1000)

        with patch(
            "bot.handlers.download.YoutubeService"
        ) as mock_yt, patch(
            "bot.handlers.download.async_prepare_files_to_send",
            new_callable=AsyncMock,
            return_value=[fake_file],
        ):
            mock_yt.async_download_by_itag = AsyncMock(return_value=fake_file)
            await on_bitrate_selected(cb, state, repo, settings, bot)

        call_args = mock_yt.async_download_by_itag.call_args
        assert call_args[0][1] == 140

    @pytest.mark.asyncio
    async def test_download_failure_notifies_user_and_admin(self, repo, settings):
        stream_dicts = [
            {"itag": 140, "language": None, "abr": "128kbps", "size_mb": 5.0},
        ]
        state = make_state(data={
            "url": "https://youtube.com/watch?v=abc",
            "video_id": "abc",
            "title": "Test",
            "duration_sec": 120.0,
            "streams": stream_dicts,
            "created_at": 1000.0,
        })
        cb = make_callback(data="bitrate:140")
        bot = make_bot()

        with patch(
            "bot.handlers.download.YoutubeService"
        ) as mock_yt, patch(
            "bot.handlers.download._cleanup_temp"
        ):
            mock_yt.async_download_by_itag = AsyncMock(
                side_effect=Exception("download error")
            )
            await on_bitrate_selected(cb, state, repo, settings, bot)

        cb.message.edit_text.assert_called()
        last_text = cb.message.edit_text.call_args[0][0]
        assert "failed" in last_text.lower() or "Failed" in last_text
        bot.send_message.assert_called_once()
        state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure_partial(self, repo, settings, tmp_path):
        stream_dicts = [
            {"itag": 140, "language": None, "abr": "128kbps", "size_mb": 5.0},
        ]
        state = make_state(data={
            "url": "https://youtube.com/watch?v=abc",
            "video_id": "abc",
            "title": "Test",
            "duration_sec": 120.0,
            "streams": stream_dicts,
            "created_at": 1000.0,
        })
        cb = make_callback(data="bitrate:140")
        bot = make_bot()

        fake_file = tmp_path / "audio.m4a"
        fake_file.write_bytes(b"x" * 1000)
        fake_chunk1 = tmp_path / "chunk1.m4a"
        fake_chunk1.write_bytes(b"x" * 500)
        fake_chunk2 = tmp_path / "chunk2.m4a"
        fake_chunk2.write_bytes(b"x" * 500)

        cb.message.answer_audio = AsyncMock(side_effect=[None, Exception("send error")])

        with patch(
            "bot.handlers.download.YoutubeService"
        ) as mock_yt, patch(
            "bot.handlers.download.async_prepare_files_to_send",
            new_callable=AsyncMock,
            return_value=[fake_chunk1, fake_chunk2],
        ):
            mock_yt.async_download_by_itag = AsyncMock(return_value=fake_file)
            await on_bitrate_selected(cb, state, repo, settings, bot)

        # Should report partial failure
        last_text = cb.message.edit_text.call_args[0][0]
        assert "failed" in last_text.lower()
        bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_usage_logged_on_success(self, repo, settings, tmp_path):
        await repo.add_user(123, "testuser")
        stream_dicts = [
            {"itag": 140, "language": None, "abr": "128kbps", "size_mb": 5.0},
        ]
        state = make_state(data={
            "url": "https://youtube.com/watch?v=abc",
            "video_id": "abc",
            "title": "Test",
            "duration_sec": 120.0,
            "streams": stream_dicts,
            "created_at": 1000.0,
        })
        cb = make_callback(data="bitrate:140")
        bot = make_bot()

        fake_file = tmp_path / "audio.m4a"
        fake_file.write_bytes(b"x" * 1000)

        with patch(
            "bot.handlers.download.YoutubeService"
        ) as mock_yt, patch(
            "bot.handlers.download.async_prepare_files_to_send",
            new_callable=AsyncMock,
            return_value=[fake_file],
        ):
            mock_yt.async_download_by_itag = AsyncMock(return_value=fake_file)
            await on_bitrate_selected(cb, state, repo, settings, bot)

        stats = await repo.get_stats()
        assert stats["total_downloads"] == 1
