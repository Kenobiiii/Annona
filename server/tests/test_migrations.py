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
    "off_cache",
    "llm_cache",
    "llm_usage",
    "job",
    "receipt_alias",
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


def test_0002_maps_activity_levels_and_keeps_data(db_url):
    from sqlalchemy import text

    migrate.upgrade(db_url, "0001")
    engine = make_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO household (id, name, weekly_budget_cents, currency) "
                    "VALUES (1, 'Home', 5000, 'EUR')"
                )
            )
            for i, level in enumerate(["sedentary", "light", "moderate", "active", "very_active"]):
                conn.execute(
                    text(
                        "INSERT INTO user_profile (household_id, name, sex, birth_date, height_cm,"
                        " weight_kg, activity, goal, diet, allergies) VALUES (1, :n, 'male',"
                        " '1990-01-01', '180', '80', :a, 'maintain', 'omnivore', '[]')"
                    ),
                    {"n": f"p{i}", "a": level},
                )
        migrate.upgrade(db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT activity, allergies_confirmed FROM user_profile ORDER BY id")
            ).all()
        assert [r[0] for r in rows] == ["inactive", "low_active", "active", "active", "very_active"]
        assert all(r[1] == 0 for r in rows)  # existing users must confirm allergies

        migrate.downgrade(db_url, "0001")
        with engine.connect() as conn:
            back = conn.execute(text("SELECT activity FROM user_profile ORDER BY id")).scalars()
            assert list(back) == ["sedentary", "light", "moderate", "moderate", "very_active"]
    finally:
        engine.dispose()
