import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.keyboards import bitrate_keyboard, tracks_keyboard
from bot.states import DownloadStates
from core.config import Settings
from services.audio import async_prepare_files_to_send
from services.youtube import StreamInfo, YoutubeService
from storage.repository import UserRepository

logger = logging.getLogger(__name__)

router = Router(name="download")


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    """Handle unknown slash commands."""
    await message.answer("Unknown command.")


@router.message(F.text)
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

    resp = await message.answer("Fetching available audio tracks...")

    try:
        title, duration_sec, streams = await YoutubeService.async_get_available_streams(url)
    except Exception as e:
        logger.error("get_streams_failed", extra={"video_id": video_id, "error": str(e)})
        await resp.edit_text("Failed to fetch audio tracks. Please try again.")
        await bot.send_message(
            chat_id=settings.tg_superuser,
            text=f"Error fetching streams for {url}: {e}",
        )
        return

    # Store state data for FSM flow
    stream_dicts = [
        {"itag": s.itag, "language": s.language, "abr": s.abr, "size_mb": s.size_mb}
        for s in streams
    ]
    await state.set_data({
        "created_at": datetime.now(timezone.utc).timestamp(),
        "url": url,
        "video_id": video_id,
        "title": title,
        "duration_sec": duration_sec,
        "streams": stream_dicts,
    })

    # Check if there are multiple languages — if so, show track selection
    languages = {s.language for s in streams}
    if len(languages) > 1:
        await resp.edit_text(
            f"{title}\nChoose audio track:",
            reply_markup=tracks_keyboard(streams),
        )
        await state.set_state(DownloadStates.choosing_track)
    else:
        # Single language — skip to bitrate selection
        await resp.edit_text(
            f"{title}\nChoose bitrate:",
            reply_markup=bitrate_keyboard(streams),
        )
        await state.set_state(DownloadStates.choosing_bitrate)


@router.callback_query(DownloadStates.choosing_track, F.data.startswith("track:"))
async def on_track_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle track (language) selection — filter streams and show bitrate keyboard."""
    selected_label = callback.data.split(":", 1)[1]
    data = await state.get_data()

    streams = [StreamInfo(**s) for s in data["streams"]]
    # Filter by selected language
    if selected_label == "Default":
        filtered = [s for s in streams if s.language is None]
    else:
        filtered = [s for s in streams if s.language == selected_label]

    if not filtered:
        filtered = streams  # fallback to all if filter yields nothing

    # Update streams in state to the filtered set
    data["streams"] = [
        {"itag": s.itag, "language": s.language, "abr": s.abr, "size_mb": s.size_mb}
        for s in filtered
    ]
    await state.set_data(data)

    await callback.message.edit_text(
        f"{data['title']}\nChoose bitrate:",
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
    choice = callback.data.split(":", 1)[1]
    data = await state.get_data()
    url = data["url"]
    video_id = data["video_id"]
    streams = [StreamInfo(**s) for s in data["streams"]]
    user = callback.from_user

    # Determine which itag to download
    if choice == "best":
        best = max(streams, key=lambda s: int(s.abr.replace("kbps", "")))
        itag = best.itag
    else:
        itag = int(choice)

    logger.info("download_started", extra={
        "user_id": user.id, "video_id": video_id, "itag": itag,
    })

    await callback.message.edit_text("Downloading audio file...")
    await callback.answer()

    temp_dir = settings.temp_download_dir / f"dl_{user.id}_{video_id}"

    try:
        file_path = await YoutubeService.async_download_by_itag(url, itag, temp_dir)
    except Exception as e:
        logger.error("download_failed", extra={"video_id": video_id, "error": str(e)})
        await callback.message.edit_text("Download failed. Please try again.")
        await bot.send_message(
            chat_id=settings.tg_superuser,
            text=f"Download error for {url} (itag={itag}): {e}",
        )
        await state.clear()
        _cleanup_temp(temp_dir)
        return

    filesize_mb = file_path.stat().st_size / (1024 * 1024)

    await callback.message.edit_text("Processing audio file...")

    try:
        files_to_send = await async_prepare_files_to_send(
            file_path, filesize_mb, settings.max_audio_file_size_mb,
        )
    except Exception as e:
        logger.error("prepare_failed", extra={"video_id": video_id, "error": str(e)})
        await callback.message.edit_text("Failed to process audio file.")
        await state.clear()
        _cleanup_temp(temp_dir)
        return

    # Send audio files
    success = True
    for i, chunk in enumerate(files_to_send, 1):
        await callback.message.edit_text(
            f"Sending file {i} of {len(files_to_send)}..."
        )
        try:
            await callback.message.answer_audio(FSInputFile(chunk))
        except Exception as e:
            logger.error("send_failed", extra={
                "video_id": video_id, "chunk": i, "error": str(e),
            })
            success = False
            break

    if success:
        await callback.message.edit_text("All files sent!")
        logger.info("download_completed", extra={"user_id": user.id, "video_id": video_id})
    else:
        await callback.message.edit_text("Some files failed to send.")
        await bot.send_message(
            chat_id=settings.tg_superuser,
            text=f"Error sending files to user {user.id} for {url}",
        )

    # Log usage and cleanup
    await repo.log_usage(user.id, video_id)
    await state.clear()
    _cleanup_temp(temp_dir)


def _cleanup_temp(temp_dir: Path) -> None:
    """Remove temp directory if it exists."""
    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
    except Exception as e:
        logger.warning("cleanup_failed", extra={"path": str(temp_dir), "error": str(e)})
