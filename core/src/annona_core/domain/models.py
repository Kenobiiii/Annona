# SPDX-License-Identifier: AGPL-3.0-or-later
"""Domain models (pure Pydantic, no persistence).

Conventions:

* ``id`` is ``None`` until the entity is stored.
* Money is integer cents + ISO 4217 currency; quantities are ``Decimal`` in a canonical
  :class:`~annona_core.domain.units.Unit`.
* Nutrition values are per 100 g or per 100 ml of the product as sold (``NutritionFacts.basis``).
* Datetimes are timezone-aware UTC.
* A :class:`Household` owns the shared things (pantry, budget, kitchen, plans, shopping lists,
  receipts); a :class:`UserProfile` is one member with personal nutrition data.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .enums import (
    ActivityLevel,
    Allergen,
    Appliance,
    Category,
    CategorySource,
    Diet,
    Goal,
    HeatLevel,
    HobType,
    MealSlot,
    NutritionSource,
    PendingActionStatus,
    PlanStatus,
    PriceSource,
    ReceiptLineStatus,
    ReceiptStatus,
    RecipeSource,
    Sex,
)
from .money import Money, UnitPrice, unit_price, validate_currency
from .units import Quantity, Unit

Currency = Annotated[str, AfterValidator(validate_currency)]
"""ISO 4217 alphabetic code, upper-cased."""


def utc_now() -> datetime:
    return datetime.now(UTC)


class DomainModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


# --------------------------------------------------------------------------------------------
# Household and people
# --------------------------------------------------------------------------------------------


class Household(DomainModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    weekly_budget_cents: int = Field(ge=0)
    currency: Currency = "EUR"

    @property
    def weekly_budget(self) -> Money:
        return Money(amount_cents=self.weekly_budget_cents, currency=self.currency)


FoodPreference = Literal["avoid", "less"]
ServingGroup = Literal["meat", "fish", "eggs"]


class UserProfile(DomainModel):
    id: int | None = None
    household_id: int
    name: str = Field(min_length=1, max_length=100)
    sex: Sex
    birth_date: date
    height_cm: Decimal = Field(gt=0, lt=300)
    weight_kg: Decimal = Field(gt=0, lt=700)
    activity: ActivityLevel
    goal: Goal = Goal.MAINTAIN
    diet: Diet = Diet.OMNIVORE
    allergies: list[Allergen] = Field(default_factory=list)
    food_preferences: dict[str, FoodPreference] = Field(
        default_factory=dict,
        description="product type -> 'avoid' (never bought for them) or 'less' (small amounts)",
    )
    weekly_servings: dict[ServingGroup, int] = Field(
        default_factory=dict,
        description="minimum servings per week, e.g. {'meat': 3, 'fish': 2}",
    )
    protein_g_per_kg: Decimal | None = Field(
        default=None,
        ge=Decimal("0.8"),
        le=Decimal(3),
        description="protein target in g per kg of body weight; None = the default for the goal "
        "(0.8 g/kg is the adult reference intake, 3 g/kg the top of what sports research uses)",
    )
    allergies_confirmed: bool = Field(
        default=False,
        description="True once the user explicitly answered the allergy question "
        "(an empty list then really means 'no allergies')",
    )

    @field_validator("weekly_servings")
    @classmethod
    def _servings_range(cls, value: dict[str, int]) -> dict[str, int]:
        for group, count in value.items():
            if not 0 <= count <= 21:
                raise ValueError(f"{group}: servings per week must be between 0 and 21")
        return value

    def servings_for_days(self, group: str, days: Decimal | int) -> int:
        """The weekly minimum of a group, scaled to a plan that covers ``days`` days (rounded up).

        "Meat 3 times a week" for a plan of one day asks for 1, not 3: a short plan could never
        satisfy the weekly figure.
        """
        wanted = self.weekly_servings.get(group, 0)  # type: ignore[call-overload]
        return min(wanted, math.ceil(Decimal(wanted) * Decimal(days) / 7))

    def age_on(self, day: date) -> int:
        """Age in whole years on ``day``."""
        years = day.year - self.birth_date.year
        if (day.month, day.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


class Equipment(DomainModel):
    """The household kitchen. Cooking times are adapted with the calibration, not by hob model."""

    id: int | None = None
    household_id: int
    hob_type: HobType = HobType.INDUCTION
    burners: int = Field(default=2, ge=0, le=12)
    power_levels: int | None = Field(default=None, ge=1, le=20, description="max level on the dial")
    oven: bool = False
    microwave: bool = False
    air_fryer: bool = False
    # Calibration: minutes to bring 1 L of tap water to the boil at ``calibration_level``.
    calibration_level: int | None = Field(default=None, ge=1)
    calibration_boil_1l_minutes: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _calibration_pair(self) -> Equipment:
        if (self.calibration_level is None) != (self.calibration_boil_1l_minutes is None):
            raise ValueError("calibration_level and calibration_boil_1l_minutes go together")
        if (
            self.calibration_level is not None
            and self.power_levels is not None
            and self.calibration_level > self.power_levels
        ):
            raise ValueError("calibration_level cannot exceed power_levels")
        return self


# --------------------------------------------------------------------------------------------
# Products and prices
# --------------------------------------------------------------------------------------------


class NutritionFacts(DomainModel):
    """Nutrient amounts per 100 g (``basis=g``) or per 100 ml (``basis=ml``)."""

    basis: Unit = Unit.G
    energy_kcal: Decimal = Field(ge=0)
    protein_g: Decimal = Field(ge=0)
    fat_g: Decimal = Field(ge=0)
    saturated_fat_g: Decimal | None = Field(default=None, ge=0)
    carbohydrates_g: Decimal = Field(ge=0)
    sugars_g: Decimal | None = Field(default=None, ge=0)
    fiber_g: Decimal | None = Field(default=None, ge=0)
    salt_g: Decimal | None = Field(default=None, ge=0)
    source: NutritionSource
    source_ref: str | None = Field(
        default=None, max_length=200, description="e.g. 'usda-fdc:173944'"
    )

    @field_validator("basis")
    @classmethod
    def _mass_or_volume(cls, value: Unit) -> Unit:
        if value == Unit.UNIT:
            raise ValueError("nutrition basis must be g or ml (per 100 g / 100 ml)")
        return value


class Product(DomainModel):
    """Something you can buy. Store products carry ``store_id`` + ``store_sku``; generic foods
    (e.g. sample data) have neither."""

    id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    brand: str | None = None
    ean: str | None = Field(
        default=None, pattern=r"^\d{8,14}$", description="barcode (EAN/UPC/GTIN)"
    )
    category: Category = Category.OTHER
    category_source: CategorySource | None = None
    type: str | None = Field(
        default=None, max_length=100, description="finer grouping, e.g. 'rice'"
    )
    store_id: str | None = Field(default=None, max_length=50, description="provider id")
    store_sku: str | None = Field(default=None, max_length=100)
    package_amount: Decimal | None = Field(default=None, gt=0)
    package_unit: Unit | None = None
    unit_weight_g: Decimal | None = Field(default=None, gt=0)
    density_g_per_ml: Decimal | None = Field(default=None, gt=0)
    allergens: list[Allergen] | None = Field(
        default=None, description="None = unknown; [] = known to contain none of the EU 14"
    )
    allergens_source: NutritionSource | None = Field(
        default=None, description="who set the allergens; same priority as nutrition sources"
    )
    nutrition: NutritionFacts | None = None

    @model_validator(mode="after")
    def _pairs(self) -> Product:
        if (self.store_id is None) != (self.store_sku is None):
            raise ValueError("store_id and store_sku go together")
        if (self.package_amount is None) != (self.package_unit is None):
            raise ValueError("package_amount and package_unit go together")
        return self

    @property
    def package(self) -> Quantity | None:
        if self.package_amount is None or self.package_unit is None:
            return None
        return Quantity(amount=self.package_amount, unit=self.package_unit)


class Price(DomainModel):
    id: int | None = None
    product_id: int
    store_id: str = Field(min_length=1, max_length=50)
    amount_cents: int = Field(ge=0)
    currency: Currency = "EUR"
    source: PriceSource
    observed_at: AwareDatetime = Field(default_factory=utc_now)
    receipt_line_id: int | None = None

    @property
    def money(self) -> Money:
        return Money(amount_cents=self.amount_cents, currency=self.currency)

    def unit_price(self, product: Product) -> UnitPrice:
        """Price per kg / l / unit, using the product's package size."""
        if product.package is None:
            raise ValueError(f"product {product.id} has no package size")
        return unit_price(self.money, product.package)


class PantryItem(DomainModel):
    id: int | None = None
    household_id: int
    product_id: int
    amount: Decimal = Field(ge=0)
    unit: Unit
    expires_at: date | None = None
    added_at: AwareDatetime = Field(default_factory=utc_now)

    @property
    def quantity(self) -> Quantity:
        return Quantity(amount=self.amount, unit=self.unit)


# --------------------------------------------------------------------------------------------
# Recipes and plans
# --------------------------------------------------------------------------------------------


class RecipeStep(DomainModel):
    """One step of a detailed recipe, as the model wrote it; times are adapted when shown.

    ``text`` may contain ``{p12}`` placeholders (12 = a product id) that are replaced by the
    household's amounts of that product, so the model never writes quantities itself.
    ``boil_ml`` marks a "bring this much water/liquid to the boil" step: its time comes from the
    hob calibration (proportional to the volume) instead of ``minutes``.
    """

    text: str = Field(min_length=1, max_length=500)
    heat: HeatLevel = HeatLevel.NONE
    minutes: int | None = Field(default=None, ge=0, le=300)
    boil_ml: int | None = Field(default=None, ge=50, le=10000)
    appliance: Appliance = Appliance.NONE


class Recipe(DomainModel):
    id: int | None = None
    household_id: int
    title: str = Field(min_length=1, max_length=200)
    servings: int = Field(default=1, ge=1)
    steps: list[str] = Field(default_factory=list)
    method: list[RecipeStep] = Field(
        default_factory=list,
        description="detailed steps (empty until the recipe of the day is generated)",
    )
    needs_oven: bool = False
    needs_microwave: bool = False
    needs_air_fryer: bool = False
    source: RecipeSource = RecipeSource.LLM
    created_at: AwareDatetime = Field(default_factory=utc_now)


class RecipeIngredient(DomainModel):
    id: int | None = None
    recipe_id: int
    product_id: int
    amount: Decimal = Field(gt=0)
    unit: Unit


class MealPlan(DomainModel):
    id: int | None = None
    household_id: int
    week_start: date
    status: PlanStatus = PlanStatus.DRAFT
    created_at: AwareDatetime = Field(default_factory=utc_now)

    @field_validator("week_start")
    @classmethod
    def _monday(cls, value: date) -> date:
        if value.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        return value


class PlannedMeal(DomainModel):
    id: int | None = None
    plan_id: int
    profile_id: int | None = Field(default=None, description="None = shared by the household")
    day: date
    slot: MealSlot
    recipe_id: int | None = None
    servings: Decimal = Field(default=Decimal(1), gt=0)
    cooked_at: AwareDatetime | None = Field(
        default=None, description="set when the meal was marked as cooked (pantry deducted once)"
    )


# --------------------------------------------------------------------------------------------
# Shopping and receipts
# --------------------------------------------------------------------------------------------


class ShoppingList(DomainModel):
    id: int | None = None
    household_id: int
    store_id: str = Field(min_length=1, max_length=50)
    plan_id: int | None = None
    created_at: AwareDatetime = Field(default_factory=utc_now)


class ShoppingItem(DomainModel):
    id: int | None = None
    list_id: int
    product_id: int
    packs: int = Field(ge=1)
    unit_price_cents: int | None = Field(default=None, ge=0, description="price per pack, snapshot")
    checked: bool = False
    replaces_product_id: int | None = Field(
        default=None,
        description="set when this product substitutes one the store does not sell",
    )


class Receipt(DomainModel):
    id: int | None = None
    household_id: int
    store_id: str | None = Field(default=None, max_length=50)
    purchased_at: AwareDatetime | None = None
    total_cents: int | None = Field(default=None, ge=0)
    currency: Currency = "EUR"
    image_path: str | None = None
    status: ReceiptStatus = ReceiptStatus.PENDING_REVIEW
    created_at: AwareDatetime = Field(default_factory=utc_now)


class PendingAction(DomainModel):
    """A change proposed by the chat agent that waits for the person's confirmation.

    The model never executes a change: it only proposes one. ``summary`` is written by code (not by
    the model) from ``payload``, and nothing happens until the person confirms it in the app.
    """

    id: int | None = None
    household_id: int
    kind: str = Field(min_length=1, max_length=40)  # "tool" | "swap"
    tool: str = Field(min_length=1, max_length=60)
    payload: dict = Field(default_factory=dict, description="exactly what will be executed")
    summary: str = Field(min_length=1, max_length=2000)
    status: PendingActionStatus = PendingActionStatus.PENDING
    result: dict | None = None
    created_at: AwareDatetime = Field(default_factory=utc_now)
    resolved_at: AwareDatetime | None = None


class ReceiptAlias(DomainModel):
    """What a receipt printed for a product, learned from a confirmation (per store).

    Stores print the same abbreviated name every time, so a confirmed match is remembered and
    reused with full confidence next time.
    """

    id: int | None = None
    household_id: int
    store_id: str | None = Field(default=None, max_length=50)
    normalized_text: str = Field(min_length=1, max_length=200)
    product_id: int
    created_at: AwareDatetime = Field(default_factory=utc_now)


class ReceiptLine(DomainModel):
    id: int | None = None
    receipt_id: int
    raw_text: str = Field(min_length=1)
    amount: Decimal | None = Field(default=None, gt=0, description="quantity bought, if printed")
    unit: Unit | None = None
    total_cents: int = Field(ge=0)
    matched_product_id: int | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    status: ReceiptLineStatus = ReceiptLineStatus.UNMATCHED
