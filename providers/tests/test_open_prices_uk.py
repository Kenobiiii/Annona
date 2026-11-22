# SPDX-License-Identifier: AGPL-3.0-or-later
"""A second, non-Spanish store through the same plugin API: Tesco (UK), prices in pounds.

Recorded from Open Prices (ODbL 1.0) on 2026-11-22; see ``fixtures/README.md``. It proves the plugin
interface is not Spain-shaped: another country, language and currency, with no change to the core.
"""

import pytest

from annona_providers.open_prices import OpenPricesProvider
from annona_providers.testing import FixtureTransport, ProviderContract

from .conftest import FIXTURES


def make() -> OpenPricesProvider:
    return OpenPricesProvider(
        brand="Tesco",
        country="United Kingdom",
        currency="GBP",
        transport=FixtureTransport(FIXTURES / "open_prices_uk"),
    )


class TestTescoContract(ProviderContract):
    search_query = "rice"
    known_sku = "5900531011016"
    unknown_sku = "99999999999999"

    @pytest.fixture
    def provider(self):
        p = make()
        yield p
        p.close()


def test_the_instance_describes_itself_not_the_class():
    """Found by adding this provider: info.currency said EUR whatever the instance followed."""
    uk, spain = make(), OpenPricesProvider(brand="Mercadona")
    assert uk.info.currency == "GBP" and spain.info.currency == "EUR"
    assert OpenPricesProvider.info.currency == "EUR"  # the class default is untouched
    assert uk.store_id == "open_prices:tesco" and spain.store_id == "open_prices:mercadona"
    assert uk.info.attribution and "ODbL" in uk.info.attribution


def test_prices_are_in_pence_as_integers_and_in_pounds():
    prices = make().get_prices(["5900531011016"])
    assert [(p.amount_cents, p.currency) for p in prices] == [(99, "GBP")]
    assert isinstance(prices[0].amount_cents, int)


def test_products_keep_their_own_language_and_units():
    product = make().get_product("5900531011016")
    assert product.name == "Serek homogenizowany waniliowy"  # Polish, sold at a UK store
    assert (str(product.package_amount), str(product.package_unit)) == ("150", "g")
