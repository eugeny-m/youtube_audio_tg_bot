import os
import pytest
from pathlib import Path


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    """Set up test environment variables and temp paths."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-123")
    monkeypatch.setenv("TG_SUPERUSER", "999")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TEMP_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    return tmp_path
