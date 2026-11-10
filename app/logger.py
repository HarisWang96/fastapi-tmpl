"""Logging configuration module using loguru"""

import logging
import sys
from pathlib import Path

from loguru import logger

from app.config import settings
from app.context import request_id_ctx


def setup_logging():
    """Configure application logging"""

    # Remove default handler
    logger.remove()

    # Log format
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # Console handler
    sink: dict[str, object] = {
        "level": settings.LOG_LEVEL,
        "backtrace": False,
        "diagnose": False,
    }
    if settings.LOG_FORMAT == "json":
        sink["serialize"] = True
    else:
        sink["format"] = log_format
    logger.configure(patcher=_patch_record)
    logger.add(sys.stderr, **sink)

    # File handler (with rotation)
    log_dir = Path(settings.LOG_DIR)
    if settings.LOG_TO_FILE:
        log_dir.mkdir(parents=True, exist_ok=True)

    # Application log
    file_options = {
        "level": "INFO",
        "retention": "7 days",
        "rotation": "10 MB",
        "compression": "gz",
        "encoding": "utf-8",
        "enqueue": True,
    }
    if settings.LOG_FORMAT == "json":
        file_options["serialize"] = True
    else:
        file_options["format"] = log_format
    if settings.LOG_TO_FILE:
        logger.add(
            log_dir / "app.log",
            **file_options,
        )

        # Error log (separate file for errors)
        logger.add(
            log_dir / "error.log",
            **{**file_options, "level": "ERROR", "retention": "30 days"},
        )

    return logger


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(exception=record.exc_info, depth=6).log(level, record.getMessage())


def _patch_record(record: dict) -> None:
    record["extra"].setdefault("service", settings.APP_NAME)
    request_id = request_id_ctx.get()
    if request_id:
        record["extra"].setdefault("request_id", request_id)


# Initialize logger
setup_logging()
_handler = _InterceptHandler()
logging.basicConfig(handlers=[_handler], level=0, force=True)

# Export logger for use in other modules
__all__ = ["logger"]
