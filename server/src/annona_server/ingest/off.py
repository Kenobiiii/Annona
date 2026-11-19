# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open Food Facts (OFF) lookups by barcode, cached in the database.

API: ``GET https://world.openfoodfacts.org/api/v2/product/{ean}?fields=...``
Rules (https://openfoodfacts.github.io/openfoodfacts-server/api/): at most 15 product reads per
minute per IP, and a User-Agent ``AppName/Version (ContactEmail)``. Data: ODbL 1.0.

Every answer, including "not found", is cached for :data:`CACHE_DAYS` so OFF is asked as little
as possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlmodel import Session

from annona_core.domain import Allergen, NutritionFacts, NutritionSource, Unit
from annona_providers import __version__ as providers_version
from annona_providers.http import PROJECT_URL, PoliteTransport

from ..config import contact_email
from ..db.tables import OffCacheRow

API = "https://world.openfoodfacts.org/api/v2/product"
FIELDS = (
    "code,product_name,brands,nutrition_data_per,product_quantity_unit,nutriments,"
    "allergens_tags,categories_tags"
)
CACHE_DAYS = 30
MIN_INTERVAL_SECONDS = 4.0  # 15 requests/minute

# OFF allergen taxonomy -> EU 14 (taxonomy checked 2026-11-19). "en:none" = explicitly none.
OFF_ALLERGENS: dict[str, Allergen] = {
    "en:gluten": Allergen.GLUTEN,
    "en:crustaceans": Allergen.CRUSTACEANS,
    "en:eggs": Allergen.EGGS,
    "en:fish": Allergen.FISH,
    "en:peanuts": Allergen.PEANUTS,
    "en:soybeans": Allergen.SOYBEANS,
    "en:milk": Allergen.MILK,
    "en:nuts": Allergen.NUTS,
    "en:celery": Allergen.CELERY,
    "en:mustard": Allergen.MUSTARD,
    "en:sesame-seeds": Allergen.SESAME,
    "en:sulphur-dioxide-and-sulphites": Allergen.SULPHITES,
    "en:lupin": Allergen.LUPIN,
    "en:molluscs": Allergen.MOLLUSCS,
}
_NUTRIENTS = {
    "energy_kcal": "energy-kcal_100g",
    "protein_g": "proteins_100g",
    "fat_g": "fat_100g",
    "saturated_fat_g": "saturated-fat_100g",
    "carbohydrates_g": "carbohydrates_100g",
    "sugars_g": "sugars_100g",
    "fiber_g": "fiber_100g",
    "salt_g": "salt_100g",
}
_REQUIRED = ("energy_kcal", "protein_g", "fat_g", "carbohydrates_g")


def off_user_agent() -> str:
    email = contact_email()
    contact = email if email else f"+{PROJECT_URL}"
    return f"Annona/{providers_version} ({contact})"


@dataclass(frozen=True)
class OffProduct:
    ean: str
    name: str | None
    nutrition: NutritionFacts | None
    allergens: list[Allergen] | None  # None = unknown
    categories: tuple[str, ...]


class OpenFoodFactsClient:
    def __init__(
        self,
        session: Session,
        *,
        transport: httpx.BaseTransport | None = None,
        now: Any = None,
    ) -> None:
        self.session = session
        self._now = now or (lambda: datetime.now(UTC))
        self._client = httpx.Client(
            transport=transport
            or PoliteTransport(min_interval=MIN_INTERVAL_SECONDS, agent=off_user_agent()),
            timeout=20.0,
        )

    def close(self) -> None:
        self._client.close()

    def lookup(self, ean: str) -> OffProduct | None:
        """The OFF product for a barcode, or None if OFF does not know it."""
        row = self.session.get(OffCacheRow, ean)
        if row is None or row.fetched_at < self._now() - timedelta(days=CACHE_DAYS):
            row = self._fetch(ean, row)
        return parse_off_product(ean, row.payload) if row.found and row.payload else None

    def _fetch(self, ean: str, row: OffCacheRow | None) -> OffCacheRow:
        response = self._client.get(f"{API}/{ean}", params={"fields": FIELDS})
        if response.status_code not in (200, 404):
            response.raise_for_status()
        data = response.json() if response.content else {}
        found = response.status_code == 200 and data.get("status") == 1
        row = row or OffCacheRow(ean=ean, found=found, fetched_at=self._now())
        row.found = found
        row.payload = data.get("product") if found else None
        row.fetched_at = self._now()
        self.session.add(row)
        self.session.flush()
        return row


def parse_off_product(ean: str, product: dict[str, Any]) -> OffProduct:
    return OffProduct(
        ean=ean,
        name=(product.get("product_name") or "").strip() or None,
        nutrition=parse_nutrition(ean, product),
        allergens=parse_allergens(product.get("allergens_tags")),
        categories=tuple(product.get("categories_tags") or ()),
    )


def parse_nutrition(ean: str, product: dict[str, Any]) -> NutritionFacts | None:
    """OFF ``*_100g`` values are per 100 g, or per 100 ml for liquids."""
    nutriments = product.get("nutriments") or {}
    values: dict[str, Decimal] = {}
    for ours, key in _NUTRIENTS.items():
        raw = nutriments.get(key)
        if raw is None or raw == "":
            continue
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            continue
        if value.is_finite() and value >= 0:
            values[ours] = value
    if any(name not in values for name in _REQUIRED):
        return None
    per = str(product.get("nutrition_data_per") or "").lower()
    unit = str(product.get("product_quantity_unit") or "").lower()
    basis = Unit.ML if per.startswith("100ml") or unit in ("ml", "cl", "l") else Unit.G
    return NutritionFacts(
        basis=basis, source=NutritionSource.OFF, source_ref=f"off:{ean}", **values
    )


def parse_allergens(tags: Any) -> list[Allergen] | None:
    """EU-14 allergens; ``None`` (unknown) when OFF lists nothing, ``[]`` for ``en:none``."""
    if not tags:
        return None
    found = [OFF_ALLERGENS[t] for t in tags if t in OFF_ALLERGENS]
    if found:
        return sorted(set(found), key=list(Allergen).index)
    return [] if "en:none" in tags else None
