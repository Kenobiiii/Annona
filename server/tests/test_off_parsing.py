# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parsing of Open Food Facts payloads. Inputs here are SYNTHETIC, shaped like the API's fields."""

from decimal import Decimal

from annona_core.domain import Allergen, NutritionSource, Unit
from annona_server.ingest.off import parse_allergens, parse_nutrition, parse_off_product

NUTRIMENTS = {
    "energy-kcal_100g": 344,
    "proteins_100g": 8.2,
    "fat_100g": 1,
    "carbohydrates_100g": 75,
    "salt_100g": 0.01,
}


def test_nutrition_per_100g_with_exact_decimals():
    n = parse_nutrition("1", {"nutriments": NUTRIMENTS, "nutrition_data_per": "100g"})
    assert n.basis == Unit.G
    assert n.protein_g == Decimal("8.2")  # from str(8.2), not float binary noise
    assert n.salt_g == Decimal("0.01")
    assert n.sugars_g is None
    assert (n.source, n.source_ref) == (NutritionSource.OFF, "off:1")


def test_liquids_use_per_100ml():
    n = parse_nutrition("1", {"nutriments": NUTRIMENTS, "nutrition_data_per": "100ml"})
    assert n.basis == Unit.ML
    n = parse_nutrition("1", {"nutriments": NUTRIMENTS, "product_quantity_unit": "l"})
    assert n.basis == Unit.ML


def test_incomplete_nutrition_is_rejected_not_guessed():
    partial = {k: v for k, v in NUTRIMENTS.items() if k != "fat_100g"}
    assert parse_nutrition("1", {"nutriments": partial}) is None
    assert parse_nutrition("1", {"nutriments": {**NUTRIMENTS, "fat_100g": "abc"}}) is None


def test_allergens():
    assert parse_allergens(["en:milk", "en:gluten", "en:milk"]) == [Allergen.GLUTEN, Allergen.MILK]
    assert parse_allergens(["en:none"]) == []  # explicitly none
    assert parse_allergens([]) is None  # unknown: nobody filled it in
    assert parse_allergens(None) is None
    assert parse_allergens(["en:peach"]) is None  # only non-EU allergens: EU 14 unknown


def test_product():
    p = parse_off_product("123", {"product_name": " Arroz ", "categories_tags": ["en:rices"]})
    assert (p.name, p.nutrition, p.allergens, p.categories) == ("Arroz", None, None, ("en:rices",))
