# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

import mercapy
import pytest

from annona_core.domain import Unit
from annona_providers.base import CatalogNotSupportedError, TooManyItemsError
from annona_providers.mercadona import MAX_SKUS_PER_CALL, MercadonaProvider, _package
from annona_providers.testing import FixtureTransport, ProviderContract

from .conftest import FIXTURES


def make() -> MercadonaProvider:
    return MercadonaProvider(
        postal_code="28001", transport=FixtureTransport(FIXTURES / "mercadona")
    )


class TestMercadonaContract(ProviderContract):
    search_query = "leche"
    known_sku = "10381"
    unknown_sku = "99999999"

    @pytest.fixture
    def provider(self):
        p = make()
        yield p
        p.close()


@pytest.mark.live
class TestMercadonaLive(TestMercadonaContract):
    @pytest.fixture
    def provider(self):
        p = MercadonaProvider(postal_code="28001")
        yield p
        p.close()


def test_recorded_pack_of_six_litres():
    p = make()
    assert p.warehouse == "mad3"
    product = p.get_product("10381")
    assert product.ean == "8402001002090"
    assert (product.package_amount, product.package_unit) == (Decimal(6000), Unit.ML)
    assert product.category_path[0] == "Huevos, leche y mantequilla"
    [price] = p.get_prices(["10381"])
    assert price.amount_cents == 498
    assert (price.unit_price_cents, price.unit_price_per) == (83, "l")


def test_never_downloads_the_catalogue():
    with pytest.raises(CatalogNotSupportedError):
        make().iter_catalog()


def test_limits_items_per_call():
    with pytest.raises(TooManyItemsError):
        make().get_prices(["1"] * (MAX_SKUS_PER_CALL + 1))


def test_requires_exactly_one_location():
    with pytest.raises(ValueError):
        MercadonaProvider()
    with pytest.raises(ValueError):
        MercadonaProvider(postal_code="28001", warehouse="mad3")


def summary(**price) -> mercapy.ProductSummary:
    return mercapy.ProductSummary(id="1", name="X", price=mercapy.Price(**price))


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        # 1 l brick at 1.23 EUR, reference 1.23 EUR/l -> consistent
        (
            dict(
                unit=Decimal("1.23"),
                unit_size=Decimal(1),
                size_format="l",
                reference=Decimal("1.23"),
            ),
            (Decimal(1000), Unit.ML),
        ),
        # 400 g at 1.29 EUR, reference 3.225 EUR/kg -> consistent
        (
            dict(
                unit=Decimal("1.29"),
                unit_size=Decimal("0.4"),
                size_format="kg",
                reference=Decimal("3.225"),
            ),
            (Decimal("400.0"), Unit.G),
        ),
        # numbers that disagree -> unknown, never guessed
        (
            dict(
                unit=Decimal("4.98"),
                unit_size=Decimal(1),
                size_format="l",
                reference=Decimal("0.83"),
            ),
            (None, None),
        ),
        # sold by weight -> priced per kg
        (
            dict(sold_by_weight=True, reference=Decimal("12.95"), size_format="kg"),
            (Decimal(1000), Unit.G),
        ),
        # units ("ud") have no mass/volume
        (
            dict(unit=Decimal(2), unit_size=Decimal(12), size_format="ud", reference=Decimal(2)),
            (None, None),
        ),
    ],
)
def test_package_rule(price, expected):
    assert _package(summary(**price)) == expected
