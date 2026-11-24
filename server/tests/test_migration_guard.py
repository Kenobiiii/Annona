# SPDX-License-Identifier: AGPL-3.0-or-later
"""Only the server and ``db upgrade`` migrate the configured database, and they back it up first."""

import logging
import sqlite3
import sys
from pathlib import Path

import pytest

from annona_server.db import migrate

OLD = "0001"


def _old_db(tmp_path: Path) -> tuple[str, Path]:
    path = tmp_path / "annona.db"
    url = f"sqlite:///{path}"
    migrate.upgrade(url, OLD)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO household (id, name, weekly_budget_cents, currency) "
            "VALUES (1, 'Home', 5000, 'EUR')"
        )
    return url, path


def _backups(path: Path) -> list[Path]:
    return sorted((path.parent / migrate.BACKUP_FOLDER).glob("*.db"))


def test_upgrade_with_backup_copies_the_old_database_before_migrating(tmp_path):
    url, path = _old_db(tmp_path)

    backup = migrate.upgrade_with_backup(url)

    assert migrate.current_revision(url) == migrate.head_revision()
    assert backup is not None and _backups(path) == [backup]
    assert backup.name.startswith(f"annona-{OLD}-")
    assert migrate.current_revision(f"sqlite:///{backup}") == OLD
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT name FROM household").fetchall() == [("Home",)]


def test_upgrade_with_backup_skips_the_copy_when_nothing_changes(tmp_path):
    path = tmp_path / "annona.db"
    url = f"sqlite:///{path}"
    assert migrate.upgrade_with_backup(url) is None  # brand new: nothing to protect
    assert migrate.upgrade_with_backup(url) is None  # already current
    assert migrate.current_revision(url) == migrate.head_revision()
    assert _backups(path) == []


def test_create_or_require_head_creates_only_new_databases(tmp_path):
    new = f"sqlite:///{tmp_path / 'new.db'}"
    migrate.create_or_require_head(new)
    assert migrate.current_revision(new) == migrate.head_revision()
    migrate.create_or_require_head(new)  # current: fine

    url, _ = _old_db(tmp_path)
    with pytest.raises(migrate.OutdatedDatabaseError):
        migrate.create_or_require_head(url)
    assert migrate.current_revision(url) == OLD


def test_a_database_with_tables_but_no_revision_is_not_touched(tmp_path):
    path = tmp_path / "foreign.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE something (id INTEGER)")
    with pytest.raises(migrate.OutdatedDatabaseError):
        migrate.create_or_require_head(f"sqlite:///{path}")


def _main(module: str):
    import importlib

    return importlib.import_module(module).main


CHECK_ONLY = [
    ("annona_server.products.__main__", ["search", "leche"]),
    ("annona_server.optimize.__main__", ["--store", "demo"]),
    ("annona_server.planner.__main__", ["--store", "demo", "--week", "2026-11-23"]),
    ("annona_server.ingest.__main__", ["open_prices", "--brand", "Demo", "--limit", "1"]),
    ("annona_server.mcp_server.__main__", []),
    ("annona_server.seed.__main__", []),
]


@pytest.mark.parametrize(("module", "argv"), CHECK_ONLY, ids=[m for m, _ in CHECK_ONLY])
def test_commands_refuse_an_outdated_database(module, argv, tmp_path, monkeypatch):
    url, path = _old_db(tmp_path)
    monkeypatch.setenv("ANNONA_DATABASE_URL", url)
    monkeypatch.setattr(sys, "argv", [module, *argv])
    main = _main(module)
    monkeypatch.setattr(sys.modules[main.__module__], "load_env", lambda: None, raising=False)

    with pytest.raises(SystemExit) as stop:
        main()

    assert "never changes your database" in str(stop.value.code)
    assert migrate.current_revision(url) == OLD
    assert _backups(path) == []


def test_the_scheduler_skips_the_refresh_on_an_outdated_database(tmp_path, monkeypatch, caplog):
    from annona_server import scheduler

    url, _ = _old_db(tmp_path)
    monkeypatch.setenv("ANNONA_DATABASE_URL", url)
    monkeypatch.setattr(scheduler, "refresh", lambda session: pytest.fail("must not refresh"))

    with caplog.at_level(logging.ERROR, logger="annona.scheduler"):
        scheduler.run_once()

    assert "price refresh skipped" in caplog.text
    assert migrate.current_revision(url) == OLD


def test_db_upgrade_command_backs_up_then_migrates(tmp_path, monkeypatch, capsys):
    from annona_server.db.__main__ import main

    url, path = _old_db(tmp_path)
    monkeypatch.setenv("ANNONA_DATABASE_URL", url)
    monkeypatch.setattr(sys, "argv", ["python -m annona_server.db", "upgrade"])

    main()

    assert migrate.current_revision(url) == migrate.head_revision()
    assert f"backup saved: {_backups(path)[0]}" in capsys.readouterr().out


def test_the_server_backs_up_then_migrates_on_start(tmp_path, monkeypatch):
    from annona_server.api.app import create_app

    url, path = _old_db(tmp_path)
    monkeypatch.setenv("ANNONA_DATABASE_URL", url)

    create_app(token="t" * 32)

    assert migrate.current_revision(url) == migrate.head_revision()
    assert len(_backups(path)) == 1
