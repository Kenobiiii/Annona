# SPDX-License-Identifier: AGPL-3.0-or-later
"""Product classification into :class:`Category` and a free-text ``type``.

Rules first, in this order of trust: the store's own category path (deepest level first), then
Open Food Facts category tags, then keywords in the product name. Products no rule recognises are
left for an LLM classifier (Phase 5); until then :class:`LLMClassifierStub` returns nothing.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from annona_core.domain import Category, CategorySource

C = Category


@dataclass(frozen=True)
class ClassificationInput:
    name: str
    store_path: tuple[str, ...] = ()
    off_categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class Classification:
    category: Category
    type: str | None
    source: CategorySource


class Classifier(Protocol):
    def classify(self, item: ClassificationInput) -> Classification | None: ...


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _matches(keyword: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}", text) is not None


# Spanish store category keywords (accent-insensitive, prefix match on words).
STORE_KEYWORDS: Sequence[tuple[str, Category]] = (
    # Snacks first: "Aperitivos > Patatas fritas y snacks" must not become vegetables.
    ("snack", C.OTHER),
    ("aperitivo", C.OTHER),
    ("golosina", C.OTHER),
    ("huevo", C.EGGS),
    ("leche", C.DAIRY),
    ("yogur", C.DAIRY),
    ("queso", C.DAIRY),
    ("mantequilla", C.DAIRY),
    ("nata", C.DAIRY),
    ("pescado", C.FISH),
    ("marisco", C.FISH),
    ("atun", C.FISH),
    ("carne", C.MEAT),
    ("pollo", C.MEAT),
    ("cerdo", C.MEAT),
    ("vacuno", C.MEAT),
    ("embutido", C.MEAT),
    ("charcuteria", C.MEAT),
    ("legumbre", C.LEGUMES),
    ("panaderia", C.BAKERY),
    ("bolleria", C.BAKERY),
    ("pan ", C.BAKERY),
    ("arroz", C.GRAINS),
    ("pasta", C.GRAINS),
    ("cereales", C.GRAINS),
    ("harina", C.GRAINS),
    ("fruta", C.FRUIT),
    ("verdura", C.VEGETABLES),
    ("hortaliza", C.VEGETABLES),
    ("ensalada", C.VEGETABLES),
    ("aceite", C.OILS_FATS),
    ("frutos secos", C.NUTS_SEEDS),
    ("salsa", C.CONDIMENTS),
    ("especia", C.CONDIMENTS),
    ("vinagre", C.CONDIMENTS),
    ("pizza", C.PREPARED),
    ("platos preparados", C.PREPARED),
    ("agua", C.BEVERAGES),
    ("refresco", C.BEVERAGES),
    ("zumo", C.BEVERAGES),
    ("bebida", C.BEVERAGES),
    ("cerveza", C.BEVERAGES),
    ("vino", C.BEVERAGES),
    ("cafe", C.BEVERAGES),
)

# Open Food Facts category tags, most specific first (beverages last: many dairies are drinks).
OFF_TAGS: Sequence[tuple[str, Category]] = (
    ("en:eggs", C.EGGS),
    ("en:dairies", C.DAIRY),
    ("en:cheeses", C.DAIRY),
    ("en:yogurts", C.DAIRY),
    ("en:fishes", C.FISH),
    ("en:seafood", C.FISH),
    ("en:meats", C.MEAT),
    ("en:poultries", C.MEAT),
    ("en:legumes", C.LEGUMES),
    ("en:breads", C.BAKERY),
    ("en:pastas", C.GRAINS),
    ("en:rices", C.GRAINS),
    ("en:cereal-grains", C.GRAINS),
    ("en:breakfast-cereals", C.GRAINS),
    ("en:fruits", C.FRUIT),
    ("en:vegetables", C.VEGETABLES),
    ("en:olive-oils", C.OILS_FATS),
    ("en:vegetable-oils", C.OILS_FATS),
    ("en:fats", C.OILS_FATS),
    ("en:nuts", C.NUTS_SEEDS),
    ("en:nuts-and-their-products", C.NUTS_SEEDS),
    ("en:sauces", C.CONDIMENTS),
    ("en:condiments", C.CONDIMENTS),
    ("en:meals", C.PREPARED),
    ("en:beverages", C.BEVERAGES),
)

# Name keywords -> (category, type). Spanish and English.
NAME_KEYWORDS: Sequence[tuple[str, Category, str]] = (
    ("patatas fritas", C.OTHER, "crisps"),
    ("aceite de oliva", C.OILS_FATS, "olive_oil"),
    ("olive oil", C.OILS_FATS, "olive_oil"),
    ("arroz", C.GRAINS, "rice"),
    ("rice", C.GRAINS, "rice"),
    ("macarron", C.GRAINS, "pasta"),
    ("espagueti", C.GRAINS, "pasta"),
    ("pasta", C.GRAINS, "pasta"),
    ("avena", C.GRAINS, "oats"),
    ("lenteja", C.LEGUMES, "lentils"),
    ("garbanzo", C.LEGUMES, "chickpeas"),
    ("alubia", C.LEGUMES, "beans"),
    ("judia", C.LEGUMES, "beans"),
    ("huevo", C.EGGS, "egg"),
    ("egg", C.EGGS, "egg"),
    ("queso", C.DAIRY, "cheese"),
    ("yogur", C.DAIRY, "yogurt"),
    ("batido", C.DAIRY, "milkshake"),
    ("leche", C.DAIRY, "milk"),
    ("milk", C.DAIRY, "milk"),
    ("mantequilla", C.OILS_FATS, "butter"),
    ("pechuga de pollo", C.MEAT, "chicken"),
    ("pollo", C.MEAT, "chicken"),
    ("cerdo", C.MEAT, "pork"),
    ("ternera", C.MEAT, "beef"),
    ("atun", C.FISH, "tuna"),
    ("sardina", C.FISH, "sardines"),
    ("salmon", C.FISH, "salmon"),
    ("merluza", C.FISH, "hake"),
    ("bacalao", C.FISH, "cod"),
    ("patata", C.VEGETABLES, "potato"),
    ("cebolla", C.VEGETABLES, "onion"),
    ("tomate", C.VEGETABLES, "tomato"),
    ("zanahoria", C.VEGETABLES, "carrot"),
    ("espinaca", C.VEGETABLES, "spinach"),
    ("pimiento", C.VEGETABLES, "pepper"),
    ("brocoli", C.VEGETABLES, "broccoli"),
    ("calabacin", C.VEGETABLES, "zucchini"),
    ("lechuga", C.VEGETABLES, "lettuce"),
    ("platano", C.FRUIT, "banana"),
    ("manzana", C.FRUIT, "apple"),
    ("naranja", C.FRUIT, "orange"),
    ("almendra", C.NUTS_SEEDS, "almonds"),
    ("nuez", C.NUTS_SEEDS, "walnuts"),
    ("pan ", C.BAKERY, "bread"),
)


def _name_type(name: str) -> tuple[Category, str] | None:
    text = _norm(name) + " "
    for keyword, category, kind in NAME_KEYWORDS:
        if _matches(keyword, text):
            return category, kind
    return None


class RuleClassifier:
    source = CategorySource.RULE

    def classify(self, item: ClassificationInput) -> Classification | None:
        by_name = _name_type(item.name)
        kind = by_name[1] if by_name else None
        for level in reversed(item.store_path):
            text = _norm(level) + " "
            for keyword, category in STORE_KEYWORDS:
                if _matches(keyword, text):
                    return Classification(category, kind, self.source)
        for tag, category in OFF_TAGS:
            if tag in item.off_categories:
                return Classification(category, kind, self.source)
        if by_name:
            return Classification(by_name[0], kind, self.source)
        return None


class LLMClassifierStub:
    """Placeholder for the Phase 5 LLM classifier (small tier, batched, cached)."""

    source = CategorySource.LLM

    def classify(self, item: ClassificationInput) -> Classification | None:
        return None


def classify(item: ClassificationInput, classifiers: Sequence[Classifier]) -> Classification | None:
    for classifier in classifiers:
        result = classifier.classify(item)
        if result is not None:
            return result
    return None
