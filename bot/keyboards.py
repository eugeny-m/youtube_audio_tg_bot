import re

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.youtube import StreamInfo


def parse_abr(abr: str | None) -> int:
    """Extract numeric bitrate from abr string like '128kbps'. Returns 0 on failure."""
    if not abr:
        return 0
    match = re.search(r"\d+", abr)
    return int(match.group()) if match else 0


def tracks_keyboard(streams: list[StreamInfo]) -> InlineKeyboardMarkup:
    """Build inline keyboard with one button per unique audio language/track.

    Uses index-based callback_data to avoid exceeding Telegram's 64-byte limit
    with long non-ASCII track names.
    """
    builder = InlineKeyboardBuilder()
    seen_languages: dict[str | None, int] = {}
    idx = 0
    for s in streams:
        if s.language not in seen_languages:
            seen_languages[s.language] = idx
            label = s.language if s.language else "Default"
            builder.button(
                text=label,
                callback_data=f"track:{idx}",
            )
            idx += 1
    builder.adjust(1)
    return builder.as_markup()


def get_track_languages(streams: list[StreamInfo]) -> list[str | None]:
    """Return ordered list of unique languages from streams (for index-based track selection)."""
    seen: set[str | None] = set()
    result: list[str | None] = []
    for s in streams:
        if s.language not in seen:
            seen.add(s.language)
            result.append(s.language)
    return result


def bitrate_keyboard(streams: list[StreamInfo]) -> InlineKeyboardMarkup:
    """Build inline keyboard with one button per bitrate option plus a 'Best quality' button."""
    if not streams:
        builder = InlineKeyboardBuilder()
        builder.adjust(1)
        return builder.as_markup()
    builder = InlineKeyboardBuilder()
    # "Best quality" button first — uses highest bitrate stream
    best = max(streams, key=lambda s: parse_abr(s.abr))
    builder.button(
        text=f"Best quality ({best.abr}, {best.size_mb:.1f} MB)",
        callback_data="bitrate:best",
    )
    for s in streams:
        if s.itag == best.itag:
            continue
        builder.button(
            text=f"{s.abr} ({s.size_mb:.1f} MB)",
            callback_data=f"bitrate:{s.itag}",
        )
    builder.adjust(1)
    return builder.as_markup()
