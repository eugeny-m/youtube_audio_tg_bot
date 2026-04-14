import logging
import os
from logging.handlers import RotatingFileHandler

from pythonjsonlogger.json import JsonFormatter


def setup_logging(settings) -> None:
    """Configure stdlib logging with JSON file handlers and human-readable console."""
    log_dir = str(settings.log_dir)
    os.makedirs(log_dir, exist_ok=True)

    root_logger = logging.getLogger()
    if settings.debug:
        effective_level = logging.DEBUG
    else:
        effective_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root_logger.setLevel(effective_level)

    # Clear existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # JSON formatter for file handlers
    json_formatter = JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )

    # app.log — all messages at INFO+
    app_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, "app.log"),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(json_formatter)

    # error.log — ERROR+ only
    error_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, "error.log"),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(json_formatter)

    # Console — human-readable
    console_handler = logging.StreamHandler()
    if settings.debug:
        console_handler.setLevel(logging.DEBUG)
        console_fmt = "%(asctime)s %(name)s %(levelname)s %(pathname)s:%(lineno)d %(message)s"
    else:
        console_handler.setLevel(effective_level)
        console_fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    console_handler.setFormatter(logging.Formatter(console_fmt))

    root_logger.addHandler(app_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
