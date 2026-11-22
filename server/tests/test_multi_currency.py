# SPDX-License-Identifier: AGPL-3.0-or-later
"""A store in another currency (Tesco UK, pounds) next to a euro household. Recorded fixtures."""

from pathlib import Path

import pytest

from annona_core.domain import Household
from annona_providers.open_prices import OpenPricesProvider
from annona_providers.testing import FixtureTransport
from annona_server.db import repositories as r
from annona_server.ingest import ingest
from annona_server.optimize import build_problem
from annona_server.shopping import store_products

FIXTURES = Path(__file__).parents[2] / "providers" / "tests" / "fixtures"
STORE = "open_prices:tesco"


@pytest.fixture
def tesco(session):
    provider = OpenPricesProvider(
        brand="Tesco",
        country="United Kingdom",
        currency="GBP",
        transport=FixtureTransport(FIXTURES / "open_prices_uk"),
    )
    report = ingest(session, provider, catalog=True, limit=2)
    assert report.products_created == 2 and report.prices_added == 2
    return provider


def test_a_foreign_store_is_ingested_with_its_own_currency(session, tesco):
    products = r.SqlProductRepository(session).list(store_id=STORE)
    assert len(products) == 2
    prices = r.SqlPriceRepository(session)
    assert {prices.latest(p.id, STORE).currency for p in products} == {"GBP"}
    assert 99 in {prices.latest(p.id, STORE).amount_cents for p in products}  # 0.99 GBP


def test_a_euro_household_does_not_see_prices_in_pounds(session, tesco):
    """Amounts in different currencies are never mixed: the store is simply not offered."""
    assert store_products(session, STORE, "EUR") == []
    pound_products = {p.store_sku for p in store_products(session, STORE, "GBP")}
    # packaging data is needed to price a basket; only products that have it are offered
    assert pound_products <= {
        p.store_sku for p in r.SqlProductRepository(session).list(store_id=STORE)
    }


def test_the_optimiser_only_offers_products_priced_in_the_household_currency(session, tesco):
    for currency, expected in (("EUR", 0), ("GBP", 2)):
        home = r.HouseholdRepository(session).add(
            Household(name=f"Home {currency}", weekly_budget_cents=5000, currency=currency)
        )
        r.UserProfileRepository(session).add(_profile(home.id))
        problem = build_problem(
            session,
            household_id=home.id,
            store_id=STORE,
            on_date=__import__("datetime").date(2026, 11, 23),
        )
        assert len(problem.offers) == expected, currency


def _profile(household_id):
    from datetime import date
    from decimal import Decimal

    from annona_core.domain import ActivityLevel, Sex, UserProfile

    return UserProfile(
        household_id=household_id,
        name="Sam",
        sex=Sex.FEMALE,
        birth_date=date(1990, 1, 1),
        height_cm=Decimal(165),
        weight_kg=Decimal(60),
        activity=ActivityLevel.ACTIVE,
        allergies_confirmed=True,
    )
