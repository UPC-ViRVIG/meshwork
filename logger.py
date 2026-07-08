# logger.py
import logging
import logging.handlers
from pathlib import Path
from config import get_config

def setup_logger():
    config = get_config()
    level = getattr(logging, config.get("logging", "level", "INFO").upper())
    log_file = Path(config.get("logging", "file", "")).expanduser()
    max_size = config.get("logging", "max_size", 10 * 1024 * 1024)
    backup_count = config.get("logging", "backup_count", 5)

    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("meshwork")
    logger.setLevel(level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_size, backupCount=backup_count
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

def get_logger():
    return setup_logger()

def log(message, level="INFO"):
    logger = get_logger()
    level = level.upper()
    if level == "DEBUG":
        logger.debug(message)
    elif level == "INFO":
        logger.info(message)
    elif level == "WARNING":
        logger.warning(message)
    elif level == "ERROR":
        logger.error(message)
    elif level == "CRITICAL":
        logger.critical(message)
    else:
        logger.info(message)