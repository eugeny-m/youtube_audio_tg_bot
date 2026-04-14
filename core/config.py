from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    tg_superuser: int = 0
    bot_proxy: Optional[str] = None
    bot_username: str = "get_me_youtube_audio_bot"
    max_audio_file_size_mb: float = 49.5
    temp_download_dir: Path = Path("temp_download")
    log_level: str = "INFO"
    debug: bool = False
    log_dir: Path = Path("logs")
    db_path: Path = Path("config/bot.db")

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}
