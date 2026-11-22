# SPDX-License-Identifier: AGPL-3.0-or-later
"""optional protein target per kg of body weight

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-22 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import annona_server.db.types

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_profile", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "protein_g_per_kg", annona_server.db.types.DecimalString(length=40), nullable=True
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("user_profile", schema=None) as batch_op:
        batch_op.drop_column("protein_g_per_kg")
