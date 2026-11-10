"""Centralized logging through Loguru.

Local development writes to stderr and files under LOG_DIR with rotation and
retention. Containers set LOG_TO_FILE=false and write to stderr for collection;
file logging is a development convenience only.

Standard-library logging (including Uvicorn) is forwarded to Loguru for one format.
"""

import logging
import sys
from pathlib import Path

from loguru import logger

from app.core.clock import TZ
from app.core.config import settings
from app.core.context import request_id_ctx

# Files omit colors so the same layout can be parsed by log collectors.
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:{line} | <level>{message}</level>"
)
_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} | {message}"


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Skip logging's internal frames so Loguru reports the real caller
        # (for example uvicorn.server) instead of logging/__init__.py.
        frame = logging.currentframe()
        frame = frame.f_back if frame is not None else None
        depth = 1
        while frame is not None:
            module = frame.f_globals.get("__name__", "")
            if module != "logging" and not module.startswith("logging."):
                break
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _add_file(path: Path, level: str, retention: str) -> None:
    options: dict[str, object] = {
        "level": level,
        "retention": retention,
        "rotation": "10 MB",
        "compression": "gz",
        "encoding": "utf-8",
        "enqueue": True,
        "backtrace": True,
        "diagnose": settings.DEBUG,
    }
    if settings.LOG_FORMAT == "json":
        # serialize and format are mutually exclusive: the JSON line is the whole record.
        options["serialize"] = True
    else:
        options["format"] = _FILE_FORMAT
    logger.add(path, **options)


def _patch_record(record: dict) -> None:
    # Loguru uses the process timezone; convert timestamps to the business timezone.
    record["time"] = record["time"].astimezone(TZ)
    record["extra"].setdefault("service", settings.APP_NAME)
    request_id = request_id_ctx.get()
    if request_id:
        record["extra"].setdefault("request_id", request_id)


def setup_logging() -> None:
    logger.remove()
    logger.configure(patcher=_patch_record)
    sink: dict[str, object] = {
        "level": settings.LOG_LEVEL,
        "backtrace": True,
        "diagnose": settings.DEBUG,
    }
    if settings.LOG_FORMAT == "json":
        sink["serialize"] = True
    else:
        sink["format"] = _CONSOLE_FORMAT
    logger.add(sys.stderr, **sink)

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

    # httpx logs one INFO line per outbound call, duplicating the callee's access log
    # and lacking the request ID. Errors still surface at WARNING and above.
    for name in ("httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(name).setLevel(logging.WARNING)


setup_logging()
