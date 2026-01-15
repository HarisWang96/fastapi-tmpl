"""upload related Pydantic schemas"""

from typing import Optional

from pydantic import BaseModel, Field


class PresignedUrlRequest(BaseModel):
    """request model for presigned URL"""

    filename: str = Field(
        ..., min_length=1, max_length=255, description="Original filename"
    )
    folder: Optional[str] = Field(
        default="", max_length=100, description="Subfolder in bucket"
    )
    content_type: Optional[str] = Field(
        default=None, description="MIME type (auto-detected if not provided)"
    )


class PresignedUrlResponse(BaseModel):
    """response model for presigned URL"""

    upload_url: str = Field(..., description="Presigned URL for PUT request")
    key: str = Field(..., description="S3 object key")
    public_url: str = Field(..., description="Public URL after upload")
    expires_in: int = Field(..., description="URL expiration time in seconds")
