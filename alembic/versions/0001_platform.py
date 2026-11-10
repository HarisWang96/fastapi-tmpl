"""request idempotency and transactional outbox

Revision ID: 0001_platform
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.config import settings

revision: str = "0001_platform"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sys_idempotency",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("idem_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", sa.JSON()),
        sa.Column("response_headers", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scope", "idem_key", name="uq_sys_idempotency_scope_key"),
        schema=settings.DATABASE_SCHEMA,
    )
    op.create_index(
        "ix_sys_idempotency_expires_at",
        "sys_idempotency",
        ["expires_at"],
        schema=settings.DATABASE_SCHEMA,
    )
    op.create_table(
        "sys_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON()),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        schema=settings.DATABASE_SCHEMA,
    )
    op.create_index(
        "ix_sys_outbox_dispatch",
        "sys_outbox",
        ["status", "next_attempt_at"],
        schema=settings.DATABASE_SCHEMA,
    )
    op.create_table(
        "sys_event_consumed",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        schema=settings.DATABASE_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("sys_event_consumed", schema=settings.DATABASE_SCHEMA)
    op.drop_index(
        "ix_sys_outbox_dispatch",
        table_name="sys_outbox",
        schema=settings.DATABASE_SCHEMA,
    )
    op.drop_table("sys_outbox", schema=settings.DATABASE_SCHEMA)
    op.drop_index(
        "ix_sys_idempotency_expires_at",
        table_name="sys_idempotency",
        schema=settings.DATABASE_SCHEMA,
    )
    op.drop_table("sys_idempotency", schema=settings.DATABASE_SCHEMA)
