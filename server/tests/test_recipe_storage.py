# SPDX-License-Identifier: AGPL-3.0-or-later
"""Detailed recipe steps and the cooked marker survive a round trip through the database."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from annona_core.domain import (
    Appliance,
    HeatLevel,
    Household,
    MealPlan,
    MealSlot,
    PlannedMeal,
    Recipe,
    RecipeStep,
)
from annona_server.db import repositories as r


@pytest.fixture
def household(session):
    return r.HouseholdRepository(session).add(Household(name="Casa", weekly_budget_cents=5000))


def test_method_and_cooked_at_round_trip(session, household):
    method = [
        RecipeStep(text="Hierve {p1} en agua.", heat=HeatLevel.HIGH, boil_ml=1500, minutes=9),
        RecipeStep(text="Sirve.", appliance=Appliance.NONE),
    ]
    recipe = r.RecipeRepository(session).add(
        Recipe(household_id=household.id, title="Arroz", method=method)
    )
    plan = r.MealPlanRepository(session).add(
        MealPlan(household_id=household.id, week_start=date(2026, 11, 23))
    )
    when = datetime(2026, 11, 23, 14, 5, tzinfo=UTC)
    meal = r.PlannedMealRepository(session).add(
        PlannedMeal(
            plan_id=plan.id, day=date(2026, 11, 23), slot=MealSlot.LUNCH, recipe_id=recipe.id
        )
    )
    assert r.PlannedMealRepository(session).get(meal.id).cooked_at is None
    r.PlannedMealRepository(session).update(meal.model_copy(update={"cooked_at": when}))

    assert r.RecipeRepository(session).get(recipe.id).method == method
    assert r.PlannedMealRepository(session).get(meal.id).cooked_at == when


def test_recipe_step_limits():
    with pytest.raises(ValidationError):
        RecipeStep(text="")
    with pytest.raises(ValidationError):
        RecipeStep(text="x", boil_ml=10)
    assert RecipeStep(text="Mezcla").appliance == Appliance.NONE


def test_receipt_alias_round_trip_and_uniqueness(session, household):
    import sqlalchemy.exc

    from annona_core.domain import Product, ReceiptAlias

    product = r.SqlProductRepository(session).add(Product(name="Arroz"))
    aliases = r.ReceiptAliasRepository(session)
    saved = aliases.add(
        ReceiptAlias(
            household_id=household.id,
            store_id="shop",
            normalized_text="ARROZ REDONDO",
            product_id=product.id,
        )
    )
    assert aliases.get(saved.id) == saved
    with pytest.raises(sqlalchemy.exc.IntegrityError):  # one alias per (store, text)
        aliases.add(
            ReceiptAlias(
                household_id=household.id,
                store_id="shop",
                normalized_text="ARROZ REDONDO",
                product_id=product.id,
            )
        )
