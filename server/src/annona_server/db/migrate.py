# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run Alembic programmatically, without needing an ``alembic.ini`` in the working directory."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from .engine import database_url

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
