# SPDX-License-Identifier: AGPL-3.0-or-later
"""Price refresh, run daily by the scheduler or on demand through the API.

Providers come from ``ANNONA_REFRESH_PROVIDERS``, e.g.::

    open_prices:brand=Mercadona;mercadona:postal_code=28001,accept_notice=yes

* open data providers (Open Prices) refresh their catalogue (up to
  ``ANNONA_REFRESH_CATALOG_LIMIT`` products, default 500);
* opt-in, personal-use providers (Mercadona) refresh ONLY the products the household follows
  (pantry, active plans, latest shopping lists), at most 50, and only if the notice was
  accepted in the configuration (``accept_notice=yes``).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from sqlmodel import Session, col, select

from annona_core.domain import PlanStatus
from annona_providers.registry import create_provider

from .config import load_env
from .db.tables import (
    MealPlanRow,
    PantryItemRow,
    PlannedMealRow,
    ProductRow,
    RecipeIngredientRow,
    ShoppingItemRow,
    ShoppingListRow,
)
from .ingest import ingest
from .ingest.off import OpenFoodFactsClient
from .ingest.service import OPT_IN_MAX_ITEMS


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    config: dict[str, str]
    accept_notice: bool = False


def parse_specs(text: str) -> list[ProviderSpec]:
    specs = []
    for part in filter(None, (p.strip() for p in text.split(";"))):
        provider_id, _, rest = part.partition(":")
        config = dict(kv.split("=", 1) for kv in filter(None, rest.split(",")))
        accept = config.pop("accept_notice", "").lower() in ("yes", "true", "1")
        specs.append(ProviderSpec(provider_id.strip(), config, accept))
    return specs


def configured_specs() -> list[ProviderSpec]:
    load_env()
    return parse_specs(os.environ.get("ANNONA_REFRESH_PROVIDERS", ""))


def followed_skus(session: Session, store_id: str) -> list[str]:
    """Store products the household uses: pantry, active plans and the latest shopping lists."""
    ids: set[int] = set(session.exec(select(PantryItemRow.product_id)))
    active = select(MealPlanRow.id).where(MealPlanRow.status == PlanStatus.ACTIVE)
    recipes = select(PlannedMealRow.recipe_id).where(col(PlannedMealRow.plan_id).in_(active))
    ids |= set(
        session.exec(
            select(RecipeIngredientRow.product_id).where(
                col(RecipeIngredientRow.recipe_id).in_(recipes)
            )
        )
    )
    latest = select(ShoppingListRow.id).order_by(col(ShoppingListRow.id).desc()).limit(3)
    ids |= set(
        session.exec(
            select(ShoppingItemRow.product_id).where(col(ShoppingItemRow.list_id).in_(latest))
        )
    )
    rows = session.exec(
        select(ProductRow.store_sku)
        .where(ProductRow.store_id == store_id, col(ProductRow.id).in_(ids))
        .order_by(col(ProductRow.id))
    )
    return [sku for sku in rows if sku]


def refresh(session: Session, specs: list[ProviderSpec] | None = None) -> dict[str, Any]:
    specs = configured_specs() if specs is None else specs
    limit = int(os.environ.get("ANNONA_REFRESH_CATALOG_LIMIT", "500"))
    results: dict[str, Any] = {}
    off = OpenFoodFactsClient(session)
    try:
        for spec in specs:
            provider = create_provider(
                spec.provider_id, accept_notice=spec.accept_notice, **spec.config
            )
            try:
                if provider.info.opt_in:
                    skus = followed_skus(session, provider.store_id)[:OPT_IN_MAX_ITEMS]
                    report = ingest(session, provider, skus=skus, off=off) if skus else None
                else:
                    report = ingest(session, provider, catalog=True, limit=limit, off=off)
            finally:
                provider.close()
            results[provider.store_id] = (
                {"skipped": "no followed products"}
                if report is None
                else {k: (len(v) if isinstance(v, list) else v) for k, v in asdict(report).items()}
            )
    finally:
        off.close()
    return results
