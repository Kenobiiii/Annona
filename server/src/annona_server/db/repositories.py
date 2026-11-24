# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQL implementations of the ``annona_core.domain.repositories`` interfaces.

Repositories ``flush`` but never ``commit``; use :func:`annona_server.db.engine.session_scope`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, SQLModel, col, select

from annona_core.domain import (
    Equipment,
    Household,
    MealPlan,
    NutritionFacts,
    PantryItem,
    PendingAction,
    PlannedMeal,
    Price,
    Product,
    Receipt,
    ReceiptAlias,
    ReceiptLine,
    Recipe,
    RecipeIngredient,
    ShoppingItem,
    ShoppingList,
    StoreConnection,
    UserProfile,
)

from . import tables as t


class NotFoundError(LookupError):
    pass


class SqlRepository[D: BaseModel, R: SQLModel]:
    """Generic CRUD for flat entities whose row has the same field names as the domain model."""

    domain: type[D]
    row: type[R]

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- mapping (override for non-flat entities) --
    def to_row(self, entity: D) -> dict[str, Any]:
        return entity.model_dump()

    def to_domain(self, row: R) -> D:
        return self.domain.model_validate(row.model_dump())

    # -- CRUD --
    def add(self, entity: D) -> D:
        if getattr(entity, "id", None) is not None:
            raise ValueError("entity already has an id; use update()")
        row = self.row(**self.to_row(entity))
        self.session.add(row)
        self.session.flush()
        self.session.refresh(row)
        return self.to_domain(row)

    def get(self, entity_id: int) -> D | None:
        row = self.session.get(self.row, entity_id)
        return None if row is None else self.to_domain(row)

    def list(self, **filters: Any) -> Sequence[D]:
        stmt = select(self.row).filter_by(**filters).order_by(self._id_col())
        return [self.to_domain(r) for r in self.session.exec(stmt)]

    def update(self, entity: D) -> D:
        entity_id = getattr(entity, "id", None)
        row = self.session.get(self.row, entity_id) if entity_id is not None else None
        if row is None:
            raise NotFoundError(f"{self.domain.__name__} {entity_id} not found")
        for key, value in self.to_row(entity).items():
            setattr(row, key, value)
        self.session.flush()
        self.session.refresh(row)
        return self.to_domain(row)

    def delete(self, entity_id: int) -> None:
        row = self.session.get(self.row, entity_id)
        if row is None:
            raise NotFoundError(f"{self.domain.__name__} {entity_id} not found")
        self.session.delete(row)
        self.session.flush()

    def _id_col(self) -> Any:
        return col(cast(Any, self.row).id)


def _repo[D: BaseModel, R: SQLModel](domain: type[D], row: type[R]) -> type[SqlRepository[D, R]]:
    return cast(
        type[SqlRepository[D, R]],
        type(f"{domain.__name__}Repository", (SqlRepository,), {"domain": domain, "row": row}),
    )


HouseholdRepository = _repo(Household, t.HouseholdRow)
UserProfileRepository = _repo(UserProfile, t.UserProfileRow)
EquipmentRepository = _repo(Equipment, t.EquipmentRow)
RecipeRepository = _repo(Recipe, t.RecipeRow)
RecipeIngredientRepository = _repo(RecipeIngredient, t.RecipeIngredientRow)
MealPlanRepository = _repo(MealPlan, t.MealPlanRow)
PlannedMealRepository = _repo(PlannedMeal, t.PlannedMealRow)
ShoppingListRepository = _repo(ShoppingList, t.ShoppingListRow)
ShoppingItemRepository = _repo(ShoppingItem, t.ShoppingItemRow)
ReceiptRepository = _repo(Receipt, t.ReceiptRow)
ReceiptLineRepository = _repo(ReceiptLine, t.ReceiptLineRow)
ReceiptAliasRepository = _repo(ReceiptAlias, t.ReceiptAliasRow)
PendingActionRepository = _repo(PendingAction, t.PendingActionRow)
StoreConnectionRepository = _repo(StoreConnection, t.StoreConnectionRow)


_NUTRITION_FIELDS = (
    "basis",
    "energy_kcal",
    "protein_g",
    "fat_g",
    "saturated_fat_g",
    "carbohydrates_g",
    "sugars_g",
    "fiber_g",
    "salt_g",
    "source",
    "source_ref",
)


class SqlProductRepository(SqlRepository[Product, t.ProductRow]):
    """Flattens ``Product.nutrition`` into ``nutrition_*`` columns."""

    domain = Product
    row = t.ProductRow

    def to_row(self, entity: Product) -> dict[str, Any]:
        data = entity.model_dump(exclude={"nutrition"})
        nutrition = entity.nutrition.model_dump() if entity.nutrition else {}
        for name in _NUTRITION_FIELDS:
            data[f"nutrition_{name}"] = nutrition.get(name)
        return data

    def to_domain(self, row: t.ProductRow) -> Product:
        data = row.model_dump()
        nutrition = {name: data.pop(f"nutrition_{name}") for name in _NUTRITION_FIELDS}
        data["nutrition"] = (
            NutritionFacts.model_validate(nutrition) if nutrition["source"] is not None else None
        )
        return Product.model_validate(data)

    def get_by_store_sku(self, store_id: str, store_sku: str) -> Product | None:
        stmt = select(t.ProductRow).where(
            t.ProductRow.store_id == store_id, t.ProductRow.store_sku == store_sku
        )
        row = self.session.exec(stmt).first()
        return None if row is None else self.to_domain(row)

    def find_by_ean(self, ean: str) -> Sequence[Product]:
        return self.list(ean=ean)

    def get_by_nutrition_ref(self, source_ref: str) -> Product | None:
        found = self.list(nutrition_source_ref=source_ref)
        return found[0] if found else None

    def search(self, text: str, limit: int = 20) -> Sequence[Product]:
        """Case-insensitive substring match on the name (good enough until full-text search)."""
        pattern = f"%{text.strip().lower()}%"
        stmt = (
            select(t.ProductRow)
            .where(func.lower(t.ProductRow.name).like(pattern))
            .order_by(col(t.ProductRow.name))
            .limit(limit)
        )
        return [self.to_domain(r) for r in self.session.exec(stmt)]


class SqlPriceRepository(SqlRepository[Price, t.PriceRow]):
    domain = Price
    row = t.PriceRow

    def history(self, product_id: int, store_id: str | None = None) -> Sequence[Price]:
        """Oldest first."""
        stmt = select(t.PriceRow).where(t.PriceRow.product_id == product_id)
        if store_id is not None:
            stmt = stmt.where(t.PriceRow.store_id == store_id)
        stmt = stmt.order_by(col(t.PriceRow.observed_at), col(t.PriceRow.id))
        return [self.to_domain(r) for r in self.session.exec(stmt)]

    def latest(self, product_id: int, store_id: str | None = None) -> Price | None:
        stmt = select(t.PriceRow).where(t.PriceRow.product_id == product_id)
        if store_id is not None:
            stmt = stmt.where(t.PriceRow.store_id == store_id)
        stmt = stmt.order_by(col(t.PriceRow.observed_at).desc(), col(t.PriceRow.id).desc())
        row = self.session.exec(stmt.limit(1)).first()
        return None if row is None else self.to_domain(row)


class SqlPantryRepository(SqlRepository[PantryItem, t.PantryItemRow]):
    domain = PantryItem
    row = t.PantryItemRow

    def for_household(self, household_id: int) -> Sequence[PantryItem]:
        return self.list(household_id=household_id)
