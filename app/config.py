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
    DATABASE_URL: str
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
    REDIS_URL: str
    REDIS_MAX_CONNECTIONS: int = 100
    REDIS_CONNECT_TIMEOUT: float = 1.0
    REDIS_TIMEOUT: float = 2.0

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    CORS_ALLOW_CREDENTIALS: bool = False

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore",
    }


settings = Settings()
