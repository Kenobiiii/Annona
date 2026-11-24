# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run Alembic programmatically, without needing an ``alembic.ini`` in the working directory.

Who may change the database's structure: only the server at start-up and
``python -m annona_server.db upgrade`` (both back the SQLite file up first, see
:func:`upgrade_with_backup`), and ``seed`` when it creates a brand-new database. Every other
command only checks the revision with :func:`require_head` and stops if it is not current.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from .engine import database_url, make_engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BACKUP_FOLDER = "backups"

log = logging.getLogger("annona.db")


class OutdatedDatabaseError(RuntimeError):
    """The database is not at the migration this code needs, and this command will not migrate."""

    def __init__(self, url: str, current: str | None, head: str) -> None:
        self.url, self.current, self.head = url, current, head
        super().__init__(
            f"the database {url} is at migration {current or 'none'}, this code needs {head}.\n"
            "This command never changes your database's structure. Start the server (it backs "
            "the database up, then migrates) or run `python -m annona_server.db upgrade`."
        )


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


def sqlite_path(url: str) -> Path | None:
    """The file behind a SQLite URL (``None`` for other databases and in-memory SQLite)."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or parsed.database in (None, "", ":memory:"):
        return None
    return Path(parsed.database)


def current_revision(url: str | None = None) -> str | None:
    """The database's migration, read without changing anything (``None``: empty or missing).

    A missing SQLite file is not created.
    """
    url = url or database_url()
    path = sqlite_path(url)
    if path is not None and not path.exists():
        return None
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def require_head(url: str | None = None) -> None:
    """Raise :class:`OutdatedDatabaseError` unless the database is at the latest migration."""
    url = url or database_url()
    current, head = current_revision(url), head_revision()
    if current != head:
        raise OutdatedDatabaseError(url, current, head)


def exit_if_outdated(url: str | None = None) -> None:
    """:func:`require_head` for command-line tools: a clear message instead of a traceback."""
    try:
        require_head(url)
    except OutdatedDatabaseError as error:
        sys.exit(str(error))


def backup_sqlite(url: str, label: str) -> Path | None:
    """Copy the SQLite file to ``<its folder>/backups/<name>-<label>-<UTC time>.db``.

    Uses SQLite's own backup, so the copy is consistent even if another process has it open.
    Returns ``None`` when there is nothing to copy (not SQLite, or no file yet).
    """
    path = sqlite_path(url)
    if path is None or not path.exists():
        return None
    folder = path.parent / BACKUP_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = folder / f"{path.stem}-{label}-{stamp}.db"
    source, copy = sqlite3.connect(path), sqlite3.connect(target)
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    return target


def upgrade_with_backup(url: str | None = None) -> Path | None:
    """Migrate to head, backing the database up first if it holds an older migration.

    Returns the backup's path (``None`` if nothing needed migrating or the database was new).
    """
    url = url or database_url()
    current, head = current_revision(url), head_revision()
    backup = None
    if current is not None and current != head:
        backup = backup_sqlite(url, current)
        if backup is None:
            log.warning("no automatic backup for %s: back it up yourself", make_url(url).drivername)
        else:
            log.warning("database backed up to %s before migrating %s -> %s", backup, current, head)
    upgrade(url)
    return backup


def create_or_require_head(url: str | None = None) -> None:
    """Build a brand-new (missing or empty) database; otherwise behave like :func:`require_head`."""
    url = url or database_url()
    if current_revision(url) is None and not _has_tables(url):
        upgrade(url)
        return
    require_head(url)


def _has_tables(url: str) -> bool:
    engine = make_engine(url)
    try:
        return bool(inspect(engine).get_table_names())
    finally:
        engine.dispose()
