# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shop-internal barcodes: Open Food Facts data under them describes another item."""

from decimal import Decimal

import pytest

from annona_core.domain import Category, NutritionFacts, NutritionSource, Product, Unit
from annona_server.db.repositories import SqlProductRepository
from annona_server.products import drop_untrusted_off_data, is_restricted_ean
from annona_server.seed import load_sample_foods

# SYNTHETIC: a deliberately wrong "OFF" record, like the one that described chicken as 29 kcal.
WRONG = NutritionFacts(
    basis=Unit.G,
    energy_kcal=Decimal(29),
    protein_g=Decimal(0),
    fat_g=Decimal(0),
    carbohydrates_g=Decimal("7.1"),
    source=NutritionSource.OFF,
    source_ref="off:2330006000000",
)


@pytest.mark.parametrize(
    ("ean", "expected"),
    [
        ("2330006000000", True),  # 2xx: restricted circulation
        ("0212345678905", True),  # 02x
        ("8480000180186", False),  # a normal manufacturer code
        ("2330006", False),  # not an EAN-13
        ("abc", False),
    ],
)
def test_restricted_circulation_barcodes(ean, expected):
    assert is_restricted_ean(ean) is expected


def _store_product(repo, name, ean, nutrition):
    return repo.add(
        Product(
            name=name,
            store_id="shop",
            store_sku=ean,
            ean=ean,
            category=Category.MEAT,
            type="chicken",
            nutrition=nutrition,
        )
    )


def test_untrusted_off_data_is_replaced_by_the_flagged_generic_reference(session):
    load_sample_foods(session)
    repo = SqlProductRepository(session)
    bad = _store_product(repo, "Pechugas", "2330006000000", WRONG)
    good = _store_product(
        repo, "Otra pechuga", "8480000000009", WRONG.model_copy(update={"source_ref": "off:x"})
    )

    changed = drop_untrusted_off_data(session)

    assert [p.id for p in changed] == [bad.id]
    fixed = repo.get(bad.id)
    assert fixed.nutrition.source == NutritionSource.SAMPLE  # flagged as approximate
    assert fixed.nutrition.energy_kcal > 100 and fixed.nutrition.protein_g > 20
    assert repo.get(good.id).nutrition == good.nutrition  # a normal barcode is left alone
    assert drop_untrusted_off_data(session) == []  # idempotent


def test_manual_and_label_data_survive(session):
    load_sample_foods(session)
    repo = SqlProductRepository(session)
    label = WRONG.model_copy(update={"source": NutritionSource.LABEL_SCAN, "source_ref": None})
    kept = _store_product(repo, "Con etiqueta", "2330006000001", label)
    assert drop_untrusted_off_data(session) == []
    assert repo.get(kept.id).nutrition.source == NutritionSource.LABEL_SCAN


def test_ingestion_does_not_ask_open_food_facts_about_shop_internal_codes():
    from annona_providers.base import ProviderProduct
    from annona_server.ingest.service import IngestReport, _lookup_off

    class Off:
        calls: list[str] = []

        def lookup(self, ean):
            self.calls.append(ean)

    off, report = Off(), IngestReport()
    internal = ProviderProduct(store_sku="1", name="Pechugas", ean="2330006000000")
    normal = ProviderProduct(store_sku="2", name="Arroz", ean="8480000050441")
    assert _lookup_off(off, internal, report) is None
    _lookup_off(off, normal, report)
    assert off.calls == ["8480000050441"] and report.off_skipped_restricted == 1
