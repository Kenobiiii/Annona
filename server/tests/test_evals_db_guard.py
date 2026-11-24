# SPDX-License-Identifier: AGPL-3.0-or-later
"""Eval commands read the budget from the configured database but must never migrate it."""

import sys
from pathlib import Path

import pytest

from annona_server.db import migrate
from annona_server.evals import __main__ as evals_cli


def _run_cli(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["python -m annona_server.evals", *argv])
    evals_cli.main()


def test_current_revision_reads_without_creating_or_migrating(tmp_path: Path):
    path = tmp_path / "missing.db"
    url = f"sqlite:///{path}"
    assert migrate.current_revision(url) is None
    assert not path.exists()

    migrate.upgrade(url, "0001")
    assert migrate.current_revision(url) == "0001"
    assert migrate.current_revision(url) == "0001"  # reading twice changes nothing
    migrate.upgrade(url)
    assert migrate.current_revision(url) == migrate.head_revision()


@pytest.mark.parametrize("command", ["receipt-run", "agent-run", "plan-run", "run"])
def test_a_dry_run_refuses_an_outdated_database_and_leaves_it_alone(
    command, tmp_path, monkeypatch, capsys
):
    url = f"sqlite:///{tmp_path / 'annona.db'}"
    migrate.upgrade(url, "0001")
    monkeypatch.setenv("ANNONA_DATABASE_URL", url)
    monkeypatch.setattr(evals_cli, "_prices", lambda model: (1, 1))
    monkeypatch.setattr(evals_cli, "load_env", lambda: None)

    with pytest.raises(SystemExit) as stop:
        _run_cli(monkeypatch, command, *(["--limit", "1"] if command == "run" else []))

    assert "never changes your database" in str(stop.value.code)
    assert migrate.current_revision(url) == "0001"
    assert "estimated cost" not in capsys.readouterr().out


def test_a_missing_database_is_refused_and_not_created(tmp_path, monkeypatch):
    path = tmp_path / "annona.db"
    monkeypatch.setenv("ANNONA_DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setattr(evals_cli, "_prices", lambda model: (1, 1))
    monkeypatch.setattr(evals_cli, "load_env", lambda: None)

    with pytest.raises(SystemExit):
        _run_cli(monkeypatch, "receipt-run", "--n", "3")
    assert not path.exists()


def test_a_dry_run_on_an_up_to_date_database_still_shows_the_cost_guard(
    tmp_path, monkeypatch, capsys
):
    url = f"sqlite:///{tmp_path / 'annona.db'}"
    migrate.upgrade(url)
    monkeypatch.setenv("ANNONA_DATABASE_URL", url)
    monkeypatch.setattr(evals_cli, "_prices", lambda model: (0, 0))
    monkeypatch.setattr(evals_cli, "load_env", lambda: None)

    _run_cli(monkeypatch, "receipt-run", "--n", "3")

    out = capsys.readouterr().out
    assert "eval budget $" in out
    assert "dry run: add --yes to spend" in out
