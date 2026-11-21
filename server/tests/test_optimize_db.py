# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optimiser fed from the database. Products, prices and nutrition are SYNTHETIC test values."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from annona_core.domain import (
    ActivityLevel,
    Category,
    Household,
    NutritionFacts,
    NutritionSource,
    PantryItem,
    Price,
    PriceSource,
    Product,
    Sex,
    Unit,
    UserProfile,
)
from annona_core.optimizer import optimise
from annona_server.db import repositories as r
from annona_server.optimize import build_problem
from annona_server.optimize.__main__ import report

FOODS = [  # name, category, grams, kcal, protein, fat, carbs, price cents
    ("rice", Category.GRAINS, 1000, 365, 7, 1, 80, 120),
    ("lentils", Category.LEGUMES, 1000, 350, 24, 1, 60, 180),
    ("oil", Category.OILS_FATS, 1000, 884, 0, 100, 0, 450),
    ("chicken", Category.MEAT, 1000, 120, 22, 3, 0, 600),
    ("apples", Category.FRUIT, 1000, 52, 0, 0, 14, 200),
    ("carrots", Category.VEGETABLES, 1000, 41, 1, 0, 10, 120),
    ("bread", Category.BAKERY, 500, 266, 9, 3, 49, 100),
    ("oats", Category.GRAINS, 500, 379, 13, 7, 68, 110),
    ("peanuts", Category.NUTS_SEEDS, 500, 567, 26, 49, 16, 300),
]


@pytest.fixture
def household(session):
    h = r.HouseholdRepository(session).add(Household(name="Home", weekly_budget_cents=8000))
    r.UserProfileRepository(session).add(
        UserProfile(
            household_id=h.id,
            name="Me",
            sex=Sex.FEMALE,
            birth_date=date(1995, 1, 1),
            height_cm=Decimal(165),
            weight_kg=Decimal(60),
            activity=ActivityLevel.LOW_ACTIVE,
            allergies_confirmed=True,
        )
    )
    products, prices = r.SqlProductRepository(session), r.SqlPriceRepository(session)
    for i, (name, cat, grams, kcal, p, f, c, cents) in enumerate(FOODS):
        prod = products.add(
            Product(
                name=name,
                category=cat,
                store_id="demo",
                store_sku=str(i),
                package_amount=Decimal(grams),
                package_unit=Unit.G,
                allergens=[],
                nutrition=NutritionFacts(
                    energy_kcal=Decimal(kcal),
                    protein_g=Decimal(p),
                    fat_g=Decimal(f),
                    carbohydrates_g=Decimal(c),
                    source=NutritionSource.MANUAL,
                ),
            )
        )
        prices.add(
            Price(
                product_id=prod.id,
                store_id="demo",
                amount_cents=cents,
                source=PriceSource.MANUAL,
                observed_at=datetime(2026, 11, 20, tzinfo=UTC),
            )
        )
    return h


def test_problem_from_db_is_solved(session, household):
    problem = build_problem(
        session, household_id=household.id, store_id="demo", on_date=date(2026, 11, 21)
    )
    assert len(problem.offers) == len(FOODS) and problem.budget_cents == 8000
    result = optimise(problem)
    assert result.status == "optimal"
    assert result.total_cost_cents <= 8000
    text = report(result, problem.budget_cents)
    assert "shopping list" in text and "daily average" in text


def test_pantry_from_db_is_used(session, household):
    rice = r.SqlProductRepository(session).get_by_store_sku("demo", "0")
    r.SqlPantryRepository(session).add(
        PantryItem(household_id=household.id, product_id=rice.id, amount=Decimal(3), unit=Unit.G)
    )
    problem = build_problem(
        session, household_id=household.id, store_id="demo", on_date=date(2026, 11, 21)
    )
    assert problem.pantry[0].amount == 3


def test_budget_override_and_explanation(session, household):
    problem = build_problem(
        session,
        household_id=household.id,
        store_id="demo",
        on_date=date(2026, 11, 21),
        budget_cents=500,
    )
    result = optimise(problem)
    assert result.status == "infeasible"
    assert "CANNOT MEET budget" in report(result, 500)


def test_household_without_members_is_rejected(session):
    h = r.HouseholdRepository(session).add(Household(name="Empty", weekly_budget_cents=1))
    with pytest.raises(ValueError, match="no members"):
        build_problem(session, household_id=h.id, store_id="demo", on_date=date(2026, 11, 21))
