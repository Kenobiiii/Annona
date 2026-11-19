# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record Open Food Facts responses for the ingestion tests (run locally, review, commit).

Usage: uv run python scripts/record_off_fixtures.py EAN [EAN ...]
"""

import sys
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from annona_providers.http import PoliteTransport
from annona_providers.testing import RecordingTransport
from annona_server.db import tables  # noqa: F401
from annona_server.ingest.off import MIN_INTERVAL_SECONDS, OpenFoodFactsClient, off_user_agent

TARGET = Path(__file__).resolve().parent.parent / "server/tests/fixtures/off"


def main() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    transport = RecordingTransport(
        TARGET,
        PoliteTransport(
            min_interval=MIN_INTERVAL_SECONDS,
            cache_ttl=0,
            agent=off_user_agent(),
            robots_exception=True,
            exception_reason="documented Open Food Facts API",
        ),
    )
    with Session(engine) as session:
        client = OpenFoodFactsClient(session, transport=transport)
        for ean in sys.argv[1:]:
            product = client.lookup(ean)
            print(ean, "->", "not found" if product is None else product.name)
        client.close()


if __name__ == "__main__":
    main()
