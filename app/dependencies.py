"""dependencies module"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db


async def get_database() -> AsyncGenerator[AsyncSession, None]:
    """
    database session dependency
    can be used in routes: db: AsyncSession = Depends(get_database)
    """
    async for session in get_db():
        yield session
