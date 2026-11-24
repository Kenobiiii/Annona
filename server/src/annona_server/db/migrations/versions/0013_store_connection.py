# SPDX-License-Identifier: AGPL-3.0-or-later
"""store connections: postal code and accepted notice per household and store plugin

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-24 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import annona_server.db.types

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "store_connection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.String(), nullable=False),
        sa.Column("postal_code", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("notice_accepted_at", annona_server.db.types.UTCDateTime(), nullable=True),
        sa.Column("updated_at", annona_server.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "store_id"),
    )
    with op.batch_alter_table("store_connection", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_store_connection_household_id"), ["household_id"])


def downgrade() -> None:
    with op.batch_alter_table("store_connection", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_store_connection_household_id"))
    op.drop_table("store_connection")
