# SPDX-License-Identifier: AGPL-3.0-or-later
"""pending actions: changes proposed by the chat agent, waiting for confirmation

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-24 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import annona_server.db.types

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_action",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", annona_server.db.types.UTCDateTime(), nullable=False),
        sa.Column("resolved_at", annona_server.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("pending_action", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pending_action_household_id"), ["household_id"])


def downgrade() -> None:
    with op.batch_alter_table("pending_action", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pending_action_household_id"))
    op.drop_table("pending_action")
