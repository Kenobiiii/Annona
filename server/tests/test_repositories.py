# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from annona_core.domain import (
    ActivityLevel,
    Allergen,
    Category,
    Equipment,
    Household,
    MealPlan,
    NutritionFacts,
    NutritionSource,
    PantryItem,
    PlannedMeal,
    Price,
    PriceSource,
    Product,
    Receipt,
    ReceiptLine,
    Recipe,
    RecipeIngredient,
    Sex,
    ShoppingItem,
    ShoppingList,
    Unit,
    UserProfile,
)
from annona_core.domain.enums import MealSlot
from annona_server.db import repositories as r


@pytest.fixture
def household(session):
    return r.HouseholdRepository(session).add(Household(name="Home", weekly_budget_cents=6000))


@pytest.fixture
def rice(session):
    return r.SqlProductRepository(session).add(
        Product(
            name="Long grain rice",
            category=Category.GRAINS,
            type="rice",
            store_id="demo",
            store_sku="R-1",
            ean="8480000123456",
            package_amount=Decimal(1000),
            package_unit=Unit.G,
            allergens=[],
            nutrition=NutritionFacts(
                energy_kcal=Decimal(365),
                protein_g=Decimal("7.13"),
                fat_g=Decimal("0.66"),
                carbohydrates_g=Decimal("79.95"),
                fiber_g=Decimal("1.3"),
                source=NutritionSource.SAMPLE,
                source_ref="test:1",
            ),
        )
    )


def test_product_round_trip_keeps_decimals_and_nutrition(session, rice):
    session.expire_all()
    loaded = r.SqlProductRepository(session).get(rice.id)
    assert loaded == rice
    assert loaded.nutrition.protein_g == Decimal("7.13")
    assert loaded.nutrition.sugars_g is None


def test_product_without_nutrition(session):
    repo = r.SqlProductRepository(session)
    p = repo.add(Product(name="Mystery"))
    assert repo.get(p.id).nutrition is None


def test_product_lookups(session, rice):
    repo = r.SqlProductRepository(session)
    assert repo.get_by_store_sku("demo", "R-1") == rice
    assert repo.get_by_store_sku("demo", "nope") is None
    assert repo.find_by_ean("8480000123456") == [rice]
    assert repo.get_by_nutrition_ref("test:1") == rice
    assert repo.search("GRAIN") == [rice]
    assert repo.search("pasta") == []


def test_store_sku_is_unique(session, rice):
    with pytest.raises(IntegrityError):
        r.SqlProductRepository(session).add(Product(name="Dup", store_id="demo", store_sku="R-1"))


def test_update_and_delete(session, rice):
    repo = r.SqlProductRepository(session)
    updated = repo.update(rice.model_copy(update={"name": "Basmati rice"}))
    assert repo.get(rice.id).name == "Basmati rice" == updated.name
    repo.delete(rice.id)
    assert repo.get(rice.id) is None
    with pytest.raises(r.NotFoundError):
        repo.delete(rice.id)
    with pytest.raises(r.NotFoundError):
        repo.update(updated)


def test_add_rejects_entities_with_id(session, rice):
    with pytest.raises(ValueError, match="already has an id"):
        r.SqlProductRepository(session).add(rice)


def test_prices_history_latest_and_timezones(session, rice):
    repo = r.SqlPriceRepository(session)
    madrid = timezone(timedelta(hours=1))
    t0 = datetime(2026, 11, 1, 10, tzinfo=madrid)

    def add(cents: int, when: datetime, store: str = "demo") -> Price:
        return repo.add(
            Price(
                product_id=rice.id,
                store_id=store,
                amount_cents=cents,
                source=PriceSource.SCRAPE,
                observed_at=when,
            )
        )

    add(129, t0)
    add(135, t0 + timedelta(days=7))
    add(99, t0 + timedelta(days=3), store="other")
    session.expire_all()

    assert [p.amount_cents for p in repo.history(rice.id, "demo")] == [129, 135]
    assert repo.latest(rice.id, "demo").amount_cents == 135
    assert repo.latest(rice.id).amount_cents == 135
    first = repo.history(rice.id)[0]
    assert first.observed_at == t0  # same instant ...
    assert first.observed_at.tzinfo == UTC  # ... returned in UTC
    assert repo.latest(rice.id, "demo").unit_price(rice).amount_cents == 135


def test_household_members_kitchen_and_pantry(session, household, rice):
    profile = r.UserProfileRepository(session).add(
        UserProfile(
            household_id=household.id,
            name="Me",
            sex=Sex.FEMALE,
            birth_date=date(1990, 1, 1),
            height_cm=Decimal("165.5"),
            weight_kg=Decimal("60.2"),
            activity=ActivityLevel.LIGHT,
            allergies=[Allergen.GLUTEN, Allergen.MILK],
        )
    )
    session.expire_all()
    assert r.UserProfileRepository(session).get(profile.id).allergies == [
        Allergen.GLUTEN,
        Allergen.MILK,
    ]

    kitchen = r.EquipmentRepository(session).add(
        Equipment(
            household_id=household.id,
            power_levels=9,
            calibration_level=9,
            calibration_boil_1l_minutes=Decimal("4.5"),
        )
    )
    assert kitchen.calibration_boil_1l_minutes == Decimal("4.5")

    pantry = r.SqlPantryRepository(session)
    item = pantry.add(
        PantryItem(household_id=household.id, product_id=rice.id, amount=Decimal(500), unit=Unit.G)
    )
    assert pantry.for_household(household.id) == [item]
    assert item.quantity.amount == 500


def test_household_delete_cascades(session, household, rice):
    r.SqlPantryRepository(session).add(
        PantryItem(household_id=household.id, product_id=rice.id, amount=Decimal(1), unit=Unit.G)
    )
    r.HouseholdRepository(session).delete(household.id)
    session.expire_all()
    assert r.SqlPantryRepository(session).list() == []
    assert r.SqlProductRepository(session).get(rice.id) is not None


def test_product_in_pantry_cannot_be_deleted(session, household, rice):
    r.SqlPantryRepository(session).add(
        PantryItem(household_id=household.id, product_id=rice.id, amount=Decimal(1), unit=Unit.G)
    )
    with pytest.raises(IntegrityError):
        r.SqlProductRepository(session).delete(rice.id)


def test_foreign_keys_are_enforced(session):
    with pytest.raises(IntegrityError):
        r.SqlPantryRepository(session).add(
            PantryItem(household_id=999, product_id=999, amount=Decimal(1), unit=Unit.G)
        )


def test_plan_recipe_shopping_and_receipt_round_trip(session, household, rice):
    recipe = r.RecipeRepository(session).add(
        Recipe(household_id=household.id, title="Rice bowl", steps=["Boil", "Serve"])
    )
    r.RecipeIngredientRepository(session).add(
        RecipeIngredient(recipe_id=recipe.id, product_id=rice.id, amount=Decimal(80), unit=Unit.G)
    )
    plan = r.MealPlanRepository(session).add(
        MealPlan(household_id=household.id, week_start=date(2026, 11, 16))
    )
    meal = r.PlannedMealRepository(session).add(
        PlannedMeal(
            plan_id=plan.id, day=date(2026, 11, 16), slot=MealSlot.LUNCH, recipe_id=recipe.id
        )
    )
    shopping = r.ShoppingListRepository(session).add(
        ShoppingList(household_id=household.id, store_id="demo", plan_id=plan.id)
    )
    r.ShoppingItemRepository(session).add(
        ShoppingItem(list_id=shopping.id, product_id=rice.id, packs=2, unit_price_cents=129)
    )
    receipt = r.ReceiptRepository(session).add(Receipt(household_id=household.id))
    line = r.ReceiptLineRepository(session).add(
        ReceiptLine(
            receipt_id=receipt.id,
            raw_text="ARROZ LARGO 1K",
            total_cents=129,
            matched_product_id=rice.id,
            confidence=Decimal("0.87"),
        )
    )
    session.expire_all()

    assert r.RecipeRepository(session).get(recipe.id).steps == ["Boil", "Serve"]
    assert r.PlannedMealRepository(session).list(plan_id=plan.id) == [meal]
    assert r.ReceiptLineRepository(session).get(line.id).confidence == Decimal("0.87")

    # Deleting the recipe keeps the planned meal but unlinks it.
    r.RecipeRepository(session).delete(recipe.id)
    session.expire_all()
    assert r.PlannedMealRepository(session).get(meal.id).recipe_id is None
    assert r.RecipeIngredientRepository(session).list() == []
