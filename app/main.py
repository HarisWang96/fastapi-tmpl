"""Application entry point: uvicorn app.main:app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import build_api_router
from app.core.config import settings
from app.core.db.orm import dispose_all as close_orm_engines
from app.core.db.redis import close_all as close_redis_pools
from app.core.exceptions import register_exception_handlers
from app.core.logger import logger
from app.core.middleware import RequestContextMiddleware
from app.core.schemas.common import ApiResponse, success


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info(f"{settings.APP_NAME} 启动 env={settings.APP_ENV} version={settings.APP_VERSION}")
    try:
        yield
    finally:
        close_orm_engines()
        close_redis_pools()
        logger.info("连接池已释放，服务退出")


def create_app() -> FastAPI:
    # Hide API documentation in production unless DEBUG is explicitly enabled.
    docs_enabled = settings.DEBUG or settings.APP_ENV != "prod"
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
    # Middleware added later wraps earlier middleware, so CORS also covers error responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # Mount all endpoints through one router, including their prefixes and dependencies.
    app.include_router(build_api_router())

    @app.get("/", response_model=ApiResponse[dict[str, str]], include_in_schema=False)
    def root() -> ApiResponse[Any]:
        return success(
            {"service": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"}
        )

    return app


app = create_app()
