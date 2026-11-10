"""FastAPI async PostgreSQL service application."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from starlette.responses import Response

from app.config import settings
from app.core import events, idempotency
from app.core.metrics import render
from app.core.middleware import RequestContextMiddleware
from app.database import close_db, engine
from app.dependencies import close_authz_client
from app.errors import register_exception_handlers
from app.logger import logger
from app.routers import demo, health
from app.utils.response import success_response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("service={} starting env={}", settings.APP_NAME, settings.APP_ENV)
    redis = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
        socket_timeout=settings.REDIS_TIMEOUT,
    )
    app.state.db_engine = engine
    app.state.redis = redis
    cleanup_stop = asyncio.Event()
    cleanup_task = asyncio.create_task(idempotency.cleanup_forever(cleanup_stop))
    event_runtime = await events.start_event_bus()
    app.state.event_runtime = event_runtime
    try:
        yield
    finally:
        cleanup_stop.set()
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        await events.close_event_bus(event_runtime)
        await close_authz_client()
        await redis.aclose()
        await close_db()
        logger.info("service={} resources closed", settings.APP_NAME)


docs_enabled = settings.APP_ENV != "prod" or settings.DEBUG
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)
register_exception_handlers(app)
app.include_router(health.router)
app.include_router(demo.router)


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    return render(request)


@app.get("/")
async def root():
    return success_response(
        data={
            "message": "Welcome to FastAPI microservice template",
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }
    )
