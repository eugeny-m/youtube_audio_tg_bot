# Project Overview

Telegram bot for downloading YouTube audio tracks. Built with aiogram 3.x + pytubefix.

## Key Commands

- Run tests: `pytest tests/`
- Run specific test file: `pytest tests/test_youtube_service.py -v`

## Architecture

- `services/youtube.py` - YouTube interaction layer (all `@staticmethod` methods)
- `bot/handlers/download.py` - Telegram bot download handler
- `core/config.py` - Settings via pydantic-settings
- `storage/` - SQLite-based persistence via aiosqlite

## Key Patterns

- **WEB client + SABR streams**: `YoutubeService` uses pytubefix WEB client for stream discovery to find all audio tracks (including dubbed/localized). Falls back to ANDROID_VR client if WEB fails. SABR streams are constructed manually from `vid_info` to bypass cipher issues. Download also uses WEB client SABR reconstruction first, falling back to default client if SABR download fails.
- **Stateless service**: All `YoutubeService` methods are `@staticmethod` - no instance state. SABR streams are reconstructed from `vid_info` at download time.
- **Async wrappers**: Sync pytubefix calls are wrapped with `asyncio.to_thread()` for use in the async bot.

## Testing

- Tests mock pytubefix internals (`YouTube`, `extract`, `Stream`) to avoid network calls
- Test files: `tests/test_youtube_service.py`, `tests/test_handlers_download.py`
