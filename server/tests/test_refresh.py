# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import UTC, datetime
from decimal import Decimal

from annona_core.domain import Household, PantryItem, Product, Unit
from annona_server.db import repositories as r
from annona_server.refresh import followed_skus, parse_specs
from annona_server.scheduler import next_run


def test_parse_provider_specs():
    specs = parse_specs(
        "open_prices:brand=Mercadona; mercadona:postal_code=28001,accept_notice=yes"
    )
    assert specs[0].provider_id == "open_prices" and specs[0].config == {"brand": "Mercadona"}
    assert not specs[0].accept_notice
    assert specs[1].config == {"postal_code": "28001"} and specs[1].accept_notice
    assert parse_specs("") == []


def test_next_run_is_daily_at_the_configured_time():
    assert next_run(datetime(2026, 11, 21, 3, 0, tzinfo=UTC), "04:30") == datetime(
        2026, 11, 21, 4, 30, tzinfo=UTC
    )
    assert next_run(datetime(2026, 11, 21, 4, 30, tzinfo=UTC), "04:30") == datetime(
        2026, 11, 22, 4, 30, tzinfo=UTC
    )


def test_followed_products_come_from_the_pantry(session):
    home = r.HouseholdRepository(session).add(Household(name="H", weekly_budget_cents=1))
    products = r.SqlProductRepository(session)
    kept = products.add(Product(name="rice", store_id="mercadona", store_sku="5044"))
    products.add(Product(name="other", store_id="mercadona", store_sku="1"))
    r.SqlPantryRepository(session).add(
        PantryItem(household_id=home.id, product_id=kept.id, amount=Decimal(1), unit=Unit.G)
    )
    assert followed_skus(session, "mercadona") == ["5044"]
    assert followed_skus(session, "open_prices:mercadona") == []
