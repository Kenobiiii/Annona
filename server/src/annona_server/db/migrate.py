# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run Alembic programmatically, without needing an ``alembic.ini`` in the working directory."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from .engine import database_url, make_engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url or database_url())
    return cfg


def upgrade(url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str | None = None, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)


def head_revision() -> str:
    """The newest migration this code knows about."""
    head = ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()
    assert head is not None
    return head


def current_revision(url: str | None = None) -> str | None:
    """The database's migration, read without changing anything (``None``: empty or missing).

    A missing SQLite file is not created.
    """
    url = url or database_url()
    sqlite_file = url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:")
    if sqlite_file and not Path(url.removeprefix("sqlite:///")).exists():
        return None
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
