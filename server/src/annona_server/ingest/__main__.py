# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ingest products and prices from a provider.

Examples::

    python -m annona_server.ingest open_prices --brand Mercadona --catalog --limit 200
    python -m annona_server.ingest open_prices --brand Tesco --country "United Kingdom" \\
        --currency GBP --catalog --limit 200
    python -m annona_server.ingest mercadona --postal-code 28001 --accept-notice \\
        --sku 4740 --query "arroz redondo"
"""

from __future__ import annotations

import argparse
import sys

from annona_providers.base import NoticeNotAcceptedError
from annona_providers.registry import available_providers, create_provider

from ..config import load_env
from ..db import migrate
from ..db.engine import database_url, make_engine, session_scope
from .off import OpenFoodFactsClient
from .service import ingest


def main() -> None:
    load_env()
    ids = [info.id for info in available_providers()]
    parser = argparse.ArgumentParser(prog="python -m annona_server.ingest")
    parser.add_argument("provider", choices=ids)
    parser.add_argument("--sku", action="append", default=[], help="store product id (repeat)")
    parser.add_argument("--query", action="append", default=[], help="search text (repeat)")
    parser.add_argument("--catalog", action="store_true", help="whole catalogue (if allowed)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--brand", help="open_prices: store brand, e.g. Mercadona")
    parser.add_argument("--country", help="open_prices: country name as in OpenStreetMap")
    parser.add_argument("--currency", help="open_prices: ISO 4217 code of the prices, e.g. GBP")
    parser.add_argument("--postal-code", help="mercadona: Spanish postcode")
    parser.add_argument("--warehouse", help="mercadona: warehouse code")
    parser.add_argument("--accept-notice", action="store_true", help="accept an opt-in notice")
    parser.add_argument("--no-off", action="store_true", help="skip Open Food Facts lookups")
    parser.add_argument(
        "--llm", action="store_true", help="classify products the rules miss with the AI"
    )
    args = parser.parse_args()

    config = {
        key: value
        for key, value in {
            "brand": args.brand,
            "country": args.country,
            "currency": args.currency,
            "postal_code": args.postal_code,
            "warehouse": args.warehouse,
        }.items()
        if value is not None
    }
    try:
        provider = create_provider(args.provider, accept_notice=args.accept_notice, **config)
    except NoticeNotAcceptedError as error:
        sys.exit(f"{error}\n\nRe-run with --accept-notice to accept it.")

    url = database_url()
    migrate.exit_if_outdated(url)
    engine = make_engine(url)
    try:
        with session_scope(engine) as session:
            off = None if args.no_off else OpenFoodFactsClient(session)
            llm_classifier = None
            if args.llm:
                from ..llm import make_llm_client
                from .llm_classify import LLMClassifier

                llm_classifier = LLMClassifier(make_llm_client(session))
            report = ingest(
                session,
                provider,
                skus=args.sku,
                queries=args.query,
                catalog=args.catalog,
                limit=args.limit,
                off=off,
                llm_classifier=llm_classifier,
            )
            if off:
                off.close()
    finally:
        provider.close()
        engine.dispose()
    for key, value in vars(report).items():
        print(f"{key}: {len(value) if isinstance(value, list) else value}")
    for line in report.unclassified:
        print(f"  unclassified: {line}")


if __name__ == "__main__":
    main()
