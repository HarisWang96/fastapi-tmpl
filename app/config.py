"""application configuration module"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """application configuration class"""

    # application basic configuration
    APP_NAME: str = "FastAPI async framework"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # database configuration
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/dbname"
    DATABASE_SCHEMA: str = "public"  # database schema name
    # database connection pool settings
    DATABASE_POOL_SIZE: int = 5  # number of connections to keep open
    DATABASE_MAX_OVERFLOW: int = 10  # additional connections when pool is exhausted
    DATABASE_POOL_TIMEOUT: int = 30  # seconds to wait for available connection
    DATABASE_POOL_RECYCLE: int = 1800  # recycle connections after N seconds (default 30min)
    DATABASE_POOL_PRE_PING: bool = True  # verify connection is alive before using

    # server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Redis configuration
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery configuration
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # AWS S3 configuration
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_S3_BUCKET: str = ""
    AWS_S3_PREFIX: str = "uploads"  # file prefix/folder in bucket
    AWS_S3_PRESIGNED_EXPIRATION: int = 3600  # presigned URL expiration in seconds

    # Upload configuration
    UPLOAD_MAX_IMAGE_SIZE: int = 5 * 1024 * 1024  # 5MB
    UPLOAD_ALLOWED_IMAGE_TYPES: str = "image/jpeg,image/png,image/gif,image/webp"

    class Config:
        """Pydantic configuration settings"""

        env_file = ".env"
        case_sensitive = True


settings = Settings()
