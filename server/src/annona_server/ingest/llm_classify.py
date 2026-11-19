# SPDX-License-Identifier: AGPL-3.0-or-later
"""LLM product classifier (``small`` tier, batched, cached). Used for products the rules miss.

The model only chooses a category from a closed list and a short type label; Pydantic validates
the answer and code checks that every index comes back exactly once.

Prompts are versioned so evals can compare them (see ``docs/evals.md``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from annona_core.domain import Category, CategorySource
from annona_core.llm import CallStats, LLMClient, LLMRequest, Message, Tier

from .classify import Classification, ClassificationInput

TASK = "classify_products"

CATEGORY_GUIDE = """Categories (choose exactly one):
- fruit: fresh, dried or canned fruit
- vegetables: fresh, frozen or canned vegetables, potatoes, olives, green beans
- grains: rice, pasta, oats, flour, quinoa, breakfast cereals, cereal bars
- legumes: dried or canned lentils, chickpeas, beans; tofu
- dairy: animal milk, yogurt, kefir, cheese, cream, dairy desserts and milkshakes
- eggs: eggs
- meat: fresh meat, poultry, cold cuts, ham, sausages
- fish: fish, seafood, canned fish and shellfish
- oils_fats: oils, butter, margarine, lard
- nuts_seeds: nuts, peanuts, seeds, nut and seed butters (incl. tahini)
- bakery: bread, toast, breadcrumbs, crackers, biscuits, pastries, wraps
- beverages: water, soft drinks, juices, coffee, tea, plant-based drinks (oat, almond, soy, rice)
- condiments: sauces, mayonnaise, vinegar, spices, salt, food colouring
- prepared: ready meals, pizza, lasagna, soups, gazpacho, potato omelette, hummus, guacamole,
  ready salads, instant mashed potato
- other: sweets, chocolate, chewing gum, crisps and snacks, plant-based yogurt alternatives,
  anything that is not food, and products you cannot identify

Rules:
- Classify by what the product IS, not by a word in its name: "almond drink" is a beverage,
  "butter biscuits" are bakery, flat green beans are vegetables.
- Plant-based drinks and yogurt alternatives are never dairy.
- type: a short lowercase English label with underscores, e.g. "milk", "oat_drink", "pasta".
  Use null if unsure."""

INPUT_FORMAT = (
    "Each product is given as 'index: name', optionally followed by the store's category path "
    "and Open Food Facts tags. Names may be Spanish, Portuguese or English, and abbreviated."
)

PROMPTS: dict[str, str] = {
    "v1_plain": (
        "Classify supermarket products into food categories.\n"
        f"{INPUT_FORMAT}\n\n{CATEGORY_GUIDE}\n\n"
        "Return one item per product, keeping its index."
    ),
    "v1_role": (
        "You are an expert in Spanish supermarket products and food categorisation.\n"
        "Classify supermarket products into food categories.\n"
        f"{INPUT_FORMAT}\n\n{CATEGORY_GUIDE}\n\n"
        "Return one item per product, keeping its index."
    ),
}
# Chosen by eval (2026-11-19, deepseek-flash, 87 items x 3 runs): v1_role 99.2% mean accuracy vs
# v1_plain 97.3%, same cost. See evals/results/.
DEFAULT_PROMPT = "v1_role"

TypeLabel = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=40)]


class ClassifiedItem(BaseModel):
    index: int = Field(ge=0)
    category: Category
    type: TypeLabel | None = None


class ClassifiedBatch(BaseModel):
    items: list[ClassifiedItem]


def _line(index: int, item: ClassificationInput) -> str:
    parts = [f"{index}: {item.name}"]
    if item.store_path:
        parts.append("store: " + " > ".join(item.store_path))
    if item.off_categories:
        parts.append("tags: " + ", ".join(item.off_categories[:6]))
    return " | ".join(parts)


def _clean_type(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned or None


class LLMClassifier:
    source = CategorySource.LLM

    def __init__(
        self, llm: LLMClient, *, prompt: str = DEFAULT_PROMPT, batch_size: int = 20
    ) -> None:
        if prompt not in PROMPTS:
            raise ValueError(f"unknown prompt {prompt!r}; known: {sorted(PROMPTS)}")
        self.llm = llm
        self.prompt = prompt
        self.batch_size = batch_size

    def classify(self, item: ClassificationInput) -> Classification | None:
        return self.classify_batch([item])[0]

    def classify_batch(
        self,
        items: Sequence[ClassificationInput],
        *,
        use_cache: bool = True,
        stats: list[CallStats] | None = None,
        task: str = TASK,
    ) -> list[Classification | None]:
        """One prediction per input (``None`` if the model skipped it)."""
        results: list[Classification | None] = []
        for start in range(0, len(items), self.batch_size):
            chunk = items[start : start + self.batch_size]
            call = CallStats()
            answer = self.llm.complete_json(
                LLMRequest(
                    tier=Tier.SMALL,
                    task=task,
                    system=PROMPTS[self.prompt],
                    messages=(
                        Message("user", "\n".join(_line(i, x) for i, x in enumerate(chunk))),
                    ),
                    max_tokens=60 * len(chunk) + 200,
                ),
                ClassifiedBatch,
                use_cache=use_cache,
                stats=call,
            )
            if stats is not None:
                stats.append(call)
            by_index: dict[int, ClassifiedItem] = {}
            for got in answer.items:
                if got.index < len(chunk) and got.index not in by_index:
                    by_index[got.index] = got  # out-of-range or duplicate indexes are ignored
            results.extend(
                Classification(by_index[i].category, _clean_type(by_index[i].type), self.source)
                if i in by_index
                else None
                for i in range(len(chunk))
            )
        return results
