# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ingestion with recorded provider fixtures and a SYNTHETIC Open Food Facts stand-in."""

from decimal import Decimal

import pytest

from annona_core.domain import (
    Allergen,
    Category,
    CategorySource,
    NutritionFacts,
    NutritionSource,
    Unit,
)
from annona_providers.mercadona import MercadonaProvider
from annona_providers.open_prices import OpenPricesProvider
from annona_providers.testing import FixtureTransport
from annona_server.db.repositories import SqlPriceRepository, SqlProductRepository
from annona_server.ingest import ingest
from annona_server.ingest.off import OffProduct
from annona_server.products import products_with_unknown_allergens, set_allergens, set_category

PROVIDER_FIXTURES = (
    __import__("pathlib").Path(__file__).parents[2] / "providers" / "tests" / "fixtures"
)

# SYNTHETIC test values (not real product data): they only exercise the ingestion logic.
FAKE_NUTRITION = NutritionFacts(
    basis=Unit.ML,
    energy_kcal=Decimal(50),
    protein_g=Decimal(3),
    fat_g=Decimal(2),
    carbohydrates_g=Decimal(5),
    source=NutritionSource.OFF,
    source_ref="off:test",
)


class FakeOff:
    def __init__(self, known: dict[str, OffProduct]) -> None:
        self.known = known
        self.calls: list[str] = []

    def lookup(self, ean: str) -> OffProduct | None:
        self.calls.append(ean)
        return self.known.get(ean)


@pytest.fixture
def mercadona():
    p = MercadonaProvider(
        postal_code="28001", transport=FixtureTransport(PROVIDER_FIXTURES / "mercadona")
    )
    yield p
    p.close()


@pytest.fixture
def off():
    return FakeOff(
        {
            "8402001002090": OffProduct(
                ean="8402001002090",
                name="synthetic",
                nutrition=FAKE_NUTRITION,
                allergens=[Allergen.MILK],
                categories=("en:dairies",),
            )
        }
    )


def test_ingest_creates_product_with_price_unit_price_and_nutrition(session, mercadona, off):
    report = ingest(session, mercadona, skus=["10381"], off=off)
    assert (report.products_created, report.prices_added) == (1, 1)
    assert report.nutrition_from_off == 1

    product = SqlProductRepository(session).get_by_store_sku("mercadona", "10381")
    assert product.ean == "8402001002090"
    assert (product.package_amount, product.package_unit) == (Decimal(6000), Unit.ML)
    assert (product.category, product.type, product.category_source) == (
        Category.DAIRY,
        "milk",
        CategorySource.RULE,
    )
    assert product.nutrition.source == NutritionSource.OFF
    assert (product.allergens, product.allergens_source) == ([Allergen.MILK], NutritionSource.OFF)

    price = SqlPriceRepository(session).latest(product.id, "mercadona")
    assert price.amount_cents == 498
    assert price.unit_price(product).amount_cents == 83  # 4.98 EUR / 6 l, per litre


def test_ingest_is_idempotent(session, mercadona, off):
    ingest(session, mercadona, skus=["10381"], off=off)
    again = ingest(session, mercadona, skus=["10381"], off=off)
    assert (again.products_created, again.products_updated, again.products_unchanged) == (0, 0, 1)
    assert (again.prices_added, again.prices_unchanged) == (0, 1)
    assert again.nutrition_from_off == 0
    assert len(SqlProductRepository(session).list()) == 1
    assert len(SqlPriceRepository(session).list()) == 1


def test_manual_edits_survive_reingestion(session, mercadona, off):
    ingest(session, mercadona, skus=["10381"], off=off)
    product = SqlProductRepository(session).get_by_store_sku("mercadona", "10381")
    set_allergens(session, product.id, [Allergen.MILK, Allergen.SOYBEANS])
    set_category(session, product.id, Category.BEVERAGES, "milk")
    manual_nutrition = product.nutrition.model_copy(
        update={"energy_kcal": Decimal(46), "source": NutritionSource.MANUAL}
    )
    SqlProductRepository(session).update(
        SqlProductRepository(session)
        .get(product.id)
        .model_copy(update={"nutrition": manual_nutrition})
    )

    ingest(session, mercadona, skus=["10381"], off=off)
    after = SqlProductRepository(session).get(product.id)
    assert after.allergens == [Allergen.SOYBEANS, Allergen.MILK]
    assert after.allergens_source == NutritionSource.MANUAL
    assert (after.category, after.category_source) == (Category.BEVERAGES, CategorySource.MANUAL)
    assert after.nutrition.energy_kcal == 46 and after.nutrition.source == NutritionSource.MANUAL


def test_product_missing_from_off_keeps_unknown_data(session, mercadona):
    report = ingest(session, mercadona, skus=["10381"], off=FakeOff({}))
    assert report.off_not_found == 1
    product = SqlProductRepository(session).get_by_store_sku("mercadona", "10381")
    assert product.nutrition is None  # never invented
    assert product.allergens is None  # unknown -> excluded for allergic users
    assert products_with_unknown_allergens(session) == [product]


def test_manual_allergens_none_means_known_free(session, mercadona):
    ingest(session, mercadona, skus=["10381"], off=FakeOff({}))
    product = SqlProductRepository(session).get_by_store_sku("mercadona", "10381")
    updated = set_allergens(session, product.id, [])
    assert updated.allergens == [] and updated.allergens_source == NutritionSource.MANUAL
    cleared = set_allergens(session, product.id, None)
    assert cleared.allergens is None and cleared.allergens_source is None


def test_open_prices_catalogue_ingestion(session):
    provider = OpenPricesProvider(
        brand="Mercadona", transport=FixtureTransport(PROVIDER_FIXTURES / "open_prices")
    )
    report = ingest(session, provider, catalog=True, limit=2, off=None)
    assert report.products_created == 2
    stored = SqlProductRepository(session).list(store_id="open_prices:mercadona")
    assert {p.ean for p in stored} == {p.store_sku for p in stored}
    again = ingest(session, provider, catalog=True, limit=2, off=None)
    assert again.products_created == 0 and again.prices_added == 0


def test_opt_in_providers_are_limited(session, mercadona):
    with pytest.raises(ValueError, match="personal-use"):
        ingest(session, mercadona, skus=[str(i) for i in range(51)], off=None)


def test_open_prices_ingestion_with_real_off_data(session):
    """Real Open Prices + real Open Food Facts responses (recorded fixtures)."""
    from annona_server.ingest.off import OpenFoodFactsClient

    provider = OpenPricesProvider(
        brand="Mercadona", transport=FixtureTransport(PROVIDER_FIXTURES / "open_prices")
    )
    off_client = OpenFoodFactsClient(
        session,
        transport=FixtureTransport(
            __import__("pathlib").Path(__file__).parent / "fixtures" / "off"
        ),
    )
    report = ingest(session, provider, catalog=True, limit=2, off=off_client)
    assert report.nutrition_from_off == 2 and report.unclassified == []

    repo = SqlProductRepository(session)
    walnuts = repo.get_by_store_sku("open_prices:mercadona", "8480000340245")
    assert (walnuts.category, walnuts.type) == (Category.NUTS_SEEDS, "walnuts")
    assert walnuts.allergens == [Allergen.NUTS]
    assert walnuts.nutrition.energy_kcal == 716

    milk = repo.get_by_store_sku("open_prices:mercadona", "8480000107947")
    assert (milk.category, milk.type) == (Category.DAIRY, "milk")
    assert milk.nutrition.protein_g == Decimal("3.1")
    assert SqlPriceRepository(session).latest(milk.id).amount_cents == 164
