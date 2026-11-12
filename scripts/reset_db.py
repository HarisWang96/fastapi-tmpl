"""
Development database reset script.
This script drops and recreates all tables - USE ONLY IN DEVELOPMENT!
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.database import Base

# Import all models here to register them with Base.metadata
# Example:
# from app.models import User, Item


async def reset_database():
    """Drop and recreate all tables in the schema."""

    print(
        f"⚠️  WARNING: This will DELETE ALL DATA in schema '{settings.DATABASE_SCHEMA}'!"
    )
    print(f"Database: {settings.DATABASE_URL.split('@')[-1]}")

    confirm = input("\nType 'yes' to confirm: ")
    if confirm.lower() != "yes":
        print("Cancelled.")
        return

    engine = create_async_engine(settings.DATABASE_URL, echo=True)

    async with engine.begin() as conn:
        print(f"\n🗑️  Dropping schema '{settings.DATABASE_SCHEMA}'...")
        await conn.execute(
            text(f"DROP SCHEMA IF EXISTS {settings.DATABASE_SCHEMA} CASCADE")
        )
        print(f"\n📁 Creating schema '{settings.DATABASE_SCHEMA}'...")
        await conn.execute(text(f"CREATE SCHEMA {settings.DATABASE_SCHEMA}"))
        print("\n🔨 Creating all tables...")
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()
    print("\n✅ Database reset complete!")


if __name__ == "__main__":
    asyncio.run(reset_database())
