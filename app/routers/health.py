"""Application liveness, readiness and dependency health checks."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.logger import logger

router = APIRouter(tags=["health"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _check_postgres(engine: AsyncEngine) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {
            "status": "up",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("PostgreSQL health check failed")
        return {
            "status": "down",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": type(exc).__name__,
        }


async def _check_redis(redis: Redis | None) -> dict[str, Any]:
    started = time.perf_counter()
    if redis is None:
        return {"status": "down", "error": "redis_not_initialized"}
    try:
        await redis.ping()
        return {
            "status": "up",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Redis health check failed")
        return {
            "status": "down",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": type(exc).__name__,
        }


async def _dependency_status(request: Request) -> dict[str, Any]:
    postgres, redis = await asyncio.gather(
        _check_postgres(request.app.state.db_engine),
        _check_redis(getattr(request.app.state, "redis", None)),
    )
    dependencies = {"postgres": postgres, "redis": redis}
    healthy = all(item["status"] == "up" for item in dependencies.values())
    return {
        "status": "ok" if healthy else "degraded",
        "timestamp": _utc_now(),
        "dependencies": dependencies,
    }


@router.get("/livez")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(request: Request):
    result = await _dependency_status(request)
    return JSONResponse(
        status_code=200 if result["status"] == "ok" else 503,
        content=result,
    )


@router.get("/healthz")
async def health(request: Request):
    result = await _dependency_status(request)
    return JSONResponse(
        status_code=200 if result["status"] == "ok" else 503,
        content={"service": request.app.title, "version": request.app.version, **result},
    )
