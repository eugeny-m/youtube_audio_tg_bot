# Refactoring YouTube Audio Bot

## Overview
- Refactor monolithic `youtube_bot.py` (333 lines) into modular package structure
- Replace stdlib logging with `python-json-logger` for JSON output in prod + RotatingFileHandler for log rotation
- Replace `os.environ.get()` with pydantic-settings `Settings` class
- Add two-step inline keyboard UX: choose audio track (language) → choose bitrate → download
- Migrate file-based storage (txt) to SQLite via aiosqlite
- Add admin panel with inline buttons (`/admin` command)
- Wrap blocking pytubefix/ffmpeg calls in `asyncio.to_thread()` to keep event loop responsive

## Context (from discovery)
- **Files involved**: `youtube_bot.py` (monolith), `log.py` (logging), `visit_counter.py` (txt storage), `notify_command.py` (one-time script, to delete), `requirements.txt`, `prod.Dockerfile`, `docker-compose.yml`
- **Framework**: aiogram 3.21, pytubefix 9.5, Python 3.12, Docker deployment
- **Current patterns**: static YoutubeService class, singleton visit storage, RotatingFileHandler logging
- **Dependencies to add**: `python-json-logger`, `pydantic-settings`, `aiosqlite`
- **Docker**: `prod.Dockerfile` copies individual files — needs update for package structure
- **Note**: `docker-compose.yml` is in `.gitignore`, prod has its own config. No token leak concern.

## Important Notes
- **Old `youtube_bot.py` remains the working entry point until Task 11 is fully complete.** New modules are developed and tested independently. The switchover happens when `main.py` is wired and verified.
- **FSM timeout is lazy** — stale states are cleaned on the user's next interaction, not proactively in background. Acceptable for this bot's scale.
- **Migration data limitations** — migrated users from txt files will have `username=NULL` and `first_seen_at=migration_timestamp` (txt files don't contain this data).

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run tests after each change

## Testing Strategy
- **Unit tests**: pytest + pytest-asyncio for async code
- **Mocking**: unittest.mock for external services (pytubefix, Telegram API, SQLite)
- **Test structure**: `tests/` directory mirroring `bot/`, `services/`, `core/`, `storage/`
- **Test deps**: add `pytest`, `pytest-asyncio` to dev requirements

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix
- Update plan if implementation deviates from original scope

## Solution Overview

### Target Structure
```
youtube_listener/           # project root (working directory)
├── bot/
│   ├── __init__.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py          # /start command
│   │   ├── admin.py           # /admin with inline buttons
│   │   └── download.py        # URL processing, FSM, callbacks
│   ├── keyboards.py           # InlineKeyboardBuilder helpers
│   ├── states.py              # DownloadStates FSM
│   ├── filters.py             # AdminFilter
│   └── middlewares/
│       ├── __init__.py
│       ├── logging.py         # logging context binding (user_id, chat_id)
│       └── fsm_timeout.py     # FSM state TTL cleanup (lazy, on next interaction)
├── services/
│   ├── __init__.py
│   ├── youtube.py             # YoutubeService (validate, get_streams, download_by_itag)
│   └── audio.py               # split_audio_ffmpeg
├── core/
│   ├── __init__.py
│   ├── config.py              # pydantic-settings Settings
│   └── logging.py             # python-json-logger + RotatingFileHandler setup
├── storage/
│   ├── __init__.py
│   ├── database.py            # init_db(), connection management
│   ├── repository.py          # UserRepository (async SQLite, connection-per-call)
│   └── migration.py           # txt → SQLite one-time import
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # fixtures: test settings, tmp db, bot mocks
│   ├── test_config.py
│   ├── test_logging.py
│   ├── test_youtube_service.py
│   ├── test_audio_service.py
│   ├── test_repository.py
│   ├── test_migration.py
│   ├── test_keyboards.py
│   └── test_handlers.py
├── main.py                    # entry point: create bot, wire routers, start polling
├── requirements.txt
├── requirements-dev.txt       # pytest, pytest-asyncio
├── Dockerfile
├── prod.Dockerfile
└── docker-compose.yml
```

### Key Design Decisions
1. **python-json-logger + stdlib logging**: JSON formatter for prod, standard formatter for debug. RotatingFileHandler handles rotation (5MB x 5 for app.log, 5MB x 3 for error.log). Simpler than structlog, all log calls use stdlib `logging.getLogger()` with key-value style via `extra={}`.
2. **aiogram FSM** for two-step download: `choosing_track` → `choosing_bitrate` → download. State data holds video_id, stream list, and `created_at` timestamp.
3. **FSM timeout middleware**: lazy cleanup — checks `created_at` on next user interaction, clears if >10 minutes old.
4. **callback_data encoding**: `track:<language>` and `bitrate:<itag>` — fits within 64-byte limit.
5. **SQLite tables**: `users` (user_id PK, username, first_seen_at) and `usage_log` (id, user_id FK, video_id, created_at).
6. **Connection-per-call** for SQLite — `UserRepository` opens/closes connection per operation (simplest, avoids "database is locked" under concurrency).
7. **asyncio.to_thread()** for all blocking I/O — pytubefix downloads and ffmpeg subprocess calls run in thread pool, keeping event loop responsive for other users.
8. **StreamInfo dataclass**: `itag`, `language`, `abr`, `size_mb` — used by YoutubeService and keyboards.

## Implementation Steps

### Task 1: Create package skeleton and core/config.py

**Files:**
- Create: `core/__init__.py`, `core/config.py`
- Create: `bot/__init__.py`, `bot/handlers/__init__.py`, `bot/middlewares/__init__.py`
- Create: `services/__init__.py`
- Create: `storage/__init__.py`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`
- Create: `requirements-dev.txt`
- Modify: `requirements.txt`

- [x] Create all `__init__.py` files for package structure
- [x] Create `core/config.py` with `Settings(BaseSettings)` class: `telegram_bot_token`, `tg_superuser`, `bot_proxy`, `bot_username`, `max_audio_file_size_mb`, `temp_download_dir`, `log_level`, `debug`, `log_dir`, `db_path`
- [x] Add `pydantic-settings` to `requirements.txt`
- [x] Create `requirements-dev.txt` with `pytest`, `pytest-asyncio`
- [x] Create `tests/conftest.py` with test settings fixture (env vars override, tmp paths)
- [x] Write `tests/test_config.py`: test default values, env var loading, optional fields
- [x] Run tests — must pass before next task

### Task 2: Setup logging with python-json-logger in core/logging.py

**Files:**
- Create: `core/logging.py`
- Modify: `requirements.txt`
- Create: `tests/test_logging.py`

- [x] Add `python-json-logger` to `requirements.txt`
- [x] Create `core/logging.py` with `setup_logging(settings)` function
- [x] Configure stdlib `logging` with `RotatingFileHandler` for `app.log` (5MB x 5) and `error.log` (5MB x 3) + `StreamHandler`
- [x] Use `pythonjsonlogger.json.JsonFormatter` for file handlers (JSON output)
- [x] Use standard formatter with human-readable output for console handler
- [x] When `debug=True`: set console to DEBUG level with verbose format
- [x] Write `tests/test_logging.py`: verify logger creation, verify handlers attached, verify JSON format in file handler
- [x] Run tests — must pass before next task

### Task 3: Create SQLite storage layer

**Files:**
- Create: `storage/database.py`
- Create: `storage/repository.py`
- Modify: `requirements.txt`
- Create: `tests/test_repository.py`

- [x] Add `aiosqlite` to `requirements.txt`
- [x] Create `storage/database.py` with `init_db(db_path)` — creates `users` and `usage_log` tables (idempotent with IF NOT EXISTS)
- [x] Create `storage/repository.py` with `UserRepository(db_path)` class using connection-per-call pattern:
  - `add_user(user_id, username)` — INSERT OR IGNORE
  - `log_usage(user_id, video_id)` — INSERT into usage_log
  - `get_users_count()` — COUNT from users
  - `get_stats()` — analytics: total users, active users, usage distribution
  - `get_top_users(limit)` — top users by usage count
  - `get_weekly_stats()` — usage in last 7 days
- [x] Write tests for `init_db` (tables created, idempotent re-run)
- [x] Write tests for `UserRepository` methods (add_user, log_usage, get_stats, get_top_users, get_weekly_stats)
- [x] Write tests for edge cases (duplicate user ignored, empty db stats return zeroes)
- [x] Run tests — must pass before next task

### Task 4: Create txt → SQLite migration script

**Files:**
- Create: `storage/migration.py`
- Create: `tests/test_migration.py`

- [x] Create `storage/migration.py` with `migrate_from_txt(db_path, config_dir)`:
  - Read `first_visit_ids.txt` → INSERT into `users` (username=NULL, first_seen_at=migration timestamp)
  - Read `bot_usage.txt` → INSERT into `usage_log` (user_id only, video_id=NULL)
  - Rename source files to `.txt.migrated` after success
  - Idempotent: skip if `.txt` files don't exist or `.txt.migrated` already exists
- [x] Write tests: migration with sample txt data, verify data in SQLite
- [x] Write tests: idempotent re-run (no errors, no duplicates)
- [x] Write tests: missing files handled gracefully
- [x] Run tests — must pass before next task

### Task 5: Extract services/youtube.py with stream listing and async wrapping

**Files:**
- Create: `services/youtube.py`
- Create: `tests/test_youtube_service.py`

- [x] Create `services/youtube.py` with `StreamInfo` dataclass (`itag`, `language`, `abr`, `size_mb`)
- [x] Move `YoutubeService` from `youtube_bot.py` to `services/youtube.py`
- [x] Refactor `validate_video_url` → `validate_url(url) -> str | None` (returns video_id or None)
- [x] Add `get_available_streams(url) -> tuple[str, float, list[StreamInfo]]` — returns (title, duration_sec, list of streams with language/bitrate/size)
- [x] Add `download_by_itag(url, itag, temp_dir) -> Path` — download specific stream by itag
- [x] Keep existing `download_audio` as convenience method (downloads best quality)
- [x] **Wrap all blocking pytubefix calls in `asyncio.to_thread()`**: add async versions `async_get_available_streams`, `async_download_by_itag`, `async_download_audio` that delegate to sync methods via `to_thread`
- [x] Replace `get_logger()` calls with `logging.getLogger(__name__)` and use key-value style: `logger.info("download_started", extra={"video_id": vid, "bitrate": abr})`
- [x] Write tests for `validate_url` (valid/invalid URLs, mock pytubefix.extract)
- [x] Write tests for `get_available_streams` (mock pytubefix.YouTube, verify StreamInfo list)
- [x] Write tests for `download_by_itag` (mock stream.download, verify path returned)
- [x] Run tests — must pass before next task

### Task 6: Extract services/audio.py with async wrapping

**Files:**
- Create: `services/audio.py`
- Create: `tests/test_audio_service.py`

- [x] Move `split_audio_ffmpeg` from `youtube_bot.py` to `services/audio.py`
- [x] Move `prepare_files_to_send` logic to `services/audio.py`
- [x] **Wrap `split_audio_ffmpeg` in `asyncio.to_thread()`**: add `async_split_audio_ffmpeg` and `async_prepare_files_to_send`
- [x] Replace `get_logger()` with `logging.getLogger(__name__)` with key-value style
- [x] Write tests for `split_audio_ffmpeg` (mock subprocess.run, verify chunk paths returned)
- [x] Write tests for `prepare_files_to_send` (under limit: single file, over limit: calls split)
- [x] Run tests — must pass before next task

### Task 7: Create FSM states and keyboards

**Files:**
- Create: `bot/states.py`
- Create: `bot/keyboards.py`
- Create: `tests/test_keyboards.py`

- [x] Create `bot/states.py` with `DownloadStates(StatesGroup)`: `choosing_track`, `choosing_bitrate`
- [x] Create `bot/keyboards.py`:
  - `tracks_keyboard(streams: list[StreamInfo]) -> InlineKeyboardMarkup` — buttons per unique language
  - `bitrate_keyboard(streams: list[StreamInfo]) -> InlineKeyboardMarkup` — buttons per bitrate + "Best quality" button
- [x] Write tests for `tracks_keyboard` (correct buttons generated, unique languages extracted)
- [x] Write tests for `bitrate_keyboard` (correct buttons, size display formatted, "best" option present)
- [x] Run tests — must pass before next task

### Task 8: Create bot middlewares and filters

**Files:**
- Create: `bot/middlewares/logging.py`
- Create: `bot/middlewares/fsm_timeout.py`
- Create: `bot/filters.py`
- Create: `tests/test_middlewares.py`

- [x] Create `bot/middlewares/logging.py` with `LoggingMiddleware`:
  - Adds `user_id` and `chat_id` to log record via `LoggerAdapter` or `extra` context on each update
- [x] Create `bot/middlewares/fsm_timeout.py` with `FSMTimeoutMiddleware(timeout_minutes=10)`:
  - Check `created_at` in state data, clear state if older than timeout
  - Note: lazy cleanup — only triggers on user's next interaction
- [x] Create `bot/filters.py` with `AdminFilter` — checks `from_user.id == settings.tg_superuser`
- [x] Write tests for LoggingMiddleware (context bound correctly)
- [x] Write tests for FSMTimeoutMiddleware (expired state cleared, fresh state kept, no state = no-op)
- [x] Write tests for AdminFilter (superuser passes, others rejected)
- [x] Run tests — must pass before next task

### Task 9: Create bot handlers — start and admin

**Files:**
- Create: `bot/handlers/start.py`
- Create: `bot/handlers/admin.py`
- Create: `tests/test_handlers_admin.py`

- [x] Create `bot/handlers/start.py` with Router:
  - `/start` handler: log user, add to DB via UserRepository, send welcome message
- [x] Create `bot/handlers/admin.py` with Router + AdminFilter:
  - `/admin` handler: show inline keyboard with stats options
  - `admin:stats` callback: total stats from UserRepository
  - `admin:top_users` callback: top 20 users
  - `admin:weekly` callback: last 7 days stats
  - Format stats as readable text in code blocks
- [x] Write tests for start handler (user added to DB, welcome sent)
- [x] Write tests for admin handler (filter works, stats displayed, non-admin rejected)
- [x] Run tests — must pass before next task

### Task 10: Create bot handler — download flow with FSM

**Files:**
- Create: `bot/handlers/download.py`
- Create: `tests/test_handlers_download.py`

- [x] Create `bot/handlers/download.py` with Router:
  - **URL received**: validate URL, call `async_get_available_streams`, save streams + `created_at` to FSM state, send tracks keyboard, set state `choosing_track`
  - **Track callback** (`track:<lang>`): filter streams by language, send bitrate keyboard, set state `choosing_bitrate`
  - **Bitrate callback** (`bitrate:<itag>` or `bitrate:best`): call `async_download_by_itag`, split if needed via `async_prepare_files_to_send`, send audio files, log usage, clear FSM state, cleanup temp dir
  - Handle errors: notify user + admin on download/send failure
  - Handle invalid commands (unknown `/`) gracefully
- [x] Use key-value logging with video_id context throughout
- [x] Write tests for URL validation flow (valid URL → keyboard shown)
- [x] Write tests for track selection callback (filtered streams → bitrate keyboard)
- [x] Write tests for bitrate selection callback (download triggered, files sent)
- [x] Write tests for error handling (download failure → user notified)
- [x] Run tests — must pass before next task

### Task 11: Create main.py entry point and wire everything

**Files:**
- Create: `main.py`

- [x] Create `main.py`:
  - Load `Settings`
  - Call `setup_logging(settings)`
  - Call `init_db(settings.db_path)` (async, at startup)
  - Run `migrate_from_txt` if txt files exist
  - Create `Bot` with optional proxy
  - Create `Dispatcher` with `MemoryStorage`
  - Register middlewares (LoggingMiddleware, FSMTimeoutMiddleware)
  - Include routers from all handler modules
  - Start polling
- [x] Verify `main.py` imports resolve correctly
- [x] Write smoke test: main module imports without error
- [x] Run tests — must pass before next task

### Task 12: Update Docker and deployment files

**Files:**
- Modify: `prod.Dockerfile`
- Modify: `docker-compose.yml`
- Create: `.dockerignore`

- [ ] Update `prod.Dockerfile`: `COPY . /app` instead of individual files, update CMD to `python main.py`
- [ ] Update `docker-compose.yml`: change command to `python main.py`, ensure volume mounts work for `config/` and `logs/`
- [ ] Create `.dockerignore` to exclude: `tests/`, `docs/`, `__pycache__/`, `.git/`, `*.pyc`, `dev_loop.py`, `requirements-dev.txt`
- [ ] Verify docker build succeeds: `docker build -f prod.Dockerfile .`
- [ ] Run tests — must pass before next task

### Task 13: Remove old files and cleanup

**Files:**
- Remove: `youtube_bot.py`
- Remove: `log.py`
- Remove: `visit_counter.py`
- Remove: `notify_command.py`
- Remove: `exp.py`

- [ ] Remove `youtube_bot.py` (all code migrated to new modules)
- [ ] Remove `log.py` (replaced by `core/logging.py`)
- [ ] Remove `visit_counter.py` (replaced by `storage/repository.py`)
- [ ] Remove `notify_command.py` (one-time script, no longer needed)
- [ ] Remove `exp.py` (test/experimentation script, no longer needed)
- [ ] Verify no remaining imports of old modules: `grep -r "from log import\|from visit_counter import\|from youtube_bot import" .`
- [ ] Run full test suite
- [ ] Run tests — must pass before next task

### Task 14: Verify acceptance criteria

- [ ] Verify modular structure: all code in `bot/`, `services/`, `core/`, `storage/`
- [ ] Verify JSON logging works: file handlers output JSON, console outputs human-readable
- [ ] Verify log rotation: RotatingFileHandler configured at 5MB
- [ ] Verify inline buttons UX: URL → track selection → bitrate selection → download
- [ ] Verify FSM timeout: stale states cleared on next interaction after 10 minutes
- [ ] Verify SQLite storage: users and usage_log populated correctly
- [ ] Verify migration: old txt data imported to SQLite (username=NULL, first_seen_at=migration time)
- [ ] Verify admin panel: `/admin` shows buttons, stats/top/weekly work
- [ ] Verify async: downloads don't block event loop (test with concurrent requests)
- [ ] Run full test suite: `pytest tests/ -v`

### Task 15: [Final] Update documentation

- [ ] Create minimal README.md with: project description, setup, env vars, Docker deployment
- [ ] Move this plan to `docs/plans/completed/`

## Post-Completion

**Manual verification:**
- Test with real YouTube URLs in development environment
- Verify audio file download and splitting works end-to-end
- Test inline buttons UX with multiple audio tracks
- Verify admin commands work for superuser
- Test Docker deployment with `docker-compose up`
- Verify bot stays responsive during large file downloads (async wrapping)

**Deployment:**
- Rebuild Docker image with new structure
- Verify volume mounts for `/app/config` (SQLite DB) and `/app/logs`
- First run will auto-migrate txt data to SQLite
