# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record real HTTP exchanges for the provider contract tests (run locally, review, commit).

Usage: uv run python scripts/record_provider_fixtures.py {open_prices,open_prices_uk,mercadona}

Makes a handful of polite requests through PoliteTransport. The Mercadona plugin is opt-in; running
this for it means you accept its notice (see annona_providers.mercadona.NOTICE).
"""

import argparse
import json
import shutil
from itertools import islice
from pathlib import Path

from annona_providers.http import PoliteTransport
from annona_providers.mercadona import MercadonaProvider
from annona_providers.open_prices import OpenPricesProvider
from annona_providers.testing import INDEX, RecordingTransport

FIXTURES = Path(__file__).resolve().parent.parent / "providers/tests/fixtures"

# Must match the class attributes of the contract tests.
SCENARIOS = {
    "open_prices": {"search": "leche", "known": "8480000229670", "unknown": "99999999999999"},
    # A non-Spanish store in another currency: proves the plugin API is not Spain-shaped.
    "open_prices_uk": {"search": "rice", "known": "5900531011016", "unknown": "99999999999999"},
    "mercadona": {"search": "leche", "known": None, "unknown": "99999999"},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=sorted(SCENARIOS))
    args = parser.parse_args()
    target = FIXTURES / args.provider
    shutil.rmtree(target, ignore_errors=True)
    scenario = SCENARIOS[args.provider]

    if args.provider.startswith("open_prices"):
        transport = RecordingTransport(target, PoliteTransport(min_interval=1.0, cache_ttl=0))
        if args.provider == "open_prices_uk":
            provider = OpenPricesProvider(
                brand="Tesco", country="United Kingdom", currency="GBP", transport=transport
            )
        else:
            provider = OpenPricesProvider(brand="Mercadona", transport=transport)
    else:
        transport = RecordingTransport(
            target, PoliteTransport(min_interval=2.0, cache_ttl=0, robots_exception=True)
        )
        provider = MercadonaProvider(postal_code="28001", transport=transport)

    with_results = provider.search(scenario["search"], limit=5)
    print(f"search {scenario['search']!r}: {[(p.store_sku, p.name) for p in with_results]}")
    known = scenario["known"] or with_results[0].store_sku
    print("known product:", provider.get_product(known))
    print("unknown product:", provider.get_product(scenario["unknown"]))
    print("prices:", provider.get_prices([known]))
    if not provider.info.opt_in:
        first_two = [p.store_sku for p in islice(provider.iter_catalog(), 2)]
        print("catalog first items:", first_two)
        # Used by server/tests/test_ingest.py (catalogue ingestion with limit=2).
        print("catalog prices:", provider.get_prices(first_two))
    provider.close()
    trim_price_pages(target)
    print(f"recorded into {target}")


def trim_price_pages(directory: Path, keep: int = 5) -> None:
    """Keep fixtures small: price listings only need their first few items."""
    index = json.loads((directory / INDEX).read_text())
    for key, entry in index.items():
        if "/api/v1/prices" in key and entry.get("file"):
            path = directory / entry["file"]
            data = json.loads(path.read_text())
            data["items"] = data["items"][:keep]
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
