"""response utility functions"""

from typing import Any, Optional
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

from app.schemas.response import ResponseModel, ErrorResponse


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
        timestamp=datetime.now(timezone.utc),
    )


def error_response(
    message: str = "error",
    code: int = 400,
    detail: Optional[str] = None,
) -> JSONResponse:
    """create error response as JSONResponse

    Used in exception handlers where HTTP status code needs to be set.

    Args:
        message: error message
        code: error status code, default 400
        detail: detailed error information

    Returns:
        JSONResponse: FastAPI JSON response with proper HTTP status code
    """
    error = ErrorResponse(
        code=code,
        message=message,
        detail=detail,
        timestamp=datetime.now(timezone.utc),
    )
    return JSONResponse(
        status_code=code,
        content=error.model_dump(mode="json"),
    )
