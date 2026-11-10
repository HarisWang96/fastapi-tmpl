"""Application errors and consistent FastAPI exception handlers."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.logger import logger
from app.schemas.errors import ErrorBody


class AppError(Exception):
    def __init__(self, message: str, *, code: int, status_code: int) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(message, code=1401, status_code=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message, code=1403, status_code=403)


class ServiceUnavailableError(AppError):
    def __init__(self, message: str = "Dependency unavailable") -> None:
        super().__init__(message, code=1503, status_code=503)


def _response(message: str, code: int, status_code: int, detail=None) -> JSONResponse:
    body = ErrorBody(code=code, message=message, detail=detail)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError):
        return _response(exc.message, exc.code, exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException):
        return _response(str(exc.detail), exc.status_code, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        detail = exc.errors() if _request.app.debug else None
        return _response("Request validation failed", 422, 422, detail)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception(
            "Unhandled request error method={} path={}",
            request.method,
            request.url.path,
        )
        detail = f"{type(exc).__name__}: {exc}" if request.app.debug else None
        return _response("Internal server error", 500, 500, detail)
