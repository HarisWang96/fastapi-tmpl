"""platform tables: idempotency, outbox, event dedupe

Revision ID: 0001_platform
Revises:
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_platform"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sys_idempotency",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("idem_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sys_idempotency"),
        sa.UniqueConstraint("scope", "idem_key", name="uq_sys_idempotency_scope_key"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_sys_idempotency_expires_at",
        "sys_idempotency",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "sys_outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_sys_outbox"),
        sa.UniqueConstraint("event_id", name="uq_sys_outbox_event_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_sys_outbox_dispatch",
        "sys_outbox",
        ["status", "next_attempt_at"],
        unique=False,
    )

    op.create_table(
        "sys_event_consumed",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sys_event_consumed"),
        sa.UniqueConstraint("event_id", name="uq_sys_event_consumed_event_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )


def downgrade() -> None:
    op.drop_table("sys_event_consumed")
    op.drop_index("ix_sys_outbox_dispatch", table_name="sys_outbox")
    op.drop_table("sys_outbox")
    op.drop_index("ix_sys_idempotency_expires_at", table_name="sys_idempotency")
    op.drop_table("sys_idempotency")
