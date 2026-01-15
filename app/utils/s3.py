"""AWS S3 async utility - upload, download, presigned URL"""

import uuid
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import aioboto3
from botocore.exceptions import ClientError

from app.config import settings
from app.logger import logger


@dataclass
class PresignedUploadResult:
    """Result of generating a presigned upload URL"""

    upload_url: str  # presigned URL for PUT request
    key: str  # S3 object key
    public_url: str  # public URL after upload (for reference)


class S3Client:
    """AWS S3 async client wrapper

    Usage:
        # upload file
        s3 = S3Client()
        url = await s3.upload_file(file_bytes, "image.png", "images")

        # upload with custom filename
        url = await s3.upload_file(file_bytes, "photo.jpg", "lenders", filename="lender-123.jpg")

        # delete file
        await s3.delete_file("uploads/images/xxx.png")
    """

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: Optional[str] = None,
        bucket: Optional[str] = None,
    ):
        """initialize S3 client

        Args:
            access_key: AWS access key ID (default from settings)
            secret_key: AWS secret access key (default from settings)
            region: AWS region (default from settings)
            bucket: S3 bucket name (default from settings)
        """
        self.access_key = access_key or settings.AWS_ACCESS_KEY_ID
        self.secret_key = secret_key or settings.AWS_SECRET_ACCESS_KEY
        self.region = region or settings.AWS_REGION
        self.bucket = bucket or settings.AWS_S3_BUCKET
        self.prefix = settings.AWS_S3_PREFIX

        self._session = aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )

    def _generate_key(
        self,
        original_filename: str,
        folder: str = "",
        filename: Optional[str] = None,
    ) -> str:
        """generate S3 object key

        Args:
            original_filename: original filename (used for extension)
            folder: subfolder in bucket
            filename: custom filename (optional, generates UUID if not provided)

        Returns:
            S3 object key
        """
        # get file extension
        ext = Path(original_filename).suffix.lower()

        # generate filename if not provided
        if not filename:
            filename = f"{uuid.uuid4().hex}{ext}"
        elif not filename.endswith(ext):
            filename = f"{filename}{ext}"

        # build key path
        parts = [self.prefix, folder, filename]
        key = "/".join(p for p in parts if p)

        return key

    async def upload_file(
        self,
        file_bytes: bytes,
        original_filename: str,
        folder: str = "",
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        public: bool = True,
    ) -> str:
        """upload file to S3 asynchronously

        Args:
            file_bytes: file content as bytes
            original_filename: original filename
            folder: subfolder in bucket (e.g., "lenders", "products")
            filename: custom filename (optional)
            content_type: MIME type (auto-detected if not provided)
            public: whether the file should be publicly accessible

        Returns:
            public URL of the uploaded file
        """
        key = self._generate_key(original_filename, folder, filename)

        # auto-detect content type
        if not content_type:
            content_type = self._get_content_type(original_filename)

        extra_args = {"ContentType": content_type}
        # Note: ACL disabled for buckets with "Block Public Access" enabled
        # if public:
        #     extra_args["ACL"] = "public-read"

        try:
            async with self._session.client("s3") as s3:
                await s3.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=file_bytes,
                    **extra_args,
                )

            # generate public URL
            url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"
            logger.info(f"File uploaded to S3: {url}")
            return url

        except ClientError as e:
            logger.error(f"Failed to upload file to S3: {e}")
            raise

    async def delete_file(self, key_or_url: str) -> bool:
        """delete file from S3 asynchronously

        Args:
            key_or_url: S3 object key or full URL

        Returns:
            True if deleted successfully
        """
        # extract key from URL if needed
        key = self.extract_key(key_or_url)

        try:
            async with self._session.client("s3") as s3:
                await s3.delete_object(Bucket=self.bucket, Key=key)
            logger.info(f"File deleted from S3: {key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete file from S3: {e}")
            return False

    def extract_key(self, key_or_url: str) -> str:
        """extract S3 key from URL or return as-is"""
        if key_or_url.startswith("http"):
            # extract key from URL
            # https://bucket.s3.region.amazonaws.com/key
            parts = key_or_url.split(".amazonaws.com/", 1)
            if len(parts) == 2:
                return parts[1]
        return key_or_url

    def _get_content_type(self, filename: str) -> str:
        """get content type from filename"""
        ext = Path(filename).suffix.lower()
        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".pdf": "application/pdf",
            ".json": "application/json",
            ".txt": "text/plain",
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
        }
        return content_types.get(ext, "application/octet-stream")

    async def download_file(self, key_or_url: str) -> bytes:
        """download file from S3 to memory asynchronously

        Args:
            key_or_url: S3 object key or full URL

        Returns:
            file content as bytes
        """
        key = self.extract_key(key_or_url)

        try:
            async with self._session.client("s3") as s3:
                response = await s3.get_object(Bucket=self.bucket, Key=key)
                async with response["Body"] as stream:
                    file_bytes = await stream.read()

            logger.info(f"File downloaded from S3: {key} ({len(file_bytes)} bytes)")
            return file_bytes

        except ClientError as e:
            logger.error(f"Failed to download file from S3: {e}")
            raise

    async def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
        method: str = "get_object",
    ) -> str:
        """generate presigned URL for private files

        Args:
            key: S3 object key
            expiration: URL expiration time in seconds (default 1 hour)
            method: S3 method (get_object or put_object)

        Returns:
            presigned URL
        """
        try:
            async with self._session.client("s3") as s3:
                url = await s3.generate_presigned_url(
                    method,
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=expiration,
                )
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise

    async def generate_presigned_upload_url(
        self,
        original_filename: str,
        folder: str = "",
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        expiration: int = 3600,
    ) -> PresignedUploadResult:
        """generate presigned URL for direct frontend upload

        Args:
            original_filename: original filename (used for extension)
            folder: subfolder in bucket
            filename: custom filename (optional, generates UUID if not provided)
            content_type: MIME type (auto-detected if not provided)
            expiration: URL expiration time in seconds (default 1 hour)

        Returns:
            PresignedUploadResult with upload_url, key, and public_url
        """
        key = self._generate_key(original_filename, folder, filename)

        if not content_type:
            content_type = self._get_content_type(original_filename)

        try:
            async with self._session.client("s3") as s3:
                upload_url = await s3.generate_presigned_url(
                    "put_object",
                    Params={
                        "Bucket": self.bucket,
                        "Key": key,
                        "ContentType": content_type,
                    },
                    ExpiresIn=expiration,
                )

            public_url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"

            logger.info(f"Generated presigned upload URL for: {key}")
            return PresignedUploadResult(
                upload_url=upload_url,
                key=key,
                public_url=public_url,
            )

        except ClientError as e:
            logger.error(f"Failed to generate presigned upload URL: {e}")
            raise


# global instance
s3_client = S3Client()


# convenience functions
async def upload_to_s3(
    file_bytes: bytes,
    original_filename: str,
    folder: str = "",
    filename: Optional[str] = None,
) -> str:
    """quick upload file to S3 asynchronously

    Args:
        file_bytes: file content
        original_filename: original filename
        folder: subfolder in bucket
        filename: custom filename (optional)

    Returns:
        public URL
    """
    return await s3_client.upload_file(file_bytes, original_filename, folder, filename)


async def delete_from_s3(key_or_url: str) -> bool:
    """quick delete file from S3 asynchronously

    Args:
        key_or_url: S3 key or URL

    Returns:
        True if deleted
    """
    return await s3_client.delete_file(key_or_url)


async def get_presigned_url(
    key_or_url: str,
    expiration: int = 3600,
) -> str:
    """generate presigned URL from S3 key or URL

    Args:
        key_or_url: S3 object key or full URL
        expiration: URL expiration time in seconds (default 1 hour)

    Returns:
        presigned URL for accessing the file
    """
    key = s3_client.extract_key(key_or_url)
    return await s3_client.generate_presigned_url(key, expiration)


async def convert_to_presigned_url(
    url: Optional[str],
    expiration: int = 3600,
) -> Optional[str]:
    """convert S3 URL to presigned URL if applicable

    Args:
        url: S3 URL or None
        expiration: URL expiration time in seconds

    Returns:
        presigned URL or None if input is None
    """
    if not url:
        return None
    # only convert URLs from our S3 bucket
    if settings.AWS_S3_BUCKET in url:
        return await get_presigned_url(url, expiration)
    return url


async def download_from_s3(key_or_url: str) -> bytes:
    """download file from S3 to memory asynchronously

    Args:
        key_or_url: S3 object key or full URL

    Returns:
        file content as bytes

    Example:
        # Download and parse PDF
        file_bytes = await download_from_s3("uploads/documents/report.pdf")
        doc = parse_pdf_bytes(file_bytes)

        # Download and parse Excel
        file_bytes = await download_from_s3("https://bucket.s3.region.amazonaws.com/data.xlsx")
        doc = parse_excel_bytes(file_bytes)
    """
    return await s3_client.download_file(key_or_url)


async def get_presigned_upload_url(
    original_filename: str,
    folder: str = "",
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    expiration: int = 3600,
) -> PresignedUploadResult:
    """generate presigned URL for direct frontend upload

    Args:
        original_filename: original filename (used for extension and content type)
        folder: subfolder in bucket (e.g., "images", "documents")
        filename: custom filename (optional, generates UUID if not provided)
        content_type: MIME type (auto-detected if not provided)
        expiration: URL expiration time in seconds (default 1 hour)

    Returns:
        PresignedUploadResult with:
        - upload_url: presigned URL for PUT request
        - key: S3 object key
        - public_url: public URL after upload

    Example:
        # Backend: Generate presigned URL
        result = await get_presigned_upload_url("photo.jpg", folder="avatars")

        # Frontend: Upload directly to S3
        # fetch(result.upload_url, {
        #     method: 'PUT',
        #     body: file,
        #     headers: { 'Content-Type': 'image/jpeg' }
        # })
    """
    return await s3_client.generate_presigned_upload_url(
        original_filename, folder, filename, content_type, expiration
    )
