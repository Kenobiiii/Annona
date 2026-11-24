# SPDX-License-Identifier: AGPL-3.0-or-later
"""``python -m annona_server.seed [--demo-store]``: create the database and load the sample foods.

``--demo-store`` also adds an INVENTED store called ``demo`` (see ``annona_server.demo``) so the app
can be tried without any real store data.
"""

import argparse
import sys

from annona_server.db import migrate
from annona_server.db.engine import database_url, make_engine, session_scope

from ..demo import load_demo_store
from . import load_sample_foods


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m annona_server.seed")
    parser.add_argument("--demo-store", action="store_true", help="add an invented demo store")
    args = parser.parse_args()
    url = database_url()
    try:
        migrate.create_or_require_head(url)
    except migrate.OutdatedDatabaseError as error:
        sys.exit(str(error))
    engine = make_engine(url)
    with session_scope(engine) as session:
        report = load_sample_foods(session)
        demo = load_demo_store(session) if args.demo_store else None
    engine.dispose()
    print(
        f"sample foods -> created {report.created}, updated {report.updated}, "
        f"skipped {report.skipped} ({url})"
    )
    if demo is not None:
        print(f"demo store -> {demo} products added (INVENTED prices: for trying the app only)")


if __name__ == "__main__":
    main()
