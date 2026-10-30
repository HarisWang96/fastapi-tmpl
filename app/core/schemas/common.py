"""Standard response contract: {code, message, data, timestamp}.

Business codes go in code; HTTP status codes are set explicitly by exception handlers.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


class ApiResponse[T](BaseModel):
    code: int = 200
    message: str = "success"
    data: T | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ErrorBody(BaseModel):
    code: int
    message: str
    detail: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ORMModel(BaseModel):
    """Read model that can validate directly from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class PageQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


def success(data: Any = None, message: str = "success", code: int = 200) -> ApiResponse[Any]:
    return ApiResponse[Any](code=code, message=message, data=data)


def error_response(
    message: str,
    *,
    code: int = 400,
    status_code: int | None = None,
    detail: str | None = None,
) -> JSONResponse:
    """Build an error response, falling back to HTTP 400 for non-HTTP business codes."""
    if status_code is None:
        status_code = code if 400 <= code <= 599 else 400
    body = ErrorBody(code=code, message=message, detail=detail)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))
