"""FastAPI main application"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import init_db, close_db
from app.logger import logger
from app.routers import health, enums, tasks, upload
from app.utils.response import error_response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """application lifecycle management"""
    # when the application is starting up
    logger.info("Application starting up...")
    await init_db()
    logger.info("Database initialized")
    yield
    # when the application is shutting down
    logger.info("Application shutting down...")
    await close_db()
    logger.info("Database connection closed")


# create FastAPI application instance
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # in production environment, should set specific domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# global exception handlers
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    """handle HTTP exception"""
    return error_response(
        message=exc.detail,
        code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    """handle request validation exception"""
    return error_response(
        message="Request validation failed",
        code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc.errors()),
    )


@app.exception_handler(Exception)
async def general_exception_handler(_request: Request, exc: Exception):
    """handle other uncaught exceptions"""
    logger.exception(f"Unhandled exception: {exc}")
    return error_response(
        message="Internal server error",
        code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=str(exc) if settings.DEBUG else None,
    )


# register routers
app.include_router(health.router)
app.include_router(enums.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(upload.router, prefix="/api/v1")

# Add your routers here
# Example:
# from app.routers import users, items
# app.include_router(users.router, prefix="/api/v1")
# app.include_router(items.router, prefix="/api/v1")


@app.get("/")
async def root():
    """root path"""
    from app.utils.response import success_response

    data = {
        "message": "Welcome to FastAPI async framework",
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
    return success_response(data=data)
