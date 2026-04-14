import os
from pathlib import Path

import pytest

from core.config import Settings


class TestSettingsDefaults:
    def test_default_values(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.delenv("TG_SUPERUSER", raising=False)
        s = Settings()
        assert s.telegram_bot_token == "test-token"
        assert s.tg_superuser == 0
        assert s.bot_proxy is None
        assert s.bot_username == "get_me_youtube_audio_bot"
        assert s.max_audio_file_size_mb == 49.5
        assert s.temp_download_dir == Path("temp_download")
        assert s.log_level == "INFO"
        assert s.debug is False
        assert s.log_dir == Path("logs")
        assert s.db_path == Path("config/bot.db")

    def test_missing_token_raises(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with pytest.raises(Exception):
            Settings()


class TestSettingsFromEnv:
    def test_env_var_loading(self, test_env):
        s = Settings()
        assert s.telegram_bot_token == "test-token-123"
        assert s.tg_superuser == 999
        assert s.db_path == test_env / "test.db"
        assert s.log_dir == test_env / "logs"
        assert s.temp_download_dir == test_env / "downloads"

    def test_optional_proxy(self, test_env, monkeypatch):
        assert Settings().bot_proxy is None
        monkeypatch.setenv("BOT_PROXY", "socks5://proxy:1080")
        s = Settings()
        assert s.bot_proxy == "socks5://proxy:1080"

    def test_debug_flag(self, test_env, monkeypatch):
        monkeypatch.setenv("DEBUG", "true")
        s = Settings()
        assert s.debug is True

    def test_log_level_override(self, test_env, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        s = Settings()
        assert s.log_level == "DEBUG"

    def test_max_audio_file_size_override(self, test_env, monkeypatch):
        monkeypatch.setenv("MAX_AUDIO_FILE_SIZE_MB", "25.0")
        s = Settings()
        assert s.max_audio_file_size_mb == 25.0
