"""Application exceptions and global exception handlers.

Business code raises exceptions instead of returning error responses; handlers format them here.

AuthError represents missing or invalid identity headers or a mismatched proxy token.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.logger import logger
from app.core.schemas.common import error_response


class AppError(Exception):
    """Base application error with a business code and HTTP status code."""

    status_code = 400
    code = 1500
    message = "请求处理失败"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: int | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)


class AuthError(AppError):
    status_code = 401
    code = 1401
    message = "调用者身份缺失或非法"


class BadRequestError(AppError):
    status_code = 400
    code = 1400
    message = "请求参数不合法"


class ForbiddenError(AppError):
    status_code = 403
    code = 1403
    message = "无访问权限"


class NotFoundError(AppError):
    status_code = 404
    code = 1404
    message = "资源不存在"


class ConflictError(AppError):
    status_code = 409
    code = 1409
    message = "请求冲突"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = 1503
    message = "依赖服务不可用"


# MySQL/PyMySQL connection error codes: unavailable, disconnected, or exhausted server connections.
# Other OperationalErrors (such as unknown column 1054) indicate application SQL errors and remain 500s.
_CONN_ERROR_CODES = frozenset({1040, 1053, 1203, 2002, 2003, 2006, 2013})


def _db_error_code(exc: BaseException) -> int | None:
    args = getattr(getattr(exc, "orig", None), "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError):
        logger.warning(
            f"[{_request_id(request)}] 业务异常 code={exc.code} {request.method} "
            f"{request.url.path}: {exc.message}"
        )
        return error_response(exc.message, code=exc.code, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError):
        logger.info(f"[{_request_id(request)}] 参数校验失败 {request.method} {request.url.path}")
        return error_response(
            "请求参数校验失败",
            code=422,
            status_code=422,
            detail=str(exc.errors()) if settings.DEBUG else None,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(request: Request, exc: StarletteHTTPException):
        return error_response(str(exc.detail), code=exc.status_code, status_code=exc.status_code)

    @app.exception_handler(PoolTimeoutError)
    async def _handle_pool_timeout(request: Request, exc: PoolTimeoutError):
        # Pool acquisition timeout is a capacity issue; return 503 so callers may retry.
        logger.error(
            f"[{_request_id(request)}] 数据库连接池获取超时 {request.method} {request.url.path}"
        )
        return error_response("服务繁忙，请稍后重试", code=1503, status_code=503)

    @app.exception_handler(OperationalError)
    async def _handle_db_unavailable(request: Request, exc: OperationalError):
        code = _db_error_code(exc)
        if code not in _CONN_ERROR_CODES:
            # SQL errors (unknown columns, syntax, constraints) use the generic 500 handler.
            return await _handle_unhandled(request, exc)
        # Log only the error code, not SQL statements or parameters that may contain business data.
        logger.error(
            f"[{_request_id(request)}] 数据库不可用 code={code} {request.method} {request.url.path}"
        )
        return error_response("依赖服务不可用", code=1503, status_code=503)

    @app.exception_handler(Exception)
    async def _handle_unhandled(request: Request, exc: Exception):
        logger.exception(
            f"[{_request_id(request)}] 未处理异常 {request.method} {request.url.path}: {exc}"
        )
        return error_response(
            "服务器内部错误",
            code=500,
            status_code=500,
            detail=f"{type(exc).__name__}: {exc}" if settings.DEBUG else None,
        )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")
