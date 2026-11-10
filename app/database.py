"""database connection module"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models.platform import Base  # noqa: F401 - public model registration point

# create asynchronous database engine with connection pool settings
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    # Connection pool settings from environment
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    pool_recycle=settings.DATABASE_POOL_RECYCLE,
    pool_pre_ping=settings.DATABASE_POOL_PRE_PING,
)

# create asynchronous session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# application models inherit from the shared Base above; schema is controlled by
# DATABASE_SCHEMA and Alembic so runtime startup never creates tables.


async def get_db() -> AsyncGenerator[AsyncSession]:
    """
    get database session dependency injection function
    can be used in routes: db: AsyncSession = Depends(get_db)
    """
    async with AsyncSessionLocal() as session:
        # Transaction boundaries belong to the application/service layer.
        yield session


async def close_db():
    """close database connection"""
    await engine.dispose()
