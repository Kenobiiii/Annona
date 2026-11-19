# SPDX-License-Identifier: AGPL-3.0-or-later
"""Enumerations shared by the domain models. Values are stable strings stored in the database."""

from enum import StrEnum


class Sex(StrEnum):
    """Biological sex, used only by the BMR formula (Mifflin-St Jeor)."""

    FEMALE = "female"
    MALE = "male"


class ActivityLevel(StrEnum):
    """Physical activity level categories for adults.

    The four categories of the National Academies' *Dietary Reference Intakes for Energy* (2023),
    which EFSA (2013) also uses with almost the same values. Factors live in
    :mod:`annona_core.nutrition.settings`; :mod:`annona_core.nutrition.activity_quiz` helps a user
    pick one.
    """

    INACTIVE = "inactive"
    LOW_ACTIVE = "low_active"
    ACTIVE = "active"
    VERY_ACTIVE = "very_active"


class Goal(StrEnum):
    CUT = "cut"
    MAINTAIN = "maintain"
    BULK = "bulk"


class Diet(StrEnum):
    OMNIVORE = "omnivore"
    PESCATARIAN = "pescatarian"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"


class Allergen(StrEnum):
    """The 14 allergens that must be declared in the EU (Regulation (EU) No 1169/2011, Annex II)."""

    GLUTEN = "gluten"
    CRUSTACEANS = "crustaceans"
    EGGS = "eggs"
    FISH = "fish"
    PEANUTS = "peanuts"
    SOYBEANS = "soybeans"
    MILK = "milk"
    NUTS = "nuts"
    CELERY = "celery"
    MUSTARD = "mustard"
    SESAME = "sesame"
    SULPHITES = "sulphites"
    LUPIN = "lupin"
    MOLLUSCS = "molluscs"


class Category(StrEnum):
    """Coarse product category. Finer grouping lives in ``Product.type`` (free text)."""

    FRUIT = "fruit"
    VEGETABLES = "vegetables"
    GRAINS = "grains"
    LEGUMES = "legumes"
    DAIRY = "dairy"
    EGGS = "eggs"
    MEAT = "meat"
    FISH = "fish"
    OILS_FATS = "oils_fats"
    NUTS_SEEDS = "nuts_seeds"
    BAKERY = "bakery"
    BEVERAGES = "beverages"
    CONDIMENTS = "condiments"
    PREPARED = "prepared"
    OTHER = "other"


class NutritionSource(StrEnum):
    """Where nutrition values (or allergens) come from. See :data:`NUTRITION_SOURCE_PRIORITY`."""

    MANUAL = "manual"
    LABEL_SCAN = "label_scan"
    OFF = "off"
    LLM_ESTIMATE = "llm_estimate"
    SAMPLE = "sample"


# Higher wins. A source may only replace values coming from the same or a lower priority source,
# so manual edits are never overwritten by automatic ones.
NUTRITION_SOURCE_PRIORITY: dict[NutritionSource, int] = {
    NutritionSource.MANUAL: 50,
    NutritionSource.LABEL_SCAN: 40,
    NutritionSource.OFF: 30,
    NutritionSource.LLM_ESTIMATE: 20,
    NutritionSource.SAMPLE: 10,
}


def nutrition_source_may_replace(current: NutritionSource | None, new: NutritionSource) -> bool:
    """True if values from ``new`` may overwrite values currently coming from ``current``."""
    if current is None:
        return True
    return NUTRITION_SOURCE_PRIORITY[new] >= NUTRITION_SOURCE_PRIORITY[current]


class CategorySource(StrEnum):
    """Who set a product's category. See :data:`CATEGORY_SOURCE_PRIORITY`."""

    MANUAL = "manual"
    RULE = "rule"
    LLM = "llm"


# Higher wins; manual corrections are never overwritten by automatic classification.
CATEGORY_SOURCE_PRIORITY: dict[CategorySource, int] = {
    CategorySource.MANUAL: 30,
    CategorySource.RULE: 20,
    CategorySource.LLM: 10,
}


def category_source_may_replace(current: CategorySource | None, new: CategorySource) -> bool:
    if current is None:
        return True
    return CATEGORY_SOURCE_PRIORITY[new] >= CATEGORY_SOURCE_PRIORITY[current]


class PriceSource(StrEnum):
    SCRAPE = "scrape"
    RECEIPT = "receipt"
    MANUAL = "manual"


class HobType(StrEnum):
    INDUCTION = "induction"
    CERAMIC = "ceramic"
    ELECTRIC_COIL = "electric_coil"
    GAS = "gas"
    NONE = "none"


class MealSlot(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class RecipeSource(StrEnum):
    LLM = "llm"
    MANUAL = "manual"


class ReceiptStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"


class ReceiptLineStatus(StrEnum):
    UNMATCHED = "unmatched"
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    IGNORED = "ignored"
