"""application configuration module"""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """application configuration class"""

    # application basic configuration
    APP_NAME: str = "fastapi-service"
    APP_VERSION: str = "0.1.0"
    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_FORMAT: Literal["text", "json"] = "text"
    LOG_DIR: str = "./logs"
    LOG_TO_FILE: bool = True
    TIMEZONE: str = "Asia/Shanghai"
    METRICS_TOKEN: SecretStr | None = None

    # database configuration
    DATABASE_URL: str
    DATABASE_SCHEMA: str = "public"  # database schema name
    # database connection pool settings
    DATABASE_POOL_SIZE: int = 5  # number of connections to keep open
    DATABASE_MAX_OVERFLOW: int = 10  # additional connections when pool is exhausted
    DATABASE_POOL_TIMEOUT: int = 30  # seconds to wait for available connection
    DATABASE_POOL_RECYCLE: int = (
        1800  # recycle connections after N seconds (default 30min)
    )
    DATABASE_POOL_PRE_PING: bool = True  # verify connection is alive before using

    # server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Redis configuration
    REDIS_URL: str
    REDIS_MAX_CONNECTIONS: int = 100
    REDIS_CONNECT_TIMEOUT: float = 1.0
    REDIS_TIMEOUT: float = 2.0

    TRUSTED_PROXY_TOKEN: SecretStr | None = None
    AUTHZ_BASE_URL: str = "http://authz-svc:8000"
    AUTHZ_TIMEOUT_SECONDS: float = Field(default=3, gt=0)
    AUTHZ_CACHE_TTL_SECONDS: int = Field(default=30, ge=0, le=300)
    INTERNAL_API_TOKEN: SecretStr | None = None

    IDEMPOTENCY_TTL_SECONDS: int = Field(default=86400, ge=60)
    IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS: int = Field(default=3600, ge=0)
    EVENT_ENABLED: bool = False
    EVENT_BROKER_URL: SecretStr | None = None
    EVENT_EXCHANGE: str = "service.events"
    EVENT_DLX_EXCHANGE: str = "service.events.dlx"
    EVENT_QUEUE: str = ""
    OUTBOX_POLL_INTERVAL_SECONDS: float = Field(default=1, gt=0)
    OUTBOX_LEASE_SECONDS: int = Field(default=30, ge=5)
    OUTBOX_MAX_ATTEMPTS: int = Field(default=10, ge=1)
    CONSUMER_PREFETCH: int = Field(default=10, ge=1, le=1000)
    CONSUMER_MAX_RETRIES: int = Field(default=3, ge=0)
    CONSUMER_RETRY_BACKOFF_SECONDS: float = Field(default=1, ge=0)

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    CORS_ALLOW_CREDENTIALS: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator(
        "METRICS_TOKEN",
        "TRUSTED_PROXY_TOKEN",
        "INTERNAL_API_TOKEN",
        "EVENT_BROKER_URL",
        mode="before",
    )
    @classmethod
    def _blank_secret_as_none(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def _validate_runtime_config(self) -> "Settings":
        try:
            ZoneInfo(self.TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Invalid TIMEZONE: {self.TIMEZONE!r}") from exc
        if self.APP_ENV == "prod":
            if self.METRICS_TOKEN is None:
                raise ValueError("METRICS_TOKEN is required in production")
            if self.INTERNAL_API_TOKEN is None:
                raise ValueError("INTERNAL_API_TOKEN is required in production")
        if self.EVENT_ENABLED and self.EVENT_BROKER_URL is None:
            raise ValueError("EVENT_BROKER_URL is required when EVENT_ENABLED=true")
        return self


settings = Settings()
