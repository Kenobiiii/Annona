# SPDX-License-Identifier: AGPL-3.0-or-later
"""shopping item: the product it substitutes

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-23 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("shopping_item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("replaces_product_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_shopping_item_replaces_product", "product", ["replaces_product_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("shopping_item", schema=None) as batch_op:
        batch_op.drop_constraint("fk_shopping_item_replaces_product", type_="foreignkey")
        batch_op.drop_column("replaces_product_id")
