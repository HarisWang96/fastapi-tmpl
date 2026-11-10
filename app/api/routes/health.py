"""Health checks: /livez checks the process; /readyz and /healthz probe dependencies.

Probes check real dependencies rather than always returning success.
An unconfigured dependency returns 503 instead of preventing process startup.
"""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.db.orm import get_engine
from app.core.db.redis import get_redis
from app.core.logger import logger

router = APIRouter(tags=["health"])


@router.get("/livez")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    result = await _dependency_status(request)
    return JSONResponse(status_code=200 if result["status"] == "ok" else 503, content=result)


@router.get("/healthz")
async def health(request: Request) -> JSONResponse:
    result = await _dependency_status(request)
    body = {"service": request.app.title, "version": request.app.version, **result}
    return JSONResponse(status_code=200 if result["status"] == "ok" else 503, content=body)


async def _dependency_status(request: Request) -> dict[str, Any]:
    probes = {
        "mysql": _probe_mysql,
        "redis": _probe_redis,
    }
    selected = settings.READINESS_DEPENDENCIES
    results = await asyncio.gather(*(asyncio.to_thread(probes[name]) for name in selected))
    dependencies = dict(zip(selected, results, strict=True))
    if settings.EVENT_ENABLED:
        runtime = getattr(request.app.state, "event_runtime", None)
        publisher = getattr(runtime, "publisher", None)
        dependencies["rabbitmq"] = (
            {"status": "up"}
            if publisher is not None and publisher.connected
            else {"status": "down"}
        )
    healthy = all(item["status"] == "up" for item in dependencies.values())
    return {"status": "ok" if healthy else "degraded", "dependencies": dependencies}


def _probe_mysql() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with get_engine("default").connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.opt(exception=True).error("MySQL 健康检查失败")
        return {"status": "down", "error": type(exc).__name__}
    return {"status": "up", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}


def _probe_redis() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        get_redis().ping()
    except Exception as exc:
        logger.opt(exception=True).error("Redis 健康检查失败")
        return {"status": "down", "error": type(exc).__name__}
    return {"status": "up", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
