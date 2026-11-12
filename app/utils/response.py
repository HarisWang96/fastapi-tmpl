"""response utility functions"""

from datetime import UTC, datetime
from typing import Any

from fastapi.responses import JSONResponse

from app.schemas.response import ErrorResponse, ResponseModel


def success_response(
    data: Any = None,
    message: str = "success",
    code: int = 200,
) -> ResponseModel:
    """create success response

    Args:
        data: response data
        message: response message
        code: response status code, default 200

    Returns:
        ResponseModel: unified response object
    """
    return ResponseModel(
        code=code,
        message=message,
        data=data,
        timestamp=datetime.now(UTC),
    )


def error_response(
    message: str = "error",
    code: int = 400,
    detail: str | None = None,
) -> JSONResponse:
    error = ErrorResponse(
        code=code,
        message=message,
        detail=detail,
        timestamp=datetime.now(UTC),
    )
    return JSONResponse(
        status_code=code,
        content=error.model_dump(mode="json"),
    )
