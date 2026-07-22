import html
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from pytubefix.exceptions import LiveStreamEnded

from bot.keyboards import bitrate_keyboard, get_track_languages, parse_abr, tracks_keyboard
from bot.states import DownloadStates
from core.config import Settings
from services.audio import async_prepare_files_to_send
from services.youtube import StreamInfo, YoutubeService
from storage.repository import UserRepository

logger = logging.getLogger(__name__)

router = Router(name="download")


@router.message(F.text.startswith("/"), StateFilter(None))
async def unknown_command(message: Message) -> None:
    """Handle unknown slash commands."""
    await message.answer("Unknown command.")


@router.message(F.text, StateFilter(DownloadStates.choosing_track, DownloadStates.choosing_bitrate))
async def on_url_during_fsm(message: Message, state: FSMContext) -> None:
    """Handle text messages while user is in a download flow - cancel and ask to resend."""
    await state.clear()
    await message.answer("Previous selection cancelled. Please send the link again.")


@router.message(F.text, StateFilter(None))
async def on_url(
    message: Message,
    state: FSMContext,
    repo: UserRepository,
    settings: Settings,
    bot: Bot,
) -> None:
    """Handle incoming text message — validate as YouTube URL and start download flow."""
    url = message.text.strip()
    user = message.from_user
    if user is None:
        return

    video_id = YoutubeService.validate_url(url)
    if video_id is None:
        await message.reply("Please send a valid YouTube video link.")
        return

    logger.info("url_received", extra={"user_id": user.id, "video_id": video_id})

    # Ensure user is registered (idempotent) even if they skipped /start
    await repo.add_user(user.id, user.username)

    resp = await message.answer("Fetching available audio tracks...")

    try:
        title, duration_sec, streams = await YoutubeService.async_get_available_streams(url)
    except LiveStreamEnded:
        # Expected, user-facing situation — not a bot error, so don't alert the admin.
        logger.info("live_stream_ended", extra={"video_id": video_id})
        await resp.edit_text(
            "This looks like a live stream that just ended. YouTube is still "
            "processing the recording — please try again later."
        )
        return
    except Exception as e:
        logger.error("get_streams_failed", extra={"video_id": video_id, "error": str(e)})
        await resp.edit_text("Failed to fetch audio tracks. Please try again.")
        if settings.tg_superuser:
            await bot.send_message(
                chat_id=settings.tg_superuser,
                text=f"Error fetching streams for {html.escape(url)}: {html.escape(str(e))}",
            )
        return

    # Store state data for FSM flow
    stream_dicts = [
        {"itag": s.itag, "language": s.language, "abr": s.abr, "size_mb": s.size_mb}
        for s in streams
    ]
    track_languages = get_track_languages(streams)
    await state.set_data({
        "created_at": datetime.now(timezone.utc).timestamp(),
        "url": url,
        "video_id": video_id,
        "title": title,
        "duration_sec": duration_sec,
        "streams": stream_dicts,
        "track_languages": track_languages,
    })

    # Check if there are multiple languages — if so, show track selection
    languages = {s.language for s in streams}
    safe_title = html.escape(title)
    if len(languages) > 1:
        await resp.edit_text(
            f"{safe_title}\nChoose audio track:",
            reply_markup=tracks_keyboard(streams),
        )
        await state.set_state(DownloadStates.choosing_track)
    else:
        # Single language — skip to bitrate selection
        await resp.edit_text(
            f"{safe_title}\nChoose bitrate:",
            reply_markup=bitrate_keyboard(streams),
        )
        await state.set_state(DownloadStates.choosing_bitrate)


@router.callback_query(DownloadStates.choosing_track, F.data.startswith("track:"))
async def on_track_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle track (language) selection — filter streams and show bitrate keyboard."""
    if not isinstance(callback.message, Message):
        await callback.answer("Message expired.")
        return
    track_idx_str = callback.data.split(":", 1)[1]
    data = await state.get_data()

    try:
        track_idx = int(track_idx_str)
    except ValueError:
        await callback.message.edit_text("Invalid selection.")
        await callback.answer()
        await state.clear()
        return

    track_languages = data.get("track_languages", [])
    if track_idx < 0 or track_idx >= len(track_languages):
        await callback.message.edit_text("Invalid selection.")
        await callback.answer()
        await state.clear()
        return

    selected_language = track_languages[track_idx]
    streams = [StreamInfo(**s) for s in data["streams"]]
    # Filter by selected language
    filtered = [s for s in streams if s.language == selected_language]

    if not filtered:
        filtered = streams  # fallback to all if filter yields nothing

    # Update streams in state to the filtered set
    data["streams"] = [
        {"itag": s.itag, "language": s.language, "abr": s.abr, "size_mb": s.size_mb}
        for s in filtered
    ]
    await state.set_data(data)

    await callback.message.edit_text(
        f"{html.escape(data['title'])}\nChoose bitrate:",
        reply_markup=bitrate_keyboard(filtered),
    )
    await state.set_state(DownloadStates.choosing_bitrate)
    await callback.answer()


@router.callback_query(DownloadStates.choosing_bitrate, F.data.startswith("bitrate:"))
async def on_bitrate_selected(
    callback: CallbackQuery,
    state: FSMContext,
    repo: UserRepository,
    settings: Settings,
    bot: Bot,
) -> None:
    """Handle bitrate selection — download audio, split if needed, send files."""
    if not isinstance(callback.message, Message):
        await callback.answer("Message expired.")
        return
    choice = callback.data.split(":", 1)[1]
    data = await state.get_data()
    url = data["url"]
    video_id = data["video_id"]
    streams = [StreamInfo(**s) for s in data["streams"]]
    user = callback.from_user

    # Determine which itag to download
    if choice == "best":
        best = max(streams, key=lambda s: parse_abr(s.abr))
        itag = best.itag
    else:
        try:
            itag = int(choice)
        except ValueError:
            await callback.message.edit_text("Invalid selection.")
            await callback.answer()
            await state.clear()
            return

    logger.info("download_started", extra={
        "user_id": user.id, "video_id": video_id, "itag": itag,
    })

    unique_id = uuid.uuid4().hex[:8]
    safe_video_id = re.sub(r'[^a-zA-Z0-9_-]', '', video_id)
    temp_dir = settings.temp_download_dir / f"dl_{user.id}_{safe_video_id}_{unique_id}"

    try:
        try:
            await callback.message.edit_text("Downloading audio file...")
        except Exception:
            pass
        await callback.answer()
        try:
            file_path = await YoutubeService.async_download_by_itag(url, itag, temp_dir)
        except ValueError as e:
            logger.error("download_failed", extra={"video_id": video_id, "error": str(e)})
            try:
                await callback.message.edit_text(html.escape(str(e)))
            except Exception:
                pass
            if settings.tg_superuser:
                await bot.send_message(
                    chat_id=settings.tg_superuser,
                    text=f"Download error for {html.escape(url)} (itag={itag}): {html.escape(str(e))}",
                )
            return
        except Exception as e:
            logger.error("download_failed", extra={"video_id": video_id, "error": str(e)})
            try:
                await callback.message.edit_text("Download failed. Please try again.")
            except Exception:
                pass
            if settings.tg_superuser:
                await bot.send_message(
                    chat_id=settings.tg_superuser,
                    text=f"Download error for {html.escape(url)} (itag={itag}): {html.escape(str(e))}",
                )
            return

        filesize_mb = file_path.stat().st_size / (1024 * 1024)

        try:
            await callback.message.edit_text("Processing audio file...")
        except Exception:
            pass

        try:
            files_to_send = await async_prepare_files_to_send(
                file_path, filesize_mb, settings.max_audio_file_size_mb,
            )
        except Exception as e:
            logger.error("prepare_failed", extra={"video_id": video_id, "error": str(e)})
            try:
                await callback.message.edit_text("Failed to process audio file.")
            except Exception:
                pass
            return

        # Send audio files
        success = True
        for i, chunk in enumerate(files_to_send, 1):
            try:
                await callback.message.edit_text(
                    f"Sending file {i} of {len(files_to_send)}..."
                )
            except Exception:
                pass  # progress update is non-critical; message may have been deleted
            try:
                await callback.message.answer_audio(FSInputFile(chunk))
            except Exception as e:
                logger.error("send_failed", extra={
                    "video_id": video_id, "chunk": i, "error": str(e),
                })
                success = False
                break

        if success:
            try:
                await callback.message.edit_text("All files sent!")
            except Exception:
                pass
            logger.info("download_completed", extra={"user_id": user.id, "video_id": video_id})
        else:
            try:
                await callback.message.edit_text("Some files failed to send.")
            except Exception:
                pass
            if settings.tg_superuser:
                await bot.send_message(
                    chat_id=settings.tg_superuser,
                    text=f"Error sending files to user {user.id} for {html.escape(url)}",
                )

        # Log usage
        if success:
            try:
                await repo.log_usage(user.id, video_id)
            except Exception as e:
                logger.error("log_usage_failed", extra={
                    "user_id": user.id, "video_id": video_id, "error": str(e),
                })
    finally:
        await state.clear()
        _cleanup_temp(temp_dir)


def _cleanup_temp(temp_dir: Path) -> None:
    """Remove temp directory if it exists."""
    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
    except Exception as e:
        logger.warning("cleanup_failed", extra={"path": str(temp_dir), "error": str(e)})
