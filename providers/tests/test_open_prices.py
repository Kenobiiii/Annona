# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

import pytest

from annona_core.domain import Unit
from annona_providers.base import TooManyItemsError
from annona_providers.open_prices import OpenPricesProvider, _package
from annona_providers.testing import FixtureTransport, ProviderContract

from .conftest import FIXTURES


def make(transport=None) -> OpenPricesProvider:
    return OpenPricesProvider(
        brand="Mercadona", transport=transport or FixtureTransport(FIXTURES / "open_prices")
    )


class TestOpenPricesContract(ProviderContract):
    search_query = "leche"
    known_sku = "8480000229670"
    unknown_sku = "99999999999999"

    @pytest.fixture
    def provider(self):
        p = make()
        yield p
        p.close()


@pytest.mark.live
class TestOpenPricesLive(TestOpenPricesContract):
    @pytest.fixture
    def provider(self):
        p = OpenPricesProvider(brand="Mercadona")
        yield p
        p.close()


def test_recorded_values():
    p = make()
    product = p.get_product("8480000229670")
    assert product.package_amount == Decimal(1200)
    assert product.package_unit == Unit.ML
    [price] = p.get_prices(["8480000229670"])
    assert price.amount_cents == 185  # 1.85 EUR, read as Decimal("1.85"), never float
    assert price.observed_at.date().isoformat() == "2025-03-16"
    assert p.store_id == "open_prices:mercadona"


def test_too_many_skus():
    with pytest.raises(TooManyItemsError):
        make().get_prices([str(10_000_000 + i) for i in range(101)])


@pytest.mark.parametrize(
    ("amount", "unit", "expected"),
    [
        (1200, "ml", (Decimal(1200), Unit.ML)),
        (1, "kg", (Decimal(1000), Unit.G)),
        (None, "g", (None, None)),
        (500, "", (None, None)),
        (3, "lb", (None, None)),
        (0, "g", (None, None)),
    ],
)
def test_package_parsing(amount, unit, expected):
    assert _package(amount, unit) == expected
