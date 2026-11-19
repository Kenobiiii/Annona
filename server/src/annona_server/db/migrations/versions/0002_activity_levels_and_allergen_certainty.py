# SPDX-License-Identifier: AGPL-3.0-or-later
"""activity levels and allergen certainty

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19 18:50:01.408106
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Old five activity levels -> the four categories of the National Academies (2023).
ACTIVITY_UP = {
    "sedentary": "inactive",
    "light": "low_active",
    "moderate": "active",
    "active": "active",
    "very_active": "very_active",
}
ACTIVITY_DOWN = {
    "inactive": "sedentary",
    "low_active": "light",
    "active": "moderate",
    "very_active": "very_active",
}


def _remap_activity(mapping: dict[str, str]) -> None:
    profile = sa.table("user_profile", sa.column("activity", sa.String))
    for old, new in mapping.items():
        op.execute(profile.update().where(profile.c.activity == old).values(activity=new))


def upgrade() -> None:
    with op.batch_alter_table("product", schema=None) as batch_op:
        batch_op.alter_column("allergens", existing_type=sqlite.JSON(), nullable=True)

    with op.batch_alter_table("user_profile", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "allergies_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )

    _remap_activity(ACTIVITY_UP)


def downgrade() -> None:
    _remap_activity(ACTIVITY_DOWN)

    with op.batch_alter_table("user_profile", schema=None) as batch_op:
        batch_op.drop_column("allergies_confirmed")

    # Lossy: "unknown" allergens (NULL) become an empty list.
    op.execute("UPDATE product SET allergens = '[]' WHERE allergens IS NULL")
    with op.batch_alter_table("product", schema=None) as batch_op:
        batch_op.alter_column("allergens", existing_type=sqlite.JSON(), nullable=False)
