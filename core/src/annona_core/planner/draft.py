# SPDX-License-Identifier: AGPL-3.0-or-later
"""The JSON the LLM must return: meals, per-person ingredient amounts and a short summary.

Amounts are per person for one serving, in the product's nutrition basis unit (g or ml); the
code rescales them per person and day afterwards, so the model never has to do arithmetic.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from annona_core.domain import MealSlot


class Appliance(StrEnum):
    HOB = "hob"
    OVEN = "oven"
    MICROWAVE = "microwave"
    AIR_FRYER = "air_fryer"
    NONE = "none"  # no cooking (salads, yogurt, sandwiches)


class DraftIngredient(BaseModel):
    product_id: int
    amount: Decimal = Field(gt=0, le=2000)


class DraftMeal(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0 = Monday
    slot: MealSlot
    title: str = Field(min_length=2, max_length=80)
    appliances: list[Appliance] = Field(default_factory=list, max_length=4)
    ingredients: list[DraftIngredient] = Field(min_length=1, max_length=10)
    summary: str = Field(min_length=2, max_length=300)
    skipped_by: list[str] = Field(default_factory=list)  # member names who do not eat it


class PlanDraft(BaseModel):
    meals: list[DraftMeal]
