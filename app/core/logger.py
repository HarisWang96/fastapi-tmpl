"""Centralized logging through Loguru.

Local development writes to stderr and files under LOG_DIR with rotation and
retention. Containers set LOG_TO_FILE=false and write to stderr for collection.
Loguru locks and queues are process-local, so multiple Uvicorn workers writing
one rotating file can race during rename and cleanup.

Standard-library logging (including Uvicorn) is forwarded to Loguru for one format.
"""

import logging
import sys
from pathlib import Path

from loguru import logger

from app.core.clock import TZ
from app.core.config import settings


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _add_file(path: Path, level: str, retention: str) -> None:
    logger.add(
        path,
        level=level,
        retention=retention,
        rotation="10 MB",
        compression="gz",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=settings.DEBUG,
    )


def _patch_record(record: dict) -> None:
    # Loguru uses the process timezone; convert timestamps to the business timezone.
    record["time"] = record["time"].astimezone(TZ)


def setup_logging() -> None:
    logger.remove()
    logger.configure(patcher=_patch_record)
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        backtrace=True,
        diagnose=settings.DEBUG,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:{line} | <level>{message}</level>"
        ),
    )

    if settings.LOG_TO_FILE:
        try:
            log_dir = Path(settings.LOG_DIR)
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(f"日志目录不可写，仅输出到 stderr：{settings.LOG_DIR} ({exc})")
        else:
            _add_file(log_dir / "app.log", settings.LOG_LEVEL, settings.LOG_RETENTION)
            _add_file(log_dir / "error.log", "ERROR", "30 days")

    handler = _InterceptHandler()
    logging.basicConfig(handlers=[handler], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [handler]
        std_logger.propagate = False

    # Uvicorn checks hasHandlers(), which sees the root handler configured above.
    # Use NullHandler to suppress access logs; middleware.py emits the request ID and duration.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = [logging.NullHandler()]
    access_logger.propagate = False


setup_logging()
