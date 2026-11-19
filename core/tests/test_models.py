# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from annona_core.domain import (
    ActivityLevel,
    Equipment,
    Household,
    MealPlan,
    NutritionFacts,
    NutritionSource,
    Price,
    PriceSource,
    Product,
    Sex,
    Unit,
    UserProfile,
    nutrition_source_may_replace,
)


def test_price_per_kg_from_product_package():
    rice = Product(id=1, name="Rice", package_amount=Decimal(1000), package_unit=Unit.G)
    price = Price(product_id=1, store_id="demo", amount_cents=129, source=PriceSource.MANUAL)
    assert price.unit_price(rice).amount_cents == 129
    assert price.unit_price(rice).per == "kg"


def test_price_per_kg_needs_package_size():
    loose = Product(id=2, name="Loose apples")
    price = Price(product_id=2, store_id="demo", amount_cents=200, source=PriceSource.MANUAL)
    with pytest.raises(ValueError, match="package size"):
        price.unit_price(loose)


def test_price_requires_timezone_aware_datetime():
    with pytest.raises(ValidationError):
        Price(
            product_id=1,
            store_id="demo",
            amount_cents=1,
            source=PriceSource.SCRAPE,
            observed_at=datetime(2026, 1, 1),
        )
    ok = Price(
        product_id=1,
        store_id="demo",
        amount_cents=1,
        source=PriceSource.SCRAPE,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert ok.observed_at.tzinfo is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"store_id": "mercadona"},
        {"store_sku": "123"},
        {"package_amount": Decimal(1)},
        {"package_unit": Unit.G},
        {"ean": "12AB"},
    ],
)
def test_product_rejects_incomplete_pairs_and_bad_ean(kwargs):
    with pytest.raises(ValidationError):
        Product(name="X", **kwargs)


def test_household_currency_is_validated():
    assert Household(name="Home", weekly_budget_cents=6000, currency="eur").currency == "EUR"
    with pytest.raises(ValidationError):
        Household(name="Home", weekly_budget_cents=6000, currency="euros")


def test_profile_age():
    p = UserProfile(
        household_id=1,
        name="Me",
        sex=Sex.MALE,
        birth_date=date(1995, 6, 15),
        height_cm=Decimal(178),
        weight_kg=Decimal(75),
        activity=ActivityLevel.MODERATE,
    )
    assert p.age_on(date(2026, 6, 14)) == 30
    assert p.age_on(date(2026, 6, 15)) == 31


def test_equipment_calibration_must_be_complete_and_in_range():
    with pytest.raises(ValidationError):
        Equipment(household_id=1, calibration_level=6)
    with pytest.raises(ValidationError):
        Equipment(
            household_id=1,
            power_levels=9,
            calibration_level=10,
            calibration_boil_1l_minutes=Decimal(4),
        )
    Equipment(
        household_id=1, power_levels=9, calibration_level=9, calibration_boil_1l_minutes=Decimal(4)
    )


def test_meal_plan_starts_on_monday():
    MealPlan(household_id=1, week_start=date(2026, 11, 16))
    with pytest.raises(ValidationError):
        MealPlan(household_id=1, week_start=date(2026, 11, 19))


@pytest.mark.parametrize(
    ("current", "new", "allowed"),
    [
        (None, NutritionSource.SAMPLE, True),
        (NutritionSource.SAMPLE, NutritionSource.OFF, True),
        (NutritionSource.OFF, NutritionSource.LABEL_SCAN, True),
        (NutritionSource.LABEL_SCAN, NutritionSource.MANUAL, True),
        (NutritionSource.MANUAL, NutritionSource.MANUAL, True),
        (NutritionSource.MANUAL, NutritionSource.LABEL_SCAN, False),
        (NutritionSource.LABEL_SCAN, NutritionSource.OFF, False),
        (NutritionSource.OFF, NutritionSource.LLM_ESTIMATE, False),
        (NutritionSource.LLM_ESTIMATE, NutritionSource.SAMPLE, False),
    ],
)
def test_nutrition_source_priority(current, new, allowed):
    assert nutrition_source_may_replace(current, new) is allowed


def test_nutrition_basis_must_be_mass_or_volume():
    base = {
        "energy_kcal": Decimal(1),
        "protein_g": Decimal(0),
        "fat_g": Decimal(0),
        "carbohydrates_g": Decimal(0),
        "source": NutritionSource.MANUAL,
    }
    assert NutritionFacts(**base).basis == Unit.G
    assert NutritionFacts(**base, basis=Unit.ML).basis == Unit.ML
    with pytest.raises(ValidationError):
        NutritionFacts(**base, basis=Unit.UNIT)
