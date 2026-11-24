# SPDX-License-Identifier: AGPL-3.0-or-later
"""Daily price refresh at ``ANNONA_REFRESH_AT`` (UTC, default 04:30, DeepSeek/most APIs off-peak).

Run as its own process (the ``scheduler`` service in docker-compose)::

    python -m annona_server.scheduler            # loop forever
    python -m annona_server.scheduler --once     # refresh now and exit
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import UTC, datetime, timedelta

from .config import load_env
from .db import migrate
from .db.engine import database_url, make_engine, session_scope
from .refresh import refresh

log = logging.getLogger("annona.scheduler")


def next_run(now: datetime, at: str) -> datetime:
    """Next UTC datetime at HH:MM strictly after ``now``."""
    hour, minute = (int(x) for x in at.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def run_once() -> None:
    url = database_url()
    try:
        migrate.require_head(url)  # the server migrates; this job only waits for it
    except migrate.OutdatedDatabaseError as error:
        log.error("price refresh skipped: %s", error)
        return
    engine = make_engine(url)
    try:
        with session_scope(engine) as session:
            log.info("price refresh: %s", refresh(session))
    except Exception:
        log.exception("price refresh failed")
    finally:
        engine.dispose()


def main() -> None:
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m annona_server.scheduler")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        run_once()
        return
    at = os.environ.get("ANNONA_REFRESH_AT", "04:30")
    while True:
        target = next_run(datetime.now(UTC), at)
        log.info("next price refresh at %s", target.isoformat())
        while (remaining := (target - datetime.now(UTC)).total_seconds()) > 0:
            time.sleep(min(remaining, 300))
        run_once()


if __name__ == "__main__":
    main()
