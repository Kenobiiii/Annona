# SPDX-License-Identifier: AGPL-3.0-or-later
"""Load the bundled sample foods (USDA FoodData Central, public domain) into the database.

The data is SAMPLE DATA for development and demos (``NutritionSource.SAMPLE``). Loading is
idempotent: foods are matched by their ``usda-fdc:<id>`` reference, and products whose nutrition
already comes from a better source (e.g. a manual edit) are left untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from sqlmodel import Session

from annona_core.domain import NutritionFacts, Product, nutrition_source_may_replace
from annona_server.db.repositories import SqlProductRepository


@dataclass(frozen=True)
class SeedReport:
    created: int = 0
    updated: int = 0
    skipped: int = 0


def sample_foods() -> list[dict[str, Any]]:
    raw = resources.files(__package__).joinpath("sample_foods.json").read_text(encoding="utf-8")
    return json.loads(raw)["foods"]


def _to_product(food: dict[str, Any]) -> Product:
    return Product(
        name=food["name"],
        category=food["category"],
        type=food["type"],
        allergens=food["allergens"],
        unit_weight_g=food.get("unit_weight_g"),
        density_g_per_ml=food.get("density_g_per_ml"),
        nutrition=NutritionFacts.model_validate(food["nutrition"]),
    )


def load_sample_foods(session: Session) -> SeedReport:
    """Insert or refresh the sample foods. The caller commits."""
    repo = SqlProductRepository(session)
    created = updated = skipped = 0
    for food in sample_foods():
        product = _to_product(food)
        assert product.nutrition is not None and product.nutrition.source_ref is not None
        existing = repo.get_by_nutrition_ref(product.nutrition.source_ref)
        if existing is None:
            repo.add(product)
            created += 1
            continue
        current = existing.nutrition.source if existing.nutrition else None
        if not nutrition_source_may_replace(current, product.nutrition.source):
            skipped += 1
            continue
        refreshed = product.model_copy(update={"id": existing.id})
        if refreshed == existing:
            skipped += 1
        else:
            repo.update(refreshed)
            updated += 1
    return SeedReport(created=created, updated=updated, skipped=skipped)
