# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which products a person may eat, given their allergies and diet.

Conservative by design: if a person has allergies and a product's allergens are unknown, the
product is excluded. Diet rules use the product category plus its declared allergens (e.g. a
vegan excludes anything declaring milk or eggs).

Limitation: meat is not an EU allergen, so a vegetarian cannot be fully protected from prepared
foods whose ingredients are unknown; such products are allowed but flagged as uncertain.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from annona_core.domain.enums import Allergen, Category, Diet
from annona_core.domain.models import Product, UserProfile


class ExclusionReason(StrEnum):
    CONTAINS_ALLERGEN = "contains_allergen"
    ALLERGENS_UNKNOWN = "allergens_unknown"
    NOT_IN_DIET = "not_in_diet"


class ProductDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reasons: tuple[ExclusionReason, ...] = ()
    allergens_found: tuple[Allergen, ...] = ()
    diet_uncertain: bool = False


_ANIMAL_SEA = {Allergen.FISH, Allergen.CRUSTACEANS, Allergen.MOLLUSCS}

_EXCLUDED_CATEGORIES: dict[Diet, set[Category]] = {
    Diet.OMNIVORE: set(),
    Diet.PESCATARIAN: {Category.MEAT},
    Diet.VEGETARIAN: {Category.MEAT, Category.FISH},
    Diet.VEGAN: {Category.MEAT, Category.FISH, Category.EGGS, Category.DAIRY},
}
_EXCLUDED_ALLERGENS: dict[Diet, set[Allergen]] = {
    Diet.OMNIVORE: set(),
    Diet.PESCATARIAN: set(),
    Diet.VEGETARIAN: set(_ANIMAL_SEA),
    Diet.VEGAN: _ANIMAL_SEA | {Allergen.MILK, Allergen.EGGS},
}
_UNCERTAIN_CATEGORIES = {Category.PREPARED, Category.OTHER}


def check_product(product: Product, profile: UserProfile) -> ProductDecision:
    reasons: list[ExclusionReason] = []
    found: tuple[Allergen, ...] = ()

    if profile.allergies:
        if product.allergens is None:
            reasons.append(ExclusionReason.ALLERGENS_UNKNOWN)
        else:
            found = tuple(a for a in profile.allergies if a in product.allergens)
            if found:
                reasons.append(ExclusionReason.CONTAINS_ALLERGEN)

    declared = set(product.allergens or ())
    if product.category in _EXCLUDED_CATEGORIES[profile.diet] or (
        declared & _EXCLUDED_ALLERGENS[profile.diet]
    ):
        reasons.append(ExclusionReason.NOT_IN_DIET)

    uncertain = profile.diet != Diet.OMNIVORE and product.category in _UNCERTAIN_CATEGORIES
    return ProductDecision(
        allowed=not reasons, reasons=tuple(reasons), allergens_found=found, diet_uncertain=uncertain
    )


def is_product_allowed(product: Product, profile: UserProfile) -> bool:
    return check_product(product, profile).allowed
