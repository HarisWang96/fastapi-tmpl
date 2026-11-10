"""Platform tables shared by every service: idempotency, outbox and event dedupe.

These are owned by the service that runs the migration; they never cross a
database boundary. Business code writes outbox rows in the same transaction as
the state change, and reads/writes idempotency rows around the request.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.models.base import Base

# BIGINT on MySQL, INTEGER on SQLite so unit tests can use autoincrement.
_PK = BigInteger().with_variant(Integer, "sqlite")


class IdempotencyRecord(Base):
    """One request fingerprint and its stored response.

    `scope` isolates callers and endpoints so the same client key can be reused
    on different routes without colliding.
    """

    __tablename__ = "sys_idempotency"
    __table_args__ = (
        UniqueConstraint("scope", "idem_key", name="uq_sys_idempotency_scope_key"),
        Index("ix_sys_idempotency_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    idem_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 1=in progress, 2=completed
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class OutboxEvent(Base):
    """Transactional outbox row; the relay publishes it and marks it done."""

    __tablename__ = "sys_outbox"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_sys_outbox_event_id"),
        Index("ix_sys_outbox_dispatch", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    headers: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    # 0=pending, 1=publishing, 2=published, 3=failed
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EventConsumed(Base):
    """Dedupe marker for at-least-once delivery; inserted after a handler succeeds."""

    __tablename__ = "sys_event_consumed"
    __table_args__ = (UniqueConstraint("event_id", name="uq_sys_event_consumed_event_id"),)

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
