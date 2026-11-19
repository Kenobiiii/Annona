# SPDX-License-Identifier: AGPL-3.0-or-later
"""Edit products by hand (until the app has screens for it).

python -m annona_server.products search leche
python -m annona_server.products show 12
python -m annona_server.products unknown-allergens
python -m annona_server.products allergens 12 milk gluten   # contains milk and gluten
python -m annona_server.products allergens 12 --none        # contains none of the EU 14
python -m annona_server.products allergens 12 --unknown     # forget the manual entry
python -m annona_server.products category 12 dairy --type milk
"""

from __future__ import annotations

import argparse
import sys

from annona_core.domain import Allergen, Product
from annona_core.domain.enums import Category

from ..config import load_env
from ..db import migrate
from ..db.engine import database_url, make_engine, session_scope
from ..db.repositories import NotFoundError, SqlProductRepository
from . import products_with_unknown_allergens, set_allergens, set_category


def describe(p: Product) -> str:
    allergens = "unknown" if p.allergens is None else (", ".join(p.allergens) or "none")
    kcal = p.nutrition.energy_kcal if p.nutrition else "?"
    return (
        f"#{p.id} {p.name} [{p.store_id or 'generic'}:{p.store_sku or '-'}] "
        f"category={p.category}({p.category_source}) allergens={allergens}"
        f"({p.allergens_source}) kcal/100={kcal}"
    )


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="python -m annona_server.products")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("search").add_argument("text")
    sub.add_parser("show").add_argument("id", type=int)
    sub.add_parser("unknown-allergens")
    a = sub.add_parser("allergens", help="set allergens by hand")
    a.add_argument("id", type=int)
    a.add_argument("allergens", nargs="*", choices=[x.value for x in Allergen], metavar="ALLERGEN")
    group = a.add_mutually_exclusive_group()
    group.add_argument("--none", action="store_true", help="contains none of the EU 14")
    group.add_argument("--unknown", action="store_true", help="clear the manual entry")
    c = sub.add_parser("category", help="set the category by hand")
    c.add_argument("id", type=int)
    c.add_argument("category", choices=[x.value for x in Category])
    c.add_argument("--type")
    args = parser.parse_args()

    url = database_url()
    migrate.upgrade(url)
    engine = make_engine(url)
    try:
        with session_scope(engine) as session:
            repo = SqlProductRepository(session)
            if args.command == "search":
                for p in repo.search(args.text, limit=50):
                    print(describe(p))
            elif args.command == "show":
                product = repo.get(args.id)
                print(describe(product) if product else f"product {args.id} not found")
            elif args.command == "unknown-allergens":
                for p in products_with_unknown_allergens(session):
                    print(describe(p))
            elif args.command == "allergens":
                if not args.allergens and not args.none and not args.unknown:
                    parser.error("give allergens, --none or --unknown")
                value = None if args.unknown else [Allergen(x) for x in args.allergens]
                print(describe(set_allergens(session, args.id, value)))
            elif args.command == "category":
                print(describe(set_category(session, args.id, Category(args.category), args.type)))
    except NotFoundError as error:
        sys.exit(str(error))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
