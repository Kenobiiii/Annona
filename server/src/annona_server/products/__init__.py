# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manual product edits. Manual data always wins over automatic sources."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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


def generic_references(session: Session) -> dict[tuple[str, str], Product]:
    """Generic sample foods (no store) with nutrition, keyed by (category, type)."""
    refs: dict[tuple[str, str], Product] = {}
    for product in SqlProductRepository(session).list(store_id=None):
        if product.type and product.nutrition is not None:
            refs.setdefault((str(product.category), product.type), product)
    return refs


def with_sample_reference(product: Product, refs: dict[tuple[str, str], Product]) -> Product | None:
    """Fill missing data of a store product from the generic food of the same category and type.

    * nutrition, only if the product has none (it keeps ``source: sample`` and the generic
      ``source_ref``, so a label scan, Open Food Facts or a manual edit replaces it later);
    * weight per unit and density, only if missing;
    * allergens, only if unknown AND the generic food declares some (adding restrictions is
      safe; claiming "contains none" from a generic food is not, so that is never copied).

    Returns the updated product, or ``None`` if nothing applies.
    """
    if not product.type:
        return None
    ref = refs.get((str(product.category), product.type))
    if ref is None:
        return None
    update: dict = {}
    if product.nutrition is None and ref.nutrition is not None:
        update["nutrition"] = ref.nutrition
    if product.unit_weight_g is None and ref.unit_weight_g is not None:
        update["unit_weight_g"] = ref.unit_weight_g
    if product.density_g_per_ml is None and ref.density_g_per_ml is not None:
        update["density_g_per_ml"] = ref.density_g_per_ml
    if product.allergens is None and ref.allergens:
        update["allergens"] = ref.allergens
        update["allergens_source"] = NutritionSource.SAMPLE
    if not update:
        return None
    return product.model_copy(update=update)


def is_restricted_ean(ean: str) -> bool:
    """True for GS1 "restricted circulation" barcodes (EAN-13 starting with 2 or 02).

    Shops number their own weighed or in-store items from these ranges, so the same code means
    different products in different shops. Open Food Facts data under such a code does not
    describe the item on the shelf and must not be used for nutrition or allergens.
    """
    return len(ean) == 13 and ean.isdigit() and (ean[0] == "2" or ean.startswith("02"))


def drop_off_data(data: dict[str, Any]) -> None:
    """Remove nutrition and allergens that came from Open Food Facts, in a product's dict.

    Used for shop-internal barcodes (see :func:`is_restricted_ean`).
    """
    if data.get("nutrition") and data["nutrition"].get("source") == NutritionSource.OFF:
        data["nutrition"] = None
    if data.get("allergens_source") == NutritionSource.OFF:
        data["allergens"] = None
        data["allergens_source"] = None


def fill_from_sample_references(session: Session) -> list[Product]:
    """Apply :func:`with_sample_reference` to every store product; returns the updated ones."""
    repo = SqlProductRepository(session)
    refs = generic_references(session)
    updated = []
    for product in repo.list():
        if product.store_id is None:
            continue
        new = with_sample_reference(product, refs)
        if new is not None:
            updated.append(repo.update(new))
    return updated


def drop_untrusted_off_data(session: Session) -> list[Product]:
    """Remove Open Food Facts data stored under shop-internal barcodes, then refill from the
    generic references (flagged ``sample``). Returns the products that changed."""
    repo = SqlProductRepository(session)
    refs = generic_references(session)
    changed = []
    for product in repo.list():
        if product.store_id is None or not product.ean or not is_restricted_ean(product.ean):
            continue
        data = product.model_dump()
        drop_off_data(data)
        cleaned = Product.model_validate(data)
        cleaned = with_sample_reference(cleaned, refs) or cleaned
        if cleaned != product:
            changed.append(repo.update(cleaned))
    return changed
