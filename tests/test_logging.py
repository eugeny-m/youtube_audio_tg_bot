import json
import logging
from logging.handlers import RotatingFileHandler

from pythonjsonlogger.json import JsonFormatter

from core.config import Settings
from core.logging import setup_logging


def test_setup_logging_creates_handlers(test_env, tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", debug=False)
    setup_logging(settings)

    root = logging.getLogger()
    handler_types = [type(h) for h in root.handlers]
    assert RotatingFileHandler in handler_types
    assert logging.StreamHandler in handler_types

    rotating_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating_handlers) == 2  # app.log + error.log


def test_setup_logging_file_handlers_use_json(test_env, tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", debug=False)
    setup_logging(settings)

    root = logging.getLogger()
    rotating_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    for h in rotating_handlers:
        assert isinstance(h.formatter, JsonFormatter)


def test_setup_logging_console_uses_standard_formatter(test_env, tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", debug=False)
    setup_logging(settings)

    root = logging.getLogger()
    stream_handlers = [
        h for h in root.handlers
        if type(h) is logging.StreamHandler
    ]
    assert len(stream_handlers) == 1
    assert not isinstance(stream_handlers[0].formatter, JsonFormatter)


def test_setup_logging_app_log_handler_config(test_env, tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", debug=False)
    setup_logging(settings)

    root = logging.getLogger()
    rotating_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    app_handler = [h for h in rotating_handlers if "app.log" in h.baseFilename][0]
    assert app_handler.maxBytes == 5 * 1024 * 1024
    assert app_handler.backupCount == 5
    assert app_handler.level == logging.INFO


def test_setup_logging_error_log_handler_config(test_env, tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", debug=False)
    setup_logging(settings)

    root = logging.getLogger()
    rotating_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    error_handler = [h for h in rotating_handlers if "error.log" in h.baseFilename][0]
    assert error_handler.maxBytes == 5 * 1024 * 1024
    assert error_handler.backupCount == 3
    assert error_handler.level == logging.ERROR


def test_setup_logging_debug_mode(test_env, tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", debug=True)
    setup_logging(settings)

    root = logging.getLogger()
    assert root.level == logging.DEBUG

    stream_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
    assert stream_handlers[0].level == logging.DEBUG


def test_setup_logging_non_debug_mode(test_env, tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", debug=False)
    setup_logging(settings)

    root = logging.getLogger()
    assert root.level == logging.INFO

    stream_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
    assert stream_handlers[0].level == logging.INFO


def test_setup_logging_json_output(test_env, tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", debug=False)
    setup_logging(settings)

    logger = logging.getLogger("test_json_output")
    logger.info("test message", extra={"user_id": 123})

    app_log = tmp_path / "logs" / "app.log"
    assert app_log.exists()
    content = app_log.read_text().strip()
    parsed = json.loads(content)
    assert parsed["message"] == "test message"
    assert parsed["user_id"] == 123
    assert "timestamp" in parsed
    assert parsed["level"] == "INFO"


def test_setup_logging_creates_log_dir(test_env, tmp_path):
    log_dir = tmp_path / "new_logs_dir"
    assert not log_dir.exists()
    settings = Settings(log_dir=log_dir, debug=False)
    setup_logging(settings)
    assert log_dir.exists()


def test_setup_logging_idempotent(test_env, tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", debug=False)
    setup_logging(settings)
    setup_logging(settings)

    root = logging.getLogger()
    # Should not accumulate duplicate handlers
    assert len(root.handlers) == 3  # app + error + console
