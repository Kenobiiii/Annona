# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date
from decimal import Decimal

import pytest

from annona_core.domain import ActivityLevel, Allergen, Category, Diet, Product, Sex, UserProfile
from annona_core.nutrition import ExclusionReason, check_product, is_product_allowed

R = ExclusionReason


def profile(diet: Diet = Diet.OMNIVORE, allergies: list[Allergen] | None = None) -> UserProfile:
    return UserProfile(
        household_id=1,
        name="Test",
        sex=Sex.FEMALE,
        birth_date=date(1990, 1, 1),
        height_cm=Decimal(165),
        weight_kg=Decimal(60),
        activity=ActivityLevel.ACTIVE,
        diet=diet,
        allergies=allergies or [],
        allergies_confirmed=True,
    )


def product(category: Category, allergens: list[Allergen] | None) -> Product:
    return Product(name="P", category=category, allergens=allergens)


def test_allergen_present_is_excluded():
    d = check_product(
        product(Category.BAKERY, [Allergen.GLUTEN, Allergen.SESAME]),
        profile(allergies=[Allergen.GLUTEN]),
    )
    assert not d.allowed
    assert d.reasons == (R.CONTAINS_ALLERGEN,)
    assert d.allergens_found == (Allergen.GLUTEN,)


def test_unknown_allergens_are_excluded_for_allergic_people():
    d = check_product(product(Category.PREPARED, None), profile(allergies=[Allergen.PEANUTS]))
    assert not d.allowed
    assert d.reasons == (R.ALLERGENS_UNKNOWN,)


def test_unknown_allergens_are_fine_without_allergies():
    assert is_product_allowed(product(Category.PREPARED, None), profile())


def test_known_free_product_is_allowed_for_allergic_people():
    assert is_product_allowed(product(Category.GRAINS, []), profile(allergies=[Allergen.GLUTEN]))


@pytest.mark.parametrize(
    ("diet", "category", "allergens", "allowed"),
    [
        (Diet.OMNIVORE, Category.MEAT, [], True),
        (Diet.PESCATARIAN, Category.MEAT, [], False),
        (Diet.PESCATARIAN, Category.FISH, [Allergen.FISH], True),
        (Diet.VEGETARIAN, Category.FISH, [Allergen.FISH], False),
        (Diet.VEGETARIAN, Category.DAIRY, [Allergen.MILK], True),
        (Diet.VEGETARIAN, Category.EGGS, [Allergen.EGGS], True),
        (Diet.VEGETARIAN, Category.PREPARED, [Allergen.CRUSTACEANS], False),
        (Diet.VEGAN, Category.DAIRY, [Allergen.MILK], False),
        (Diet.VEGAN, Category.EGGS, [Allergen.EGGS], False),
        (Diet.VEGAN, Category.BAKERY, [Allergen.GLUTEN, Allergen.MILK], False),  # milk bread
        (Diet.VEGAN, Category.BAKERY, [Allergen.GLUTEN], True),
        (Diet.VEGAN, Category.LEGUMES, [], True),
    ],
)
def test_diet_rules(diet, category, allergens, allowed):
    d = check_product(product(category, allergens), profile(diet=diet))
    assert d.allowed is allowed
    if not allowed:
        assert d.reasons == (R.NOT_IN_DIET,)


def test_prepared_food_is_flagged_uncertain_for_vegetarians():
    d = check_product(product(Category.PREPARED, []), profile(diet=Diet.VEGETARIAN))
    assert d.allowed and d.diet_uncertain
    assert not check_product(product(Category.PREPARED, []), profile()).diet_uncertain


def test_multiple_reasons_are_reported():
    d = check_product(
        product(Category.DAIRY, [Allergen.MILK]), profile(Diet.VEGAN, [Allergen.MILK])
    )
    assert d.reasons == (R.CONTAINS_ALLERGEN, R.NOT_IN_DIET)
