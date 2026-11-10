"""Application configuration loaded from environment variables or .env.

This service does not implement authentication. JWT issuance and validation
belong to identity-svc; downstream services only read gateway-injected identity
headers (see Caller in app/api/deps.py). Fine-grained authorization is enforced
in the service against authz-svc (see app/api/authz_deps.py).
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
    # json writes one structured line per record for collectors; text stays human-readable.
    LOG_FORMAT: Literal["text", "json"] = "text"
    # When set, /metrics requires X-Metrics-Token or a matching Bearer token.
    METRICS_TOKEN: SecretStr | None = None

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

    # Service-side authorization (PEP): routes declare permission codes and ask
    # authz-svc (PDP) for the decision. INTERNAL_API_TOKEN authenticates this
    # service to authz-svc; it must match authz-svc's INTERNAL_API_TOKEN.
    AUTHZ_BASE_URL: str = "http://authz-svc:8000"
    AUTHZ_TIMEOUT_SECONDS: float = Field(default=3.0, gt=0)
    # In-process decision cache. Bounds how long a revoked permission can stay
    # effective; set 0 to disable caching. Keep it short for admin operations.
    AUTHZ_CACHE_TTL_SECONDS: int = Field(default=30, ge=0, le=300)
    INTERNAL_API_TOKEN: SecretStr | None = None

    # ---- Idempotency (write endpoints that accept Idempotency-Key) ----
    IDEMPOTENCY_TTL_SECONDS: int = Field(default=86_400, ge=60)
    # Expired rows are purged by a background task; 0 disables the cleaner.
    IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS: int = Field(default=3_600, ge=0)

    # ---- Transactional outbox + RabbitMQ event bus ----
    EVENT_ENABLED: bool = False
    EVENT_BROKER_URL: SecretStr | None = None
    EVENT_EXCHANGE: str = "meihao.events"
    EVENT_DLX_EXCHANGE: str = "meihao.events.dlx"
    # Consumer queue name; defaults to "<APP_NAME>.events" when empty.
    EVENT_QUEUE: str = ""
    OUTBOX_POLL_INTERVAL_SECONDS: float = Field(default=1.0, gt=0)
    OUTBOX_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)
    OUTBOX_LEASE_SECONDS: int = Field(default=30, ge=5)
    OUTBOX_MAX_ATTEMPTS: int = Field(default=10, ge=1)
    CONSUMER_PREFETCH: int = Field(default=10, ge=1, le=1000)
    CONSUMER_MAX_RETRIES: int = Field(default=3, ge=0)
    CONSUMER_RETRY_BACKOFF_SECONDS: float = Field(default=1.0, ge=0)

    @field_validator(
        "TRUSTED_PROXY_TOKEN",
        "INTERNAL_API_TOKEN",
        "METRICS_TOKEN",
        "EVENT_BROKER_URL",
        mode="before",
    )
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
        if self.APP_ENV == "prod" and self.INTERNAL_API_TOKEN is None:
            raise ValueError("生产环境必须配置 INTERNAL_API_TOKEN，以调用 authz-svc")
        if self.APP_ENV == "prod" and self.METRICS_TOKEN is None:
            raise ValueError("生产环境必须配置 METRICS_TOKEN，以保护 /metrics")
        if self.EVENT_ENABLED and self.EVENT_BROKER_URL is None:
            raise ValueError("EVENT_ENABLED=true 时必须配置 EVENT_BROKER_URL")
        return self


settings = Settings()
