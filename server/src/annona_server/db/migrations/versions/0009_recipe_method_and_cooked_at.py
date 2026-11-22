# SPDX-License-Identifier: AGPL-3.0-or-later
"""detailed recipe method and cooked_at on planned meals

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-22 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import annona_server.db.types

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recipe", schema=None) as batch_op:
        batch_op.add_column(sa.Column("method", sa.JSON(), nullable=False, server_default="[]"))
    with op.batch_alter_table("planned_meal", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("cooked_at", annona_server.db.types.UTCDateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("planned_meal", schema=None) as batch_op:
        batch_op.drop_column("cooked_at")
    with op.batch_alter_table("recipe", schema=None) as batch_op:
        batch_op.drop_column("method")
