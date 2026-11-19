# SPDX-License-Identifier: AGPL-3.0-or-later
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlmodel import SQLModel

from annona_server.db import migrate, tables  # noqa: F401
from annona_server.db.engine import make_engine

EXPECTED_TABLES = {
    "household",
    "user_profile",
    "equipment",
    "product",
    "price",
    "pantry_item",
    "recipe",
    "recipe_ingredient",
    "meal_plan",
    "planned_meal",
    "shopping_list",
    "shopping_item",
    "receipt",
    "receipt_line",
}


def _tables(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade(db_url):
    migrate.upgrade(db_url)
    assert _tables(db_url) == EXPECTED_TABLES
    migrate.downgrade(db_url)
    assert _tables(db_url) == set()
    migrate.upgrade(db_url)
    assert _tables(db_url) == EXPECTED_TABLES


def test_migrations_match_models(db_url):
    """Fails if a table changed without a new migration."""
    migrate.upgrade(db_url)
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            diff = compare_metadata(ctx, SQLModel.metadata)
    finally:
        engine.dispose()
    assert diff == []
