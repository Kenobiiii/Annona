# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shopping list of a plan at one store, ticking items, and the stores to choose from."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...db.repositories import ShoppingItemRepository, ShoppingListRepository
from ...shopping import (
    ItemView,
    ListView,
    PantryEffect,
    UnknownStore,
    build_list,
    find_list,
    set_checked,
    view_list,
)
from ..deps import HouseholdDep, SessionDep
from ..errors import APIError
from .plans import _plan

router = APIRouter(tags=["shopping"])


class AlternativeOut(BaseModel):
    product_id: int
    name: str
    packs: int
    price_cents: int = Field(description="per pack")
    cost_cents: int = Field(description="for the packs needed")
    extra_cost_cents: int = Field(description="versus the suggested product (negative = cheaper)")
    kcal_diff_pct: Decimal | None = Field(description="per 100 g/ml, versus what the menu used")
    protein_diff_pct: Decimal | None


class PantryEffectOut(BaseModel):
    product_id: int
    name: str
    amount: Decimal
    unit: str
    direction: str = Field(description="added | removed")


class ShoppingItemOut(BaseModel):
    id: int
    product_id: int
    name: str
    packs: int
    unit_price_cents: int | None
    checked: bool
    replaces_product_id: int | None = None
    replaces: str | None = Field(default=None, description="the product this one replaces")
    alternatives: list[AlternativeOut] = Field(default_factory=list)
    pantry_effect: PantryEffectOut | None = Field(
        default=None, description="what ticking or unticking did to the pantry (PATCH only)"
    )


class UnavailableOut(BaseModel):
    product_id: int
    name: str
    amount: Decimal
    unit: str
    reason: str = Field(description="not_sold (no equivalent in this store) | no_type")


class ShoppingListOut(BaseModel):
    store_id: str
    total_cents: int
    items: list[ShoppingItemOut]
    unavailable: list[UnavailableOut] = Field(default_factory=list)


def _item_out(view: ItemView, effect: PantryEffect | None = None) -> ShoppingItemOut:
    item = view.item
    return ShoppingItemOut(
        id=item.id,  # type: ignore[arg-type]
        product_id=item.product_id,
        name=view.name,
        packs=item.packs,
        unit_price_cents=item.unit_price_cents,
        checked=item.checked,
        replaces_product_id=item.replaces_product_id,
        replaces=view.replaces,
        alternatives=[
            AlternativeOut(**a.model_dump(exclude={"pack_amount"})) for a in view.alternatives
        ],
        pantry_effect=PantryEffectOut(**effect.__dict__) if effect else None,
    )


def _list_out(view: ListView) -> ShoppingListOut:
    return ShoppingListOut(
        store_id=view.shopping_list.store_id,
        total_cents=view.total_cents,
        items=[_item_out(v) for v in view.items],
        unavailable=[
            UnavailableOut(
                product_id=u.product_id,
                name=u.name,
                amount=u.amount,
                unit=u.basis,
                reason=u.reason,
            )
            for u in view.unavailable
        ],
    )


@router.get("/plans/{plan_id}/shopping-list", response_model=ShoppingListOut)
def shopping_list(
    plan_id: int, session: SessionDep, household: HouseholdDep, store_id: str | None = None
) -> ShoppingListOut:
    """The plan's list at a store (default: the most recent one)."""
    _plan(session, household.id, plan_id)
    found = find_list(session, plan_id, store_id)
    if found is None:
        where = f" at {store_id}" if store_id else ""
        raise APIError(404, "not_found", f"plan {plan_id} has no shopping list{where}")
    return _list_out(view_list(session, household, found))


class BuildListIn(BaseModel):
    store_id: str
    refresh: bool = Field(default=False, description="rebuild it (loses the ticks)")


@router.post("/plans/{plan_id}/shopping-list", response_model=ShoppingListOut)
def build_shopping_list(
    plan_id: int, body: BuildListIn, session: SessionDep, household: HouseholdDep
) -> ShoppingListOut:
    """The plan's list at the chosen store: built the first time, then kept with its ticks."""
    _plan(session, household.id, plan_id)
    try:
        built = build_list(session, household, plan_id, body.store_id, refresh=body.refresh)
    except UnknownStore as error:
        raise APIError(404, "unknown_store", str(error)) from error
    return _list_out(view_list(session, household, built))


class ShoppingItemPatch(BaseModel):
    checked: bool


@router.patch("/shopping-items/{item_id}", response_model=ShoppingItemOut)
def check_shopping_item(
    item_id: int, body: ShoppingItemPatch, session: SessionDep, household: HouseholdDep
) -> ShoppingItemOut:
    """Tick (bought: the packs go to the pantry) or untick (they are taken back) an item."""
    items = ShoppingItemRepository(session)
    item = items.get(item_id)
    parent = ShoppingListRepository(session).get(item.list_id) if item else None
    if item is None or parent is None or parent.household_id != household.id:
        raise APIError(404, "not_found", f"shopping item {item_id} not found")
    updated, effect = set_checked(session, household, item, body.checked)
    view = next(v for v in view_list(session, household, parent).items if v.item.id == updated.id)
    return _item_out(view, effect)
