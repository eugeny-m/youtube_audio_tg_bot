import logging
from logging.handlers import RotatingFileHandler


def get_logger(name: str = 'youtube_bot'):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(pathname)s - %(message)s')
    
    file_handler = RotatingFileHandler(
        filename='logs/info.log',
        maxBytes=1024 * 512,  # 0.5mb
        backupCount=5,
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_format)
    
    error_file_handler = RotatingFileHandler(
        filename='logs/error.log',
        maxBytes=1024 * 512,  # 0.5mb
        backupCount=5,
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(log_format)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(log_format)
    
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(error_file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    
    return logger
