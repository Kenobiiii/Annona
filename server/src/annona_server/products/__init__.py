# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manual product edits. Manual data always wins over automatic sources."""

from __future__ import annotations

from collections.abc import Sequence

from sqlmodel import Session

from annona_core.domain import Allergen, CategorySource, NutritionSource, Product
from annona_core.domain.enums import Category

from ..db.repositories import NotFoundError, SqlProductRepository


def set_allergens(
    session: Session, product_id: int, allergens: Sequence[Allergen] | None
) -> Product:
    """Set a product's allergens by hand: a list, ``[]`` for "contains none", ``None`` to clear.

    Manual allergens are never overwritten by Open Food Facts or other automatic sources.
    Clearing (``None``) marks them unknown again and lets automatic sources fill them.
    """
    repo = SqlProductRepository(session)
    product = repo.get(product_id)
    if product is None:
        raise NotFoundError(f"product {product_id} not found")
    if allergens is None:
        update = {"allergens": None, "allergens_source": None}
    else:
        unique = sorted(set(allergens), key=list(Allergen).index)
        update = {"allergens": unique, "allergens_source": NutritionSource.MANUAL}
    return repo.update(product.model_copy(update=update))


def set_category(
    session: Session, product_id: int, category: Category, type_: str | None = None
) -> Product:
    repo = SqlProductRepository(session)
    product = repo.get(product_id)
    if product is None:
        raise NotFoundError(f"product {product_id} not found")
    return repo.update(
        product.model_copy(
            update={"category": category, "type": type_, "category_source": CategorySource.MANUAL}
        )
    )


def products_with_unknown_allergens(session: Session) -> list[Product]:
    return [p for p in SqlProductRepository(session).list() if p.allergens is None]
