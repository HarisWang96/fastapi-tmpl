"""unified API response schema"""

from datetime import datetime
from typing import Generic, TypeVar, Optional

from pydantic import BaseModel

# define generic type for response data
T = TypeVar("T")


class ResponseModel(BaseModel, Generic[T]):
    """unified API response model

    all API interfaces should use this response structure
    """

    code: int = 200
    message: str = "success"
    data: Optional[T] = None
    timestamp: datetime = datetime.now()

    class Config:
        """Pydantic configuration settings"""

        json_encoders = {datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S.%f")}


class ErrorResponse(BaseModel):
    """error response model"""

    code: int
    message: str
    detail: Optional[str] = None
    timestamp: datetime = datetime.now()

    class Config:
        """Pydantic configuration settings"""

        json_encoders = {datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S.%f")}
