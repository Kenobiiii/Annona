# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLModel tables (persistence only). Domain logic and validation live in ``annona_core``.

Enums are stored as their string values. Children of a household are deleted with it; products
referenced by pantry, recipes or shopping lists cannot be deleted.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from .types import DecimalString, UTCDateTime

# Stable constraint names (needed by Alembic batch migrations on SQLite).
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

CASCADE = "CASCADE"
SET_NULL = "SET NULL"


def dec(*, nullable: bool = False) -> Decimal:
    return Field(default=None, sa_type=DecimalString, nullable=nullable)  # type: ignore[no-any-return]


def utc(*, nullable: bool = False) -> datetime:
    return Field(default=None, sa_type=UTCDateTime, nullable=nullable)  # type: ignore[no-any-return]


class HouseholdRow(SQLModel, table=True):
    __tablename__ = "household"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    weekly_budget_cents: int
    currency: str = Field(max_length=3)


class UserProfileRow(SQLModel, table=True):
    __tablename__ = "user_profile"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", ondelete=CASCADE, index=True)
    name: str
    sex: str
    birth_date: date
    height_cm: Decimal = dec()
    weight_kg: Decimal = dec()
    activity: str
    goal: str
    diet: str
    allergies: list[str] = Field(default_factory=list, sa_type=JSON)
    allergies_confirmed: bool = False


class EquipmentRow(SQLModel, table=True):
    __tablename__ = "equipment"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", ondelete=CASCADE, unique=True)
    hob_type: str
    burners: int
    power_levels: int | None = None
    oven: bool
    microwave: bool
    air_fryer: bool
    calibration_level: int | None = None
    calibration_boil_1l_minutes: Decimal | None = dec(nullable=True)


class ProductRow(SQLModel, table=True):
    __tablename__ = "product"
    __table_args__ = (UniqueConstraint("store_id", "store_sku"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    brand: str | None = None
    ean: str | None = Field(default=None, index=True)
    category: str
    category_source: str | None = None
    type: str | None = None
    store_id: str | None = None
    store_sku: str | None = None
    package_amount: Decimal | None = dec(nullable=True)
    package_unit: str | None = None
    unit_weight_g: Decimal | None = dec(nullable=True)
    density_g_per_ml: Decimal | None = dec(nullable=True)
    allergens: list[str] | None = Field(default=None, sa_type=JSON)  # NULL = unknown
    allergens_source: str | None = None
    # Nutrition per 100 g/ml, flattened (all NULL when unknown).
    nutrition_basis: str | None = None
    nutrition_energy_kcal: Decimal | None = dec(nullable=True)
    nutrition_protein_g: Decimal | None = dec(nullable=True)
    nutrition_fat_g: Decimal | None = dec(nullable=True)
    nutrition_saturated_fat_g: Decimal | None = dec(nullable=True)
    nutrition_carbohydrates_g: Decimal | None = dec(nullable=True)
    nutrition_sugars_g: Decimal | None = dec(nullable=True)
    nutrition_fiber_g: Decimal | None = dec(nullable=True)
    nutrition_salt_g: Decimal | None = dec(nullable=True)
    nutrition_source: str | None = None
    nutrition_source_ref: str | None = Field(default=None, index=True)


class PriceRow(SQLModel, table=True):
    __tablename__ = "price"
    __table_args__ = (
        Index("ix_price_product_store_observed", "product_id", "store_id", "observed_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", ondelete=CASCADE)
    store_id: str
    amount_cents: int
    currency: str = Field(max_length=3)
    source: str
    observed_at: datetime = utc()
    receipt_line_id: int | None = Field(
        default=None, foreign_key="receipt_line.id", ondelete=SET_NULL
    )


class PantryItemRow(SQLModel, table=True):
    __tablename__ = "pantry_item"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", ondelete=CASCADE, index=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    amount: Decimal = dec()
    unit: str
    expires_at: date | None = None
    added_at: datetime = utc()


class RecipeRow(SQLModel, table=True):
    __tablename__ = "recipe"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", ondelete=CASCADE, index=True)
    title: str
    servings: int
    steps: list[str] = Field(default_factory=list, sa_type=JSON)
    needs_oven: bool
    needs_microwave: bool
    needs_air_fryer: bool
    source: str
    created_at: datetime = utc()


class RecipeIngredientRow(SQLModel, table=True):
    __tablename__ = "recipe_ingredient"

    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", ondelete=CASCADE, index=True)
    product_id: int = Field(foreign_key="product.id")
    amount: Decimal = dec()
    unit: str


class MealPlanRow(SQLModel, table=True):
    __tablename__ = "meal_plan"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", ondelete=CASCADE, index=True)
    week_start: date
    status: str
    created_at: datetime = utc()


class PlannedMealRow(SQLModel, table=True):
    __tablename__ = "planned_meal"

    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="meal_plan.id", ondelete=CASCADE, index=True)
    profile_id: int | None = Field(default=None, foreign_key="user_profile.id", ondelete=CASCADE)
    day: date
    slot: str
    recipe_id: int | None = Field(default=None, foreign_key="recipe.id", ondelete=SET_NULL)
    servings: Decimal = dec()


class ShoppingListRow(SQLModel, table=True):
    __tablename__ = "shopping_list"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", ondelete=CASCADE, index=True)
    store_id: str
    plan_id: int | None = Field(default=None, foreign_key="meal_plan.id", ondelete=SET_NULL)
    created_at: datetime = utc()


class ShoppingItemRow(SQLModel, table=True):
    __tablename__ = "shopping_item"

    id: int | None = Field(default=None, primary_key=True)
    list_id: int = Field(foreign_key="shopping_list.id", ondelete=CASCADE, index=True)
    product_id: int = Field(foreign_key="product.id")
    packs: int
    unit_price_cents: int | None = None
    checked: bool


class ReceiptRow(SQLModel, table=True):
    __tablename__ = "receipt"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", ondelete=CASCADE, index=True)
    store_id: str | None = None
    purchased_at: datetime | None = utc(nullable=True)
    total_cents: int | None = None
    currency: str = Field(max_length=3)
    image_path: str | None = None
    status: str
    created_at: datetime = utc()


class ReceiptLineRow(SQLModel, table=True):
    __tablename__ = "receipt_line"

    id: int | None = Field(default=None, primary_key=True)
    receipt_id: int = Field(foreign_key="receipt.id", ondelete=CASCADE, index=True)
    raw_text: str
    amount: Decimal | None = dec(nullable=True)
    unit: str | None = None
    total_cents: int
    matched_product_id: int | None = Field(
        default=None, foreign_key="product.id", ondelete=SET_NULL
    )
    confidence: Decimal | None = dec(nullable=True)
    status: str


class OffCacheRow(SQLModel, table=True):
    """Cached Open Food Facts lookups by barcode, including "not found" answers."""

    __tablename__ = "off_cache"

    ean: str = Field(primary_key=True)
    found: bool
    payload: dict | None = Field(default=None, sa_type=JSON)
    fetched_at: datetime = utc()
