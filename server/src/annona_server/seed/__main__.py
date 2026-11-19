# SPDX-License-Identifier: AGPL-3.0-or-later
"""``python -m annona_server.seed`` — migrate the database to head and load the sample foods."""

from annona_server.db import migrate
from annona_server.db.engine import database_url, make_engine, session_scope

from . import load_sample_foods


def main() -> None:
    url = database_url()
    migrate.upgrade(url)
    engine = make_engine(url)
    with session_scope(engine) as session:
        report = load_sample_foods(session)
    engine.dispose()
    print(
        f"sample foods -> created {report.created}, updated {report.updated}, "
        f"skipped {report.skipped} ({url})"
    )


if __name__ == "__main__":
    main()
