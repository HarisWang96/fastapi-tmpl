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
# from app.models import User, Item  # noqa: F401


async def reset_database():
    """Drop and recreate all tables in the schema."""

    print(f"⚠️  WARNING: This will DELETE ALL DATA in schema '{settings.DATABASE_SCHEMA}'!")
    print(f"Database: {settings.DATABASE_URL.split('@')[-1]}")

    confirm = input("\nType 'yes' to confirm: ")
    if confirm.lower() != "yes":
        print("Cancelled.")
        return

    engine = create_async_engine(settings.DATABASE_URL, echo=True)

    async with engine.begin() as conn:
        # Drop schema cascade (removes all tables, types, etc.)
        print(f"\n🗑️  Dropping schema '{settings.DATABASE_SCHEMA}'...")
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {settings.DATABASE_SCHEMA} CASCADE"))

        # Create schema
        print(f"\n📁 Creating schema '{settings.DATABASE_SCHEMA}'...")
        await conn.execute(text(f"CREATE SCHEMA {settings.DATABASE_SCHEMA}"))

        # Create all tables
        print("\n🔨 Creating all tables...")
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()

    print("\n✅ Database reset complete!")


async def reset_alembic():
    """Reset alembic version table and delete migration files."""

    engine = create_async_engine(settings.DATABASE_URL)

    async with engine.begin() as conn:
        # Drop alembic_version table
        print("🗑️  Dropping alembic_version table...")
        await conn.execute(
            text(f"DROP TABLE IF EXISTS {settings.DATABASE_SCHEMA}.alembic_version")
        )

    await engine.dispose()

    # Delete migration files
    versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*.py"))

    if migration_files:
        print(f"🗑️  Deleting {len(migration_files)} migration file(s)...")
        for f in migration_files:
            if f.name != "__pycache__":
                f.unlink()
                print(f"   Deleted: {f.name}")

    print("\n✅ Alembic reset complete!")
    print("   Run 'uv run alembic revision --autogenerate -m \"initial\"' to create fresh migration")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--alembic-only":
        asyncio.run(reset_alembic())
    else:
        asyncio.run(reset_database())
