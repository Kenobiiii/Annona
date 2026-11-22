# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shopping list of a plan at one chosen store, and what ticking an item does to the pantry.

The list is the plan's needs (every ingredient of every planned meal) minus the pantry, in whole
packs, priced at the store. Choosing another store builds another list (with its own ticks);
products the store does not sell are replaced by equivalents or reported as unavailable. The
pricing itself is :mod:`annona_core.shopping`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlmodel import Session

from annona_core.domain import (
    Household,
    PantryItem,
    Product,
    ShoppingItem,
    ShoppingList,
    Unit,
)
from annona_core.domain.units import Quantity, UnitConversionError
from annona_core.shopping import (
    DEFAULT_MIN_SAVING_CENTS,
    Alternative,
    Need,
    StoreComparison,
    StoreProduct,
    Unavailable,
    alternatives_for,
    compare_baskets,
    price_basket,
)

from ..db.repositories import (
    PlannedMealRepository,
    RecipeIngredientRepository,
    ShoppingItemRepository,
    ShoppingListRepository,
    SqlPantryRepository,
    SqlPriceRepository,
    SqlProductRepository,
)

_THOUSANDTH = Decimal("0.001")


class UnknownStore(LookupError):
    """The store has no priced products in the database."""


def _to_basis(amount: Decimal, unit: Unit, basis: Unit, product: Product) -> Decimal | None:
    try:
        return (
            Quantity(amount=amount, unit=unit)
            .to(
                basis,
                density_g_per_ml=product.density_g_per_ml,
                unit_weight_g=product.unit_weight_g,
            )
            .amount
        )
    except UnitConversionError:
        return None


def _per_100(product: Product) -> tuple[Decimal | None, Decimal | None]:
    n = product.nutrition
    return (None, None) if n is None else (n.energy_kcal, n.protein_g)


def plan_needs(
    session: Session, household_id: int, plan_id: int
) -> tuple[list[Need], dict[int, tuple[Decimal | None, Decimal | None]]]:
    """What the plan uses of each product (whole household) and how much the pantry holds."""
    ingredients = RecipeIngredientRepository(session)
    products = SqlProductRepository(session)
    totals: dict[int, tuple[Decimal, Unit]] = {}
    cache: dict[int, list] = {}
    for row in PlannedMealRepository(session).list(plan_id=plan_id):
        if row.recipe_id is None:
            continue
        if row.recipe_id not in cache:
            cache[row.recipe_id] = list(ingredients.list(recipe_id=row.recipe_id))
        for ing in cache[row.recipe_id]:
            amount, _ = totals.get(ing.product_id, (Decimal(0), ing.unit))
            totals[ing.product_id] = (amount + ing.amount * row.servings, ing.unit)

    pantry = list(SqlPantryRepository(session).for_household(household_id))
    needs: list[Need] = []
    nutrition: dict[int, tuple[Decimal | None, Decimal | None]] = {}
    for product_id, (amount, unit) in sorted(totals.items()):
        product = products.get(product_id)
        if product is None:
            continue
        have = Decimal(0)
        for item in pantry:
            if item.product_id == product_id:
                converted = _to_basis(item.amount, item.unit, unit, product)
                have += converted if converted is not None else Decimal(0)
        needs.append(
            Need(
                product_id=product_id,
                name=product.name,
                category=str(product.category),
                type=product.type,
                basis=str(unit),
                amount=amount.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP),
                in_pantry=have.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP),
            )
        )
        nutrition[product_id] = _per_100(product)
    return needs, nutrition


def store_products(session: Session, store_id: str, currency: str) -> list[StoreProduct]:
    """Products of the store with a current price and a pack size convertible to their basis."""
    prices = SqlPriceRepository(session)
    out = []
    for product in SqlProductRepository(session).list(store_id=store_id):
        if product.id is None or product.nutrition is None:
            continue
        price = prices.latest(product.id, store_id)
        if price is None or price.currency != currency:
            continue
        if product.package_amount is None or product.package_unit is None:
            continue
        basis = Unit(str(product.nutrition.basis))
        pack = _to_basis(product.package_amount, Unit(str(product.package_unit)), basis, product)
        if pack is None or pack <= 0:
            continue
        kcal, protein = _per_100(product)
        out.append(
            StoreProduct(
                product_id=product.id,
                name=product.name,
                category=str(product.category),
                type=product.type,
                basis=str(basis),
                pack_amount=pack,
                price_cents=price.amount_cents,
                kcal_per_100=kcal,
                protein_per_100=protein,
            )
        )
    return out


def compare_plan_stores(
    session: Session,
    household: Household,
    plan_id: int,
    store_ids: list[str],
    *,
    min_saving_cents: int = DEFAULT_MIN_SAVING_CENTS,
) -> StoreComparison:
    """Price the plan's needs (minus the pantry) at each store and compare them."""
    needs, nutrition = plan_needs(session, household.id, plan_id)
    baskets = []
    for store_id in dict.fromkeys(store_ids):  # no repeats, order kept
        products = store_products(session, store_id, household.currency)
        if not products:
            raise UnknownStore(f"no priced products for store {store_id!r}")
        baskets.append(price_basket(needs, products, store_id=store_id, nutrition=nutrition))
    return compare_baskets(baskets, min_saving_cents=min_saving_cents)


def find_list(session: Session, plan_id: int, store_id: str | None = None) -> ShoppingList | None:
    lists = [
        lst
        for lst in ShoppingListRepository(session).list(plan_id=plan_id)
        if store_id is None or lst.store_id == store_id
    ]
    return lists[-1] if lists else None


def build_list(
    session: Session, household: Household, plan_id: int, store_id: str, *, refresh: bool = False
) -> ShoppingList:
    """The list of a plan at a store; built on first request and kept (with its ticks)."""
    existing = find_list(session, plan_id, store_id)
    if existing is not None and not refresh:
        return existing
    products = store_products(session, store_id, household.currency)
    if not products:
        raise UnknownStore(f"no priced products for store {store_id!r}")
    if existing is not None and existing.id is not None:
        ShoppingListRepository(session).delete(existing.id)
    needs, nutrition = plan_needs(session, household.id, plan_id)
    basket = price_basket(needs, products, store_id=store_id, nutrition=nutrition)
    lists, items = ShoppingListRepository(session), ShoppingItemRepository(session)
    shopping_list = lists.add(
        ShoppingList(household_id=household.id, store_id=store_id, plan_id=plan_id)
    )
    assert shopping_list.id is not None
    merged: dict[int, tuple[int, int, int | None]] = {}  # product -> packs, price, replaces
    for line in basket.lines:
        packs, price, replaces = merged.get(line.product_id, (0, line.unit_price_cents, None))
        merged[line.product_id] = (packs + line.packs, price, line.replaces_product_id or replaces)
    for product_id, (packs, price, replaces) in sorted(merged.items()):
        items.add(
            ShoppingItem(
                list_id=shopping_list.id,
                product_id=product_id,
                packs=packs,
                unit_price_cents=price,
                replaces_product_id=replaces,
            )
        )
    return shopping_list


@dataclass
class ItemView:
    item: ShoppingItem
    name: str
    replaces: str | None
    alternatives: tuple[Alternative, ...]


@dataclass
class ListView:
    shopping_list: ShoppingList
    items: list[ItemView]
    unavailable: tuple[Unavailable, ...]

    @property
    def total_cents(self) -> int:
        return sum(i.item.packs * (i.item.unit_price_cents or 0) for i in self.items)


def view_list(session: Session, household: Household, shopping_list: ShoppingList) -> ListView:
    """The stored items, plus (recomputed with today's data) alternatives and unavailable ones."""
    assert shopping_list.id is not None and shopping_list.plan_id is not None
    catalogue = store_products(session, shopping_list.store_id, household.currency)
    by_id = {p.product_id: p for p in catalogue}
    needs, nutrition = plan_needs(session, household.id, shopping_list.plan_id)
    products = SqlProductRepository(session)
    views: list[ItemView] = []
    for item in ShoppingItemRepository(session).list(list_id=shopping_list.id):
        product = products.get(item.product_id)
        replaced = products.get(item.replaces_product_id) if item.replaces_product_id else None
        alternatives: tuple[Alternative, ...] = ()
        chosen = by_id.get(item.product_id)
        if replaced is not None and chosen is not None and replaced.id is not None:
            amount = chosen.pack_amount * item.packs
            need = Need(
                product_id=replaced.id,
                name=replaced.name,
                category=str(replaced.category),
                type=replaced.type,
                basis=chosen.basis,
                amount=amount,
            )
            alternatives = alternatives_for(
                need, chosen, catalogue, amount, nutrition.get(replaced.id, (None, None))
            )
        views.append(
            ItemView(
                item=item,
                name=product.name if product else "?",
                replaces=replaced.name if replaced else None,
                alternatives=alternatives,
            )
        )
    stored = {v.item.product_id for v in views} | {
        v.item.replaces_product_id for v in views if v.item.replaces_product_id
    }
    basket = price_basket(needs, catalogue, store_id=shopping_list.store_id, nutrition=nutrition)
    unavailable = tuple(u for u in basket.unavailable if u.product_id not in stored)
    return ListView(shopping_list=shopping_list, items=views, unavailable=unavailable)


# ---------------------------------------------------------------------------------------------
# Ticking an item: bought -> in the pantry
# ---------------------------------------------------------------------------------------------


@dataclass
class PantryEffect:
    product_id: int
    name: str
    amount: Decimal
    unit: str
    direction: str  # "added" | "removed"


def set_checked(
    session: Session, household: Household, item: ShoppingItem, checked: bool
) -> tuple[ShoppingItem, PantryEffect | None]:
    """Tick or untick an item. Ticking adds the packs to the pantry; unticking takes them back.

    Only a change of state has an effect, so repeating a request never doubles the stock. The
    amount taken back never goes below zero (some of it may have been cooked already).
    """
    repo = ShoppingItemRepository(session)
    if item.checked == checked:
        return item, None
    updated = repo.update(item.model_copy(update={"checked": checked}))
    product = SqlProductRepository(session).get(item.product_id)
    if (
        product is None
        or product.id is None
        or product.package_amount is None
        or product.package_unit is None
    ):
        return updated, None  # no pack size known: nothing can be added to the pantry
    unit = Unit(str(product.package_unit))
    amount = product.package_amount * item.packs
    pantry = SqlPantryRepository(session)
    rows = [
        i
        for i in pantry.for_household(household.id)
        if i.product_id == product.id and i.unit == unit
    ]
    if checked:
        if rows:
            row = rows[0]
            pantry.update(row.model_copy(update={"amount": row.amount + amount}))
        else:
            pantry.add(
                PantryItem(
                    household_id=household.id, product_id=product.id, amount=amount, unit=unit
                )
            )
        direction = "added"
    else:
        remaining = amount
        for row in sorted(rows, key=lambda r: r.added_at, reverse=True):
            take = min(remaining, row.amount)
            remaining -= take
            if row.amount - take <= 0 and row.id is not None:
                pantry.delete(row.id)
            else:
                pantry.update(row.model_copy(update={"amount": row.amount - take}))
            if remaining <= 0:
                break
        direction = "removed"
    effect = PantryEffect(
        product_id=product.id,
        name=product.name,
        amount=amount.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP),
        unit=str(unit),
        direction=direction,
    )
    return updated, effect
