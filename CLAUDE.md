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

- **Client chain**: both stream discovery and download walk WEB → TV → ANDROID_VR (`FALLBACK_CLIENTS`), taking the first client that answers. WEB leads because only it exposes dubbed/localized tracks; its SABR streams are constructed manually from `vid_info` to bypass cipher issues. No single client is reliable on its own — YouTube intermittently answers `LOGIN_REQUIRED` ("not a bot") to whichever one it likes, hence the chain and the one retry on `BotDetection`. The two fallbacks are not interchangeable either: ANDROID_VR carries itag 139, TV carries 250.
- **Client refusal vs. video verdict**: `_is_about_the_video` splits them. Refusals (`CLIENT_REFUSALS` — bot check, login, po_token) mean the next client is worth trying; anything else under `VideoUnavailable` describes the video (live, private, removed) and aborts the chain, so a later client's bot check cannot bury the real reason.
- **Live URLs**: an ongoing broadcast and a recording YouTube hasn't processed yet both carry formats without `approxDurationMs`, which `Stream()` rejects — leaving zero audio streams rather than an error. `_get_streams_web_client` therefore calls `check_availability()` on an empty result to surface YouTube's own verdict (`LiveStreamError` while live, `LiveStreamEnded` right after). The handler answers both without alerting the admin.
- **Loudness variants**: YouTube ships each itag several times per language (original plus DRC / "vb", told apart by `isDrc`/`xtags`). Only the original is surfaced, per `(itag, language)` — see `_is_redundant`, which runs before `StreamInfo` is built because reading `filesize` costs a request.
- **Stateless service**: All `YoutubeService` methods are `@staticmethod` - no instance state. SABR streams are reconstructed from `vid_info` at download time.
- **Async wrappers**: Sync pytubefix calls are wrapped with `asyncio.to_thread()` for use in the async bot.

## Testing

- Tests mock pytubefix internals (`YouTube`, `extract`, `Stream`) to avoid network calls
- Test files: `tests/test_youtube_service.py`, `tests/test_handlers_download.py`
