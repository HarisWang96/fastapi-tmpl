"""Logging configuration module using loguru"""

import sys
from pathlib import Path

from loguru import logger

from app.config import settings


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
    logger.add(
        sys.stderr,
        format=log_format,
        level=settings.LOG_LEVEL,
        colorize=True,
        backtrace=True,
        diagnose=settings.DEBUG,
    )

    # File handler (with rotation)
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Application log
    logger.add(
        log_dir / "app.log",
        format=log_format,
        level="INFO",
        rotation="10 MB",  # Rotate when file reaches 10MB
        retention="7 days",  # Keep logs for 7 days
        compression="gz",  # Compress rotated files
        encoding="utf-8",
        enqueue=True,  # Async logging (thread-safe)
    )

    # Error log (separate file for errors)
    logger.add(
        log_dir / "error.log",
        format=log_format,
        level="ERROR",
        rotation="10 MB",
        retention="30 days",
        compression="gz",
        encoding="utf-8",
        enqueue=True,
    )

    return logger


# Initialize logger
setup_logging()

# Export logger for use in other modules
__all__ = ["logger"]
