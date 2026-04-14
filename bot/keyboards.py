from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.youtube import StreamInfo


def tracks_keyboard(streams: list[StreamInfo]) -> InlineKeyboardMarkup:
    """Build inline keyboard with one button per unique audio language/track."""
    builder = InlineKeyboardBuilder()
    seen_languages: set[str | None] = set()
    for s in streams:
        if s.language not in seen_languages:
            seen_languages.add(s.language)
            label = s.language if s.language else "Default"
            builder.button(
                text=label,
                callback_data=f"track:{label}",
            )
    builder.adjust(1)
    return builder.as_markup()


def bitrate_keyboard(streams: list[StreamInfo]) -> InlineKeyboardMarkup:
    """Build inline keyboard with one button per bitrate option plus a 'Best quality' button."""
    builder = InlineKeyboardBuilder()
    # "Best quality" button first — uses highest bitrate stream
    best = max(streams, key=lambda s: int(s.abr.replace("kbps", "")))
    builder.button(
        text=f"Best quality ({best.abr}, {best.size_mb:.1f} MB)",
        callback_data="bitrate:best",
    )
    for s in streams:
        builder.button(
            text=f"{s.abr} ({s.size_mb:.1f} MB)",
            callback_data=f"bitrate:{s.itag}",
        )
    builder.adjust(1)
    return builder.as_markup()
