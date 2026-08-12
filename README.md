# YouTube Audio Telegram Bot

Telegram bot that downloads audio from YouTube videos. Supports multi-track selection (language), bitrate choice, and automatic file splitting for large files.

Built with aiogram 3, pytubefix, and SQLite.

## Features

- Two-step download UX: choose audio track (language) then bitrate via inline buttons
- Automatic splitting of audio files exceeding Telegram's 50MB limit (via ffmpeg)
- Admin panel (`/admin`) with usage statistics
- JSON structured logging with log rotation
- SQLite storage for users and usage tracking
- Async-safe: blocking downloads run in thread pool

## Project Structure

```
bot/            # Telegram handlers, keyboards, FSM states, middlewares
services/       # YouTube download and audio processing
core/           # Configuration (pydantic-settings) and logging setup
storage/        # SQLite database, repository, txt migration
tests/          # pytest test suite
main.py         # Entry point
```

## Setup

### Requirements

- Python 3.12+
- ffmpeg
- Node.js (for pytubefix potoken generation)

### Install

```bash
pip install -r requirements.txt
# For development:
pip install -r requirements-dev.txt
```

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | | Telegram Bot API token |
| `TG_SUPERUSER` | Yes | `0` | Telegram user ID for admin access |
| `BOT_PROXY` | No | | HTTP proxy URL for Telegram API |
| `BOT_USERNAME` | No | `get_me_youtube_audio_bot` | Bot username |
| `MAX_AUDIO_FILE_SIZE_MB` | No | `49.5` | Max file size before splitting |
| `TEMP_DOWNLOAD_DIR` | No | `temp_download` | Temporary download directory |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `DEBUG` | No | `false` | Enable debug mode (verbose console logging) |
| `LOG_DIR` | No | `logs` | Log files directory |
| `DB_PATH` | No | `config/bot.db` | SQLite database path |

### Run

```bash
python main.py
```

## Docker Deployment

Build and run with Docker:

```bash
docker build -f prod.Dockerfile -t youtube_tg:latest .
docker-compose up -d
```

Volume mounts:
- `/app/config` - SQLite database (persistent)
- `/app/logs` - Log files

On first run, existing `first_visit_ids.txt` and `bot_usage.txt` files in the config directory are automatically migrated to SQLite.

## Production

| | |
|---|---|
| Server | `138.124.73.63` (HipHoster, Frankfurt) |
| Project dir | `/opt/youtube_tg_bot` (docker-compose.yml, logs/) |
| Config dir | `/etc/youtube_tg_bot` (bot.db), mounted to `/app/config` |
| Container | `youtube_tg` |

The image is built locally (`release.sh`) and shipped via `docker save`/`docker load` — there is no registry.

`BOT_PROXY` is not set: the server reaches the Telegram API directly.

## Testing

```bash
pytest tests/ -v
```
