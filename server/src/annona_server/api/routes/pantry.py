# SPDX-License-Identifier: AGPL-3.0-or-later
"""The household pantry."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from annona_core.domain import PantryItem, Unit

from ...db.repositories import SqlPantryRepository, SqlProductRepository
from ..deps import HouseholdDep, SessionDep
from ..errors import APIError
from ..schemas import Page, paginate

router = APIRouter(tags=["pantry"])


class PantryIn(BaseModel):
    product_id: int
    amount: Decimal = Field(ge=0)
    unit: Unit
    expires_at: date | None = None


class PantryOut(PantryItem):
    """A pantry item with the product's name and category, so clients can group and label it."""

    name: str
    category: str


def _out(session, item: PantryItem) -> PantryOut:
    product = SqlProductRepository(session).get(item.product_id)
    return PantryOut(
        **item.model_dump(),
        name=product.name if product else "?",
        category=str(product.category) if product else "other",
    )


def _item(session, household, item_id: int) -> PantryItem:
    item = SqlPantryRepository(session).get(item_id)
    if item is None or item.household_id != household.id:
        raise APIError(404, "not_found", f"pantry item {item_id} not found")
    return item


@router.get("/pantry", response_model=Page[PantryOut])
def list_pantry(
    session: SessionDep,
    household: HouseholdDep,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> Page[PantryOut]:
    items = [_out(session, i) for i in SqlPantryRepository(session).for_household(household.id)]
    return paginate(items, page, size)


@router.post("/pantry", response_model=PantryOut, status_code=status.HTTP_201_CREATED)
def add_pantry(body: PantryIn, session: SessionDep, household: HouseholdDep) -> PantryOut:
    if SqlProductRepository(session).get(body.product_id) is None:
        raise APIError(404, "not_found", f"product {body.product_id} not found")
    item = SqlPantryRepository(session).add(
        PantryItem(household_id=household.id, **body.model_dump())
    )
    return _out(session, item)


@router.put("/pantry/{item_id}", response_model=PantryOut)
def update_pantry(
    item_id: int, body: PantryIn, session: SessionDep, household: HouseholdDep
) -> PantryOut:
    current = _item(session, household, item_id)
    updated = SqlPantryRepository(session).update(current.model_copy(update=body.model_dump()))
    return _out(session, updated)


@router.delete("/pantry/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pantry(item_id: int, session: SessionDep, household: HouseholdDep) -> None:
    _item(session, household, item_id)
    SqlPantryRepository(session).delete(item_id)
