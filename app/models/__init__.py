"""Model registration point.

Import every ORM model here so Alembic target_metadata (Base.metadata) can see it.
Register each new model below or autogenerate will treat its table as missing.
"""

from app.models.base import Base
from app.models.platform import EventConsumed, IdempotencyRecord, OutboxEvent

# from app.models.user import User  # noqa: E402,F401  # Register new models here.

__all__ = ["Base", "EventConsumed", "IdempotencyRecord", "OutboxEvent"]
