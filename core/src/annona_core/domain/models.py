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

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

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
    Category,
    Diet,
    Goal,
    HobType,
    MealSlot,
    NutritionSource,
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
    type: str | None = Field(
        default=None, max_length=100, description="finer grouping, e.g. 'rice'"
    )
    store_id: str | None = Field(default=None, max_length=50, description="provider id")
    store_sku: str | None = Field(default=None, max_length=100)
    package_amount: Decimal | None = Field(default=None, gt=0)
    package_unit: Unit | None = None
    unit_weight_g: Decimal | None = Field(default=None, gt=0)
    density_g_per_ml: Decimal | None = Field(default=None, gt=0)
    allergens: list[Allergen] = Field(default_factory=list)
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


class Recipe(DomainModel):
    id: int | None = None
    household_id: int
    title: str = Field(min_length=1, max_length=200)
    servings: int = Field(default=1, ge=1)
    steps: list[str] = Field(default_factory=list)
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
