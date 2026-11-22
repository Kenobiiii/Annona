# SPDX-License-Identifier: AGPL-3.0-or-later
"""receipt aliases: names printed on receipts, learned from confirmations

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-23 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import annona_server.db.types

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "receipt_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.String(), nullable=True),
        sa.Column("normalized_text", sa.String(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("created_at", annona_server.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "store_id", "normalized_text"),
    )
    with op.batch_alter_table("receipt_alias", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_receipt_alias_household_id"), ["household_id"])


def downgrade() -> None:
    with op.batch_alter_table("receipt_alias", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_receipt_alias_household_id"))
    op.drop_table("receipt_alias")
