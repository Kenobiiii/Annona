# SPDX-License-Identifier: AGPL-3.0-or-later
"""Inputs and outputs of the shopping optimiser."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from annona_core.domain import PantryItem, Product, UserProfile
from annona_core.nutrition import WeeklyTargets


class OptimizerSettings(BaseModel):
    """Defaults; every value is overridable.

    * ``fruit_veg_g_per_person_day``: WHO healthy-diet fact sheet, at least 400 g of fruit and
      vegetables a day, excluding potatoes and other starchy roots.
    * ``max_kcal_share_per_product``: project choice for variety (no single product above 20 %
      of the week's calories).
    * ``assumed_density_g_per_ml``: used ONLY when a product sold by volume has nutrition per
      100 g (or the reverse) and no density is known; such lines are flagged ``estimated``.
    """

    model_config = ConfigDict(frozen=True)

    days: int = Field(default=7, ge=1)
    fruit_veg_g_per_person_day: Decimal = Decimal(400)
    starchy_types: frozenset[str] = frozenset({"potato", "sweet_potato", "cassava", "yam"})
    max_kcal_share_per_product: Decimal = Decimal("0.20")
    max_packs_per_product: int = Field(default=30, ge=1)
    assumed_density_g_per_ml: Decimal = Decimal(1)
    time_limit_s: float = 20.0


class Offer(BaseModel):
    """A product the store sells at a price per pack."""

    model_config = ConfigDict(frozen=True)

    product: Product
    price_cents: int = Field(ge=0)


class Problem(BaseModel):
    model_config = ConfigDict(frozen=True)

    offers: list[Offer]
    pantry: list[PantryItem] = Field(default_factory=list)
    members: list[UserProfile]
    targets: WeeklyTargets  # for the whole household and the whole period
    budget_cents: int = Field(ge=0)
    currency: str = "EUR"
    settings: OptimizerSettings = OptimizerSettings()


class AllergenNote(BaseModel):
    model_config = ConfigDict(frozen=True)

    member: str
    reasons: list[str]  # e.g. ["contains_allergen: milk"], ["allergens_unknown"], ["not_in_diet"]


class Line(BaseModel):
    """One product in the result."""

    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    packs_to_buy: int
    cost_cents: int
    pack_amount: Decimal
    pack_unit: str
    used_from_pantry: Decimal  # in the nutrition basis unit (g or ml)
    used_total: Decimal  # consumed this period, nutrition basis unit
    basis_unit: str
    kcal: Decimal
    estimated: bool = False  # a conversion used an assumed density
    not_for: list[AllergenNote] = Field(default_factory=list)


class Totals(BaseModel):
    model_config = ConfigDict(frozen=True)

    energy_kcal: Decimal
    protein_g: Decimal
    fat_g: Decimal
    carbohydrates_g: Decimal
    fruit_veg_g: Decimal


class Shortfall(BaseModel):
    """A constraint that cannot be met, and by how much."""

    model_config = ConfigDict(frozen=True)

    constraint: str  # budget, energy_min, energy_max, protein_min, fat_min, fat_max, fruit_veg_min,
    # variety
    amount: Decimal
    unit: str
    detail: str


class DataWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    issue: str  # excluded_no_nutrition, excluded_no_unit_weight, excluded_no_package,
    # density_estimated, excluded_nobody_can_eat
    detail: str


class Result(BaseModel):
    status: str  # "optimal" | "infeasible" | "no_candidates" | "solver_error"
    lines: list[Line] = Field(default_factory=list)
    total_cost_cents: int = 0
    currency: str = "EUR"
    period_totals: Totals | None = None
    daily_average: Totals | None = None
    shortfalls: list[Shortfall] = Field(default_factory=list)
    warnings: list[DataWarning] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        """False when some results rest on estimated or missing product data."""
        return not self.warnings
