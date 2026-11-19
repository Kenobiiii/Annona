# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

from annona_core.domain import Category, NutritionSource, Unit
from annona_server.db.repositories import SqlProductRepository
from annona_server.seed import load_sample_foods, sample_foods


def test_seed_file_is_well_formed():
    foods = sample_foods()
    assert 25 <= len(foods) <= 40
    keys = [f["key"] for f in foods]
    assert len(keys) == len(set(keys))
    for f in foods:
        assert f["nutrition"]["source"] == "sample"
        assert f["nutrition"]["source_ref"].startswith("usda-fdc:")
        Category(f["category"])  # valid category


def test_seed_loads_and_is_idempotent(session):
    first = load_sample_foods(session)
    assert first.created == len(sample_foods())
    assert (first.updated, first.skipped) == (0, 0)

    second = load_sample_foods(session)
    assert (second.created, second.updated, second.skipped) == (0, 0, len(sample_foods()))
    assert len(SqlProductRepository(session).list()) == len(sample_foods())


def test_seeded_values_round_trip(session):
    load_sample_foods(session)
    repo = SqlProductRepository(session)
    egg = repo.get_by_nutrition_ref("usda-fdc:171287")
    assert egg is not None
    assert egg.nutrition.basis == Unit.G
    assert egg.nutrition.energy_kcal == Decimal(143)
    assert egg.unit_weight_g == Decimal(50)
    assert egg.allergens == ["eggs"]
    assert egg.store_id is None  # generic food, not a store product


def test_seed_never_overwrites_better_nutrition(session):
    load_sample_foods(session)
    repo = SqlProductRepository(session)
    rice = repo.get_by_nutrition_ref("usda-fdc:169756")
    edited = rice.model_copy(
        update={
            "nutrition": rice.nutrition.model_copy(
                update={"energy_kcal": Decimal(360), "source": NutritionSource.MANUAL}
            )
        }
    )
    repo.update(edited)

    report = load_sample_foods(session)
    assert report.created == 0
    after = repo.get(rice.id)
    assert after.nutrition.source == NutritionSource.MANUAL
    assert after.nutrition.energy_kcal == Decimal(360)
