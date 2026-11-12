"""example orders business table

Revision ID: 0002_orders
Revises: 0001_platform
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.config import settings

revision: str = "0002_orders"
down_revision: str | None = "0001_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.String(100), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=settings.DATABASE_SCHEMA,
    )
    op.create_index(
        "ix_orders_customer_id",
        "orders",
        ["customer_id"],
        schema=settings.DATABASE_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orders_customer_id", table_name="orders", schema=settings.DATABASE_SCHEMA
    )
    op.drop_table("orders", schema=settings.DATABASE_SCHEMA)
