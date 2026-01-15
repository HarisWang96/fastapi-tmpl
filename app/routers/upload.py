"""upload router - presigned URL for direct S3 upload"""

from pathlib import Path

from fastapi import APIRouter, Query, status

from app.utils.response import success_response, error_response
from app.utils.s3 import get_presigned_upload_url, PresignedUploadResult
from app.schemas.response import ResponseModel
from app.schemas.upload import PresignedUrlRequest, PresignedUrlResponse
from app.config import settings

router = APIRouter(prefix="/upload", tags=["upload"])

# Allowed file extensions configuration
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".xlsx", ".xls"}

# Allowed MIME types (for content_type validation if provided)
ALLOWED_IMAGE_TYPES = set(settings.UPLOAD_ALLOWED_IMAGE_TYPES.split(","))
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}


def _get_file_extension(filename: str) -> str:
    """Get lowercase file extension from filename"""
    return Path(filename).suffix.lower()


def _validate_file_type(
    filename: str,
    content_type: str | None,
    allowed_extensions: set[str],
    allowed_types: set[str],
    type_name: str,
) -> str | None:
    """
    Validate file type by extension and content_type.

    Returns error message if invalid, None if valid.
    """
    ext = _get_file_extension(filename)

    # Validate by extension
    if ext not in allowed_extensions:
        return f"Invalid {type_name} type. Allowed extensions: {', '.join(sorted(allowed_extensions))}"

    # Validate content_type if provided
    if content_type and content_type not in allowed_types:
        return f"Invalid {type_name} MIME type. Allowed: {', '.join(sorted(allowed_types))}"

    return None


async def _generate_presigned_response(
    request: PresignedUrlRequest,
    folder: str,
    expires_in: int,
) -> PresignedUrlResponse:
    """Generate presigned URL and build response"""
    result: PresignedUploadResult = await get_presigned_upload_url(
        original_filename=request.filename,
        folder=folder,
        content_type=request.content_type,
        expiration=expires_in,
    )

    return PresignedUrlResponse(
        upload_url=result.upload_url,
        key=result.key,
        public_url=result.public_url,
        expires_in=expires_in,
    )


@router.post("/presign", response_model=ResponseModel[PresignedUrlResponse])
async def get_upload_presigned_url(
    request: PresignedUrlRequest,
    expires_in: int = Query(
        default=3600, ge=60, le=43200, description="URL expiration (60s-12h)"
    ),
):
    """
    Generate a presigned URL for direct frontend upload to S3.

    The frontend can use this URL to upload files directly to S3
    without going through the backend server.

    ## Usage Flow:
    1. Frontend calls this API with filename
    2. Backend returns presigned URL
    3. Frontend uploads file directly to S3 using PUT request
    4. Frontend notifies backend with the key for database storage

    ## Frontend Example (JavaScript):
    ```javascript
    // 1. Get presigned URL
    const response = await fetch('/api/v1/upload/presign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: 'photo.jpg', folder: 'avatars' })
    });
    const { data } = await response.json();

    // 2. Upload directly to S3
    await fetch(data.upload_url, {
        method: 'PUT',
        body: file,
        headers: { 'Content-Type': file.type }
    });

    // 3. Use data.key or data.public_url for further processing
    ```
    """
    response = await _generate_presigned_response(
        request=request,
        folder=request.folder or "",
        expires_in=expires_in,
    )
    return success_response(data=response)


@router.post("/presign/image", response_model=ResponseModel[PresignedUrlResponse])
async def get_image_upload_presigned_url(
    request: PresignedUrlRequest,
    expires_in: int = Query(default=3600, ge=60, le=43200),
):
    """
    Generate a presigned URL for image upload.

    Only allows image types: JPEG, PNG, GIF, WebP
    """
    # Validate file type
    error_msg = _validate_file_type(
        filename=request.filename,
        content_type=request.content_type,
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
        allowed_types=ALLOWED_IMAGE_TYPES,
        type_name="image",
    )
    if error_msg:
        return error_response(message=error_msg, code=status.HTTP_400_BAD_REQUEST)

    response = await _generate_presigned_response(
        request=request,
        folder=request.folder or "images",
        expires_in=expires_in,
    )
    return success_response(data=response)


@router.post("/presign/document", response_model=ResponseModel[PresignedUrlResponse])
async def get_document_upload_presigned_url(
    request: PresignedUrlRequest,
    expires_in: int = Query(default=3600, ge=60, le=43200),
):
    """
    Generate a presigned URL for document upload.

    Only allows document types: PDF, XLSX, XLS
    """
    # Validate file type
    error_msg = _validate_file_type(
        filename=request.filename,
        content_type=request.content_type,
        allowed_extensions=ALLOWED_DOCUMENT_EXTENSIONS,
        allowed_types=ALLOWED_DOCUMENT_TYPES,
        type_name="document",
    )
    if error_msg:
        return error_response(message=error_msg, code=status.HTTP_400_BAD_REQUEST)

    response = await _generate_presigned_response(
        request=request,
        folder=request.folder or "documents",
        expires_in=expires_in,
    )
    return success_response(data=response)
