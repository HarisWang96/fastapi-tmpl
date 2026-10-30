"""Application configuration loaded from environment variables or .env.

This service does not implement authentication. JWT issuance and validation
belong to the auth service; downstream services only read gateway-injected
identity headers (see Caller in app/api/deps.py).
"""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MysqlConfig(BaseModel):
    host: str
    port: int = 3306
    user: str
    password: SecretStr
    database: str


class RedisConfig(BaseModel):
    host: str
    port: int = 6379
    username: str | None = None
    password: SecretStr


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        # Prevent validation errors from echoing secrets into logs.
        hide_input_in_errors=True,
    )

    APP_NAME: str = "fastapi-svc"
    APP_VERSION: str = "0.1.0"
    # Default to production behavior: hide docs and example endpoints unless configured otherwise.
    APP_ENV: Literal["dev", "test", "prod"] = "prod"
    DEBUG: bool = False

    API_PREFIX: str = "/api/v1"
    # Deny cross-origin requests by default; configure origins per environment.
    CORS_ORIGINS: list[str] = Field(default_factory=list)
    CORS_ALLOW_CREDENTIALS: bool = False

    LOG_DIR: str = "./logs"
    LOG_LEVEL: str = "INFO"
    LOG_RETENTION: str = "7 days"
    LOG_TO_FILE: bool = True

    # Business-local naive timestamps use this zone, independent of the container timezone.
    TIMEZONE: str = "Asia/Shanghai"

    DB_CHARSET: str = "utf8mb4"
    MYSQL_DATABASES: dict[str, MysqlConfig] = Field(default_factory=dict)
    MYSQL_POOL_MAX_CONNECTIONS: int = Field(default=20, ge=1)
    MYSQL_POOL_TIMEOUT: int = Field(default=10, ge=1)
    MYSQL_POOL_RECYCLE: int = Field(default=1800, ge=1)
    MYSQL_CONNECT_TIMEOUT: int = Field(default=5, ge=1)
    MYSQL_READ_TIMEOUT: int = Field(default=30, ge=1)
    MYSQL_WRITE_TIMEOUT: int = Field(default=30, ge=1)

    REDIS_DATABASES: dict[str, RedisConfig] = Field(default_factory=dict)
    REDIS_DEFAULT_DB: int = 0
    REDIS_MAX_CONNECTIONS: int = Field(default=100, ge=1)
    REDIS_CONNECT_TIMEOUT: float = Field(default=1.0, gt=0)
    REDIS_TIMEOUT: float = Field(default=2.0, gt=0)

    # Readiness only depends on explicitly listed services. Use [] for a service
    # that has no hard runtime dependency; available values are mysql and redis.
    READINESS_DEPENDENCIES: list[Literal["mysql", "redis"]] = Field(
        default_factory=lambda: ["mysql", "redis"]
    )

    # The gateway injects identity headers after authentication. Network policy
    # must restrict ingress to the gateway; this token is an additional check.
    TRUSTED_PROXY_TOKEN: SecretStr | None = None

    @field_validator("TRUSTED_PROXY_TOKEN", mode="before")
    @classmethod
    def _blank_token_as_none(cls, value: object) -> object:
        # Normalize empty Kubernetes Secrets or .env values to None.
        return None if value == "" else value

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        try:
            ZoneInfo(self.TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TIMEZONE 无效: {self.TIMEZONE!r}") from exc
        if self.APP_ENV == "prod" and self.TRUSTED_PROXY_TOKEN is None:
            raise ValueError("生产环境必须配置 TRUSTED_PROXY_TOKEN，以保护网关注入的身份头")
        return self


settings = Settings()
