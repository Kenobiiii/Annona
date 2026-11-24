# SPDX-License-Identifier: AGPL-3.0-or-later
"""Product search, details, manual edits (manual data always wins) and products you add."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from annona_core.domain import (
    Allergen,
    Category,
    CategorySource,
    NutritionFacts,
    NutritionSource,
    Product,
    Unit,
)

from ...db.repositories import SqlPriceRepository, SqlProductRepository
from ...products import set_allergens
from ..deps import SessionDep
from ..errors import APIError
from ..schemas import Page, paginate

router = APIRouter(tags=["products"])


class ProductOut(BaseModel):
    product: Product
    latest_price_cents: int | None
    currency: str | None
    unit_price_cents: int | None
    unit_price_per: str | None


def _out(session, product: Product) -> ProductOut:
    price = (
        SqlPriceRepository(session).latest(product.id, product.store_id)
        if product.store_id and product.id
        else None
    )
    unit = price.unit_price(product) if price is not None and product.package else None
    return ProductOut(
        product=product,
        latest_price_cents=price.amount_cents if price else None,
        currency=price.currency if price else None,
        unit_price_cents=unit.amount_cents if unit else None,
        unit_price_per=unit.per if unit else None,
    )


@router.get("/products", response_model=Page[ProductOut])
def search_products(
    session: SessionDep,
    q: str = "",
    store: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> Page[ProductOut]:
    repo = SqlProductRepository(session)
    found = repo.search(q, limit=1000) if q else list(repo.list())
    if store is not None:
        found = [p for p in found if p.store_id == store]
    paged = paginate(found, page, size)
    return Page(
        items=[_out(session, p) for p in paged.items], page=page, size=size, total=paged.total
    )


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, session: SessionDep) -> ProductOut:
    product = SqlProductRepository(session).get(product_id)
    if product is None:
        raise APIError(404, "not_found", f"product {product_id} not found")
    return _out(session, product)


class ProductCreate(BaseModel):
    """A product you add yourself, e.g. a receipt line that is not in the catalogue yet.

    It is a generic product (no store): there is no store SKU to give it. Its prices still carry
    the store they were paid at. Nutrition and allergens start unknown; set them later.
    """

    name: str = Field(min_length=1, max_length=200)
    category: Category = Category.OTHER
    package_amount: Decimal | None = Field(default=None, gt=0)
    package_unit: Unit | None = None


def _same_name(a: str, b: str) -> bool:
    return " ".join(a.casefold().split()) == " ".join(b.casefold().split())


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(body: ProductCreate, session: SessionDep, response: Response) -> ProductOut:
    """Add a product. If a product you added has the same name, that one is returned (200)."""
    name = " ".join(body.name.split())
    if not name:
        raise APIError(422, "invalid", "the name is empty")
    if (body.package_amount is None) != (body.package_unit is None):
        raise APIError(422, "invalid", "package_amount and package_unit go together")
    repo = SqlProductRepository(session)
    for existing in repo.list():
        if existing.store_id is None and _same_name(existing.name, name):
            response.status_code = 200
            return _out(session, existing)
    product = repo.add(
        Product(
            name=name,
            category=body.category,
            category_source=CategorySource.MANUAL,
            package_amount=body.package_amount,
            package_unit=body.package_unit,
        )
    )
    return _out(session, product)


class NutritionIn(BaseModel):
    basis: Unit = Unit.G
    energy_kcal: Decimal = Field(ge=0)
    protein_g: Decimal = Field(ge=0)
    fat_g: Decimal = Field(ge=0)
    carbohydrates_g: Decimal = Field(ge=0)
    saturated_fat_g: Decimal | None = Field(default=None, ge=0)
    sugars_g: Decimal | None = Field(default=None, ge=0)
    fiber_g: Decimal | None = Field(default=None, ge=0)
    salt_g: Decimal | None = Field(default=None, ge=0)


class ProductPatch(BaseModel):
    """Only the fields sent are changed. Manual data is never overwritten by automatic sources."""

    allergens: list[Allergen] | None = None  # [] = contains none of the EU 14
    allergens_unknown: bool = False  # clear a manual entry
    category: Category | None = None
    type: str | None = Field(default=None, max_length=100)
    nutrition: NutritionIn | None = None
    unit_weight_g: Decimal | None = Field(default=None, gt=0)
    density_g_per_ml: Decimal | None = Field(default=None, gt=0)


@router.patch("/products/{product_id}", response_model=ProductOut)
def patch_product(product_id: int, body: ProductPatch, session: SessionDep) -> ProductOut:
    repo = SqlProductRepository(session)
    product = repo.get(product_id)
    if product is None:
        raise APIError(404, "not_found", f"product {product_id} not found")
    if body.allergens_unknown:
        product = set_allergens(session, product_id, None)
    elif body.allergens is not None:
        product = set_allergens(session, product_id, body.allergens)
    update: dict = {}
    if body.category is not None:
        update |= {"category": body.category, "category_source": CategorySource.MANUAL}
    if body.type is not None:
        update["type"] = body.type
    if body.nutrition is not None:
        update["nutrition"] = NutritionFacts(
            **body.nutrition.model_dump(), source=NutritionSource.MANUAL, source_ref="manual"
        )
    if body.unit_weight_g is not None:
        update["unit_weight_g"] = body.unit_weight_g
    if body.density_g_per_ml is not None:
        update["density_g_per_ml"] = body.density_g_per_ml
    if update:
        product = repo.update(product.model_copy(update=update))
    return _out(session, product)


class CatalogStore(BaseModel):
    store_id: str
    products: int
    priced: int  # products with at least one price


@router.get("/catalog/stores", response_model=list[CatalogStore])
def catalog_stores(session: SessionDep) -> list[CatalogStore]:
    """Stores that have products in the database (the ones a plan can be made for)."""
    from sqlmodel import select

    from ...db.tables import PriceRow

    priced_ids = set(session.exec(select(PriceRow.product_id).distinct()))
    stores: dict[str, CatalogStore] = {}
    for product in SqlProductRepository(session).list():
        if product.store_id is None:
            continue
        entry = stores.setdefault(
            product.store_id, CatalogStore(store_id=product.store_id, products=0, priced=0)
        )
        entry.products += 1
        entry.priced += product.id in priced_ids
    return sorted(stores.values(), key=lambda s: s.store_id)
