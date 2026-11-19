# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ingestion: provider products and prices -> database, with OFF nutrition and classification.

Idempotent: running the same ingestion twice changes nothing. Data with a higher-priority source
(manual edits, label scans) is never overwritten. A new price row is stored only when the price
changed or it was observed on a new day.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import islice
from typing import Any

from sqlmodel import Session

from annona_core.domain import (
    NutritionSource,
    Product,
    category_source_may_replace,
    nutrition_source_may_replace,
)
from annona_providers.base import (
    ProviderPrice,
    ProviderProduct,
    SupermarketProvider,
    to_domain_price,
)

from ..db.repositories import SqlPriceRepository, SqlProductRepository
from .classify import (
    Classification,
    ClassificationInput,
    Classifier,
    LLMClassifierStub,
    RuleClassifier,
    classify,
)
from .llm_classify import LLMClassifier
from .off import OffProduct, OpenFoodFactsClient

OPT_IN_MAX_ITEMS = 50
PRICE_BATCH = 50
DEFAULT_CLASSIFIERS: tuple[Classifier, ...] = (RuleClassifier(), LLMClassifierStub())


@dataclass
class IngestReport:
    products_created: int = 0
    products_updated: int = 0
    products_unchanged: int = 0
    prices_added: int = 0
    prices_unchanged: int = 0
    nutrition_from_off: int = 0
    off_not_found: int = 0
    without_ean: int = 0
    unclassified: list[str] = field(default_factory=list)


def ingest(
    session: Session,
    provider: SupermarketProvider,
    *,
    skus: Sequence[str] = (),
    queries: Sequence[str] = (),
    catalog: bool = False,
    limit: int | None = None,
    off: OpenFoodFactsClient | None = None,
    classifiers: Sequence[Classifier] = DEFAULT_CLASSIFIERS,
    llm_classifier: LLMClassifier | None = None,
) -> IngestReport:
    """Ingest the given products (by sku, by search query and/or the whole catalogue).

    Rules classify first; products they miss go to ``llm_classifier`` in batches, if given.
    """
    report = IngestReport()
    items = _collect(provider, skus, queries, catalog, limit)
    off_products = [_lookup_off(off, item, report) for item in items]
    inputs = [
        ClassificationInput(i.name, i.category_path, o.categories if o else ())
        for i, o in zip(items, off_products, strict=True)
    ]
    classifications = [classify(x, classifiers) for x in inputs]
    missing = [n for n, c in enumerate(classifications) if c is None]
    if llm_classifier is not None and missing:
        for n, result in zip(
            missing, llm_classifier.classify_batch([inputs[n] for n in missing]), strict=True
        ):
            classifications[n] = result

    products = SqlProductRepository(session)
    stored: dict[str, Product] = {}
    for item, off_product, result in zip(items, off_products, classifications, strict=True):
        stored[item.store_sku] = _upsert(
            products, item, provider.store_id, off_product, result, report
        )

    prices = SqlPriceRepository(session)
    skus_to_price = list(stored)
    for start in range(0, len(skus_to_price), PRICE_BATCH):
        for price in provider.get_prices(skus_to_price[start : start + PRICE_BATCH]):
            product = stored.get(price.store_sku)
            if product is not None and product.id is not None:
                _record_price(prices, price, product.id, provider.store_id, report)
    return report


def _collect(
    provider: SupermarketProvider,
    skus: Sequence[str],
    queries: Sequence[str],
    catalog: bool,
    limit: int | None,
) -> list[ProviderProduct]:
    if provider.info.opt_in and len(set(skus)) > OPT_IN_MAX_ITEMS:
        raise ValueError(
            f"{provider.info.id} is personal-use only: at most {OPT_IN_MAX_ITEMS} products per run"
        )
    found: dict[str, ProviderProduct] = {}

    def add(items: Iterable[ProviderProduct]) -> None:
        for item in items:
            found.setdefault(item.store_sku, item)

    if catalog:
        add(islice(provider.iter_catalog(), limit) if limit else provider.iter_catalog())
    for query in queries:
        add(provider.search(query, limit=limit or 20))
    for sku in skus:
        if sku not in found and (item := provider.get_product(sku)) is not None:
            found[sku] = item

    items = list(found.values())
    if limit is not None:
        items = items[:limit]
    if provider.info.opt_in and len(items) > OPT_IN_MAX_ITEMS:
        raise ValueError(
            f"{provider.info.id} is personal-use only: at most {OPT_IN_MAX_ITEMS} products per run"
        )
    # Search results may lack the barcode; the product detail has it.
    return [(provider.get_product(i.store_sku) or i) if i.ean is None else i for i in items]


def _lookup_off(
    off: OpenFoodFactsClient | None, item: ProviderProduct, report: IngestReport
) -> OffProduct | None:
    if item.ean is None:
        report.without_ean += 1
        return None
    if off is None:
        return None
    result = off.lookup(item.ean)
    if result is None:
        report.off_not_found += 1
    return result


def _upsert(
    repo: SqlProductRepository,
    item: ProviderProduct,
    store_id: str,
    off_product: OffProduct | None,
    result: Classification | None,
    report: IngestReport,
) -> Product:
    existing = repo.get_by_store_sku(store_id, item.store_sku)
    data: dict[str, Any] = (
        existing.model_dump()
        if existing
        else {"name": item.name, "store_id": store_id, "store_sku": item.store_sku}
    )
    # Store facts: the store is the authority for name, brand, barcode and package.
    data["name"] = item.name
    data["brand"] = item.brand
    data["ean"] = item.ean or data.get("ean")
    if item.package_amount is not None:
        data["package_amount"] = item.package_amount
        data["package_unit"] = item.package_unit

    if result is None:
        if data.get("category_source") is None:
            report.unclassified.append(f"{store_id}:{item.store_sku} {item.name}")
    elif category_source_may_replace(data.get("category_source"), result.source):
        data.update(category=result.category, type=result.type, category_source=result.source)

    if off_product is not None:
        current = data["nutrition"]["source"] if data.get("nutrition") else None
        if off_product.nutrition and nutrition_source_may_replace(current, NutritionSource.OFF):
            new_nutrition = off_product.nutrition.model_dump()
            if data.get("nutrition") != new_nutrition:
                data["nutrition"] = new_nutrition
                report.nutrition_from_off += 1
        if off_product.allergens is not None and nutrition_source_may_replace(
            data.get("allergens_source"), NutritionSource.OFF
        ):
            data["allergens"] = off_product.allergens
            data["allergens_source"] = NutritionSource.OFF

    product = Product.model_validate(data)
    if existing is None:
        report.products_created += 1
        return repo.add(product)
    if product == existing:
        report.products_unchanged += 1
        return existing
    report.products_updated += 1
    return repo.update(product)


def _record_price(
    repo: SqlPriceRepository,
    price: ProviderPrice,
    product_id: int,
    store_id: str,
    report: IngestReport,
) -> None:
    latest = repo.latest(product_id, store_id)
    if (
        latest is not None
        and latest.amount_cents == price.amount_cents
        and latest.observed_at.date() == price.observed_at.date()
    ):
        report.prices_unchanged += 1
        return
    repo.add(to_domain_price(price, product_id, store_id))
    report.prices_added += 1
