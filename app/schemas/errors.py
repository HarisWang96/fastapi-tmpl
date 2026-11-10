"""Stable error response contract."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: int
    message: str
    detail: Any | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
