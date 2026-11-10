"""unified API response schema"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class ResponseModel[T](BaseModel):
    """unified API response model

    all API interfaces should use this response structure
    """

    code: int = 200
    message: str = "success"
    data: T | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_config = ConfigDict(ser_json_bytes="utf8")


class ErrorResponse(BaseModel):
    """error response model"""

    code: int
    message: str
    detail: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
